"""
Orchestration Manager — the LangGraph StateGraph that coordinates the full
monthly close workflow.

Node sequence (happy path):
    fetch_financials → run_ias29 → compile_statements → reconcile
        → analyse_variances → llm_review → generate_report → deliver → END

Routing logic:
    - After each tool node: check for errors or escalation flags
    - If requires_human_review=True: route to human_escalation node
    - If status="failed": route to handle_failure node
    - LLM review node decides whether to proceed or request more data

The graph is compiled once at startup and reused across runs.
Each run gets its own AgentState instance — the graph itself is stateless.
"""

import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.state import AgentState
from app.agent.nodes import (
    fetch_financials_node,
    run_ias29_node,
    compile_statements_node,
    reconcile_node,
    analyse_variances_node,
    llm_review_node,
    generate_report_node,
    deliver_node,
    human_escalation_node,
    handle_failure_node,
)

logger = logging.getLogger(__name__)


# ── Routing Functions ─────────────────────────────────────────────────────────
# These are pure functions — they look at state and return the name of the
# next node. LangGraph calls these after each node execution.

def route_after_tool(state: AgentState) -> str:
    """
    Standard post-tool router.
    Used after: fetch_financials, run_ias29, compile_statements, reconcile.
    """
    if state.get("requires_human_review"):
        logger.warning(f"[Router] Escalating to human review: {state.get('review_reason')}")
        return "human_escalation"

    if state.get("status") == "failed":
        return "handle_failure"

    if state.get("errors"):
        # Errors exist but didn't trigger escalation — continue but log
        logger.warning(f"[Router] Continuing with {len(state['errors'])} non-fatal errors")

    # Advance to the next step based on current_step
    next_steps = {
        "fetch_financials":   "run_ias29",
        "run_ias29":          "compile_statements",
        "compile_statements": "reconcile",
        "reconcile":          "analyse_variances",
    }
    return next_steps.get(state.get("current_step", ""), "handle_failure")


def route_after_llm_review(state: AgentState) -> str:
    """
    After the LLM review node, Claude may decide to:
    - Proceed to report generation
    - Request re-reconciliation (if discrepancies look suspicious)
    - Escalate for human review (if anomalies are significant)
    """
    if state.get("requires_human_review"):
        return "human_escalation"

    if state.get("status") == "failed":
        return "handle_failure"

    # Claude sets current_step to indicate its decision
    llm_decision = state.get("current_step")
    if llm_decision == "re_reconcile":
        logger.info("[Router] LLM requested re-reconciliation")
        return "reconcile"

    return "generate_report"


def route_after_report(state: AgentState) -> str:
    """After report generation — either deliver or escalate."""
    if state.get("requires_human_review"):
        return "human_escalation"
    if state.get("status") == "failed":
        return "handle_failure"
    return "deliver"


# ── Graph Builder ─────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Construct and compile the orchestration graph.

    Called once at application startup. The compiled graph is stored as a
    module-level singleton and injected into API routes.
    """
    builder = StateGraph(AgentState)

    # ── Register nodes ────────────────────────────────────────────────────────
    builder.add_node("fetch_financials",   fetch_financials_node)
    builder.add_node("run_ias29",          run_ias29_node)
    builder.add_node("compile_statements", compile_statements_node)
    builder.add_node("reconcile",          reconcile_node)
    builder.add_node("analyse_variances",  analyse_variances_node)
    builder.add_node("llm_review",         llm_review_node)
    builder.add_node("generate_report",    generate_report_node)
    builder.add_node("deliver",            deliver_node)
    builder.add_node("human_escalation",   human_escalation_node)
    builder.add_node("handle_failure",     handle_failure_node)

    # ── Entry point ───────────────────────────────────────────────────────────
    builder.set_entry_point("fetch_financials")

    # ── Edges with conditional routing ───────────────────────────────────────
    builder.add_conditional_edges(
        "fetch_financials",
        route_after_tool,
        {
            "run_ias29":        "run_ias29",
            "human_escalation": "human_escalation",
            "handle_failure":   "handle_failure",
        },
    )

    builder.add_conditional_edges(
        "run_ias29",
        route_after_tool,
        {
            "compile_statements": "compile_statements",
            "human_escalation":   "human_escalation",
            "handle_failure":     "handle_failure",
        },
    )

    builder.add_conditional_edges(
        "compile_statements",
        route_after_tool,
        {
            "reconcile":        "reconcile",
            "human_escalation": "human_escalation",
            "handle_failure":   "handle_failure",
        },
    )

    builder.add_conditional_edges(
        "reconcile",
        route_after_tool,
        {
            "analyse_variances": "analyse_variances",
            "human_escalation":  "human_escalation",
            "handle_failure":    "handle_failure",
        },
    )

    # After variance analysis, always go to LLM review
    builder.add_edge("analyse_variances", "llm_review")

    builder.add_conditional_edges(
        "llm_review",
        route_after_llm_review,
        {
            "generate_report":  "generate_report",
            "reconcile":        "reconcile",        # LLM requests re-check
            "human_escalation": "human_escalation",
            "handle_failure":   "handle_failure",
        },
    )

    builder.add_conditional_edges(
        "generate_report",
        route_after_report,
        {
            "deliver":          "deliver",
            "human_escalation": "human_escalation",
            "handle_failure":   "handle_failure",
        },
    )

    # Terminal nodes
    builder.add_edge("deliver",           END)
    builder.add_edge("human_escalation",  END)
    builder.add_edge("handle_failure",    END)

    # ── Compile with in-memory checkpointer ───────────────────────────────────
    # MemorySaver lets us resume interrupted runs by run_id.
    # Swap for PostgresSaver in production.
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    logger.info("[Orchestrator] Graph compiled successfully")
    return graph


# ── Singleton ─────────────────────────────────────────────────────────────────
# Compiled once at import time. Reused for every run.

orchestrator = build_graph()