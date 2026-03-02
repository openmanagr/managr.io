"""
Tool Registry — routes agent tasks to the correct tool implementation.

Why this pattern matters:
- The orchestrator (LangGraph graph) never imports tools directly
- Adding a new tool (e.g. bank feed connector) = register it here, no graph changes
- Each tool is a callable that takes AgentState and returns a partial state update
- The registry also handles: timeout wrapping, error normalisation, duration tracking

Tool contract:
    async def my_tool(state: AgentState) -> dict:
        # Returns a PARTIAL state update (only the keys this tool changes)
        return {"financial_statements": ..., "current_step": "reconcile"}
"""

import asyncio
import time
import logging
from typing import Callable, Awaitable, Optional
from dataclasses import dataclass, field
from datetime import datetime

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


# ── Tool Descriptor ───────────────────────────────────────────────────────────

@dataclass
class Tool:
    """
    Metadata + callable for a single agent tool.

    name:        Unique key used to invoke the tool
    description: Shown to Claude when it needs to decide which tool to call
    fn:          The async function — takes AgentState, returns partial state dict
    timeout_s:   Max seconds before we abort and flag for human review
    retries:     How many times to retry on transient failure
    phase:       "p0" | "p1" | "p2" — matches the architecture doc phases
    """
    name: str
    description: str
    fn: Callable[[AgentState], Awaitable[dict]]
    timeout_s: int = 60
    retries: int = 2
    phase: str = "p0"
    tags: list[str] = field(default_factory=list)


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Central registry for all agent tools.

    Usage:
        registry = ToolRegistry()
        registry.register(Tool(name="fetch_financials", ...))
        result = await registry.invoke("fetch_financials", state)
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises if name already taken."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        logger.info(f"[ToolRegistry] Registered tool: {tool.name} (phase={tool.phase})")

    def get(self, name: str) -> Tool:
        """Retrieve a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found. Registered: {list(self._tools.keys())}")
        return self._tools[name]

    def list_tools(self, phase: Optional[str] = None) -> list[dict]:
        """
        List all registered tools, optionally filtered by phase.
        This is passed to Claude as context so it can decide what to call.
        """
        tools = self._tools.values()
        if phase:
            tools = [t for t in tools if t.phase == phase]
        return [
            {"name": t.name, "description": t.description, "phase": t.phase, "tags": t.tags}
            for t in tools
        ]

    async def invoke(self, name: str, state: AgentState) -> dict:
        """
        Invoke a tool by name with full retry + timeout handling.

        Returns a partial state update dict on success.
        On failure, returns an error entry to be merged into state.errors.
        Never raises — failures are encoded into the returned dict.
        """
        tool = self.get(name)
        start = time.monotonic()

        for attempt in range(tool.retries + 1):
            try:
                logger.info(f"[{name}] Invoking (attempt {attempt + 1}/{tool.retries + 1})")

                result = await asyncio.wait_for(
                    tool.fn(state),
                    timeout=tool.timeout_s,
                )

                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(f"[{name}] Completed in {duration_ms}ms")

                # Always append a timing record
                result["step_durations"] = [{
                    "step": name,
                    "duration_ms": duration_ms,
                    "attempt": attempt + 1,
                    "status": "ok",
                }]
                result["updated_at"] = datetime.utcnow().isoformat() + "Z"
                return result

            except asyncio.TimeoutError:
                logger.warning(f"[{name}] Timed out after {tool.timeout_s}s (attempt {attempt + 1})")
                if attempt == tool.retries:
                    return self._error_state(name, f"Timed out after {tool.timeout_s}s", start, escalate=True)

            except Exception as e:
                logger.exception(f"[{name}] Error on attempt {attempt + 1}: {e}")
                if attempt == tool.retries:
                    return self._error_state(name, str(e), start, escalate=False)

                # Exponential backoff between retries
                await asyncio.sleep(2 ** attempt)

        return self._error_state(name, "Max retries exceeded", start, escalate=True)

    def _error_state(self, tool_name: str, message: str, start: float, escalate: bool) -> dict:
        """Build the partial state update that encodes a tool failure."""
        duration_ms = int((time.monotonic() - start) * 1000)
        error_entry = {
            "tool": tool_name,
            "message": message,
            "at": datetime.utcnow().isoformat() + "Z",
        }
        update: dict = {
            "errors": [error_entry],
            "step_durations": [{"step": tool_name, "duration_ms": duration_ms, "status": "error"}],
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        if escalate:
            update["requires_human_review"] = True
            update["review_reason"] = f"Tool '{tool_name}' failed: {message}"
            update["status"] = "awaiting_review"
        return update


# ── Singleton registry instance ───────────────────────────────────────────────
# Imported by tools/*.py files to self-register, and by the graph to invoke.

registry = ToolRegistry()