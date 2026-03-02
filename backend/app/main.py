"""
OpenManagr — Main application entry point

Startup order:
1. Load environment variables
2. Import tool stubs (self-register with the tool registry)
3. Import the LLM review tool (self-registers)
4. Build and compile the LangGraph orchestration graph
5. Start FastAPI
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import logging
import uuid
import os
from datetime import datetime

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Register tools (import triggers self-registration) ────────────────────────
import app.tools.stubs        # noqa: F401 — registers all stub tools
import app.tools.llm_review   # noqa: F401 — registers the real LLM tool (overwrites stub)

# ── Build orchestration graph ─────────────────────────────────────────────────
from app.agent.graph import orchestrator
from app.agent.state import create_initial_state
from app.agent.registry import registry

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="OpenManagr API",
    description="Open-source AI accounting agent for Zimbabwe",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ───────────────────────────────────────────────────

class RunAgentRequest(BaseModel):
    company_id: str
    company_name: str
    company_currency: str = "USD"
    reporting_period: str               # "2025-01"
    erp_system: str = "xero"
    trigger: str = "manual"


class RunAgentResponse(BaseModel):
    run_id: str
    status: str
    message: str


# ── In-memory run store (replace with Redis/DB in production) ─────────────────
_run_store: dict[str, dict] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Welcome to OpenManagr API", "version": "0.1.0", "status": "operational"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "tools_registered": len(registry.list_tools()),
    }


@app.get("/api/v1/tools")
async def list_tools():
    """List all registered tools — useful for debugging the registry."""
    return {"tools": registry.list_tools()}


@app.post("/api/v1/runs", response_model=RunAgentResponse)
async def start_run(request: RunAgentRequest, background_tasks: BackgroundTasks):
    """
    Start a new agent run for a company's monthly close.
    The graph runs in the background — poll /api/v1/runs/{run_id} for status.
    """
    run_id = str(uuid.uuid4())
    initial_state = create_initial_state(
        run_id=run_id,
        company_id=request.company_id,
        company_name=request.company_name,
        company_currency=request.company_currency,
        reporting_period=request.reporting_period,
        erp_system=request.erp_system,
        trigger=request.trigger,
    )

    _run_store[run_id] = {"status": "running", "started_at": datetime.utcnow().isoformat() + "Z"}
    background_tasks.add_task(_execute_run, run_id, initial_state)

    logger.info(f"[API] Run started: {run_id} for {request.company_name} {request.reporting_period}")
    return RunAgentResponse(
        run_id=run_id,
        status="running",
        message=f"Agent run started for {request.company_name} {request.reporting_period}",
    )


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str):
    """Poll for the status and result of an agent run."""
    if run_id not in _run_store:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _run_store[run_id]


# ── Background task ───────────────────────────────────────────────────────────

async def _execute_run(run_id: str, initial_state: dict):
    """Execute the LangGraph orchestration in the background."""
    try:
        config = {"configurable": {"thread_id": run_id}}
        final_state = await orchestrator.ainvoke(initial_state, config=config)

        _run_store[run_id] = {
            "status": final_state.get("status", "complete"),
            "run_id": run_id,
            "company": final_state.get("company_name"),
            "period": final_state.get("reporting_period"),
            "current_step": final_state.get("current_step"),
            "errors": final_state.get("errors", []),
            "warnings": final_state.get("warnings", []),
            "report": final_state.get("report"),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        }
        logger.info(f"[API] Run {run_id} completed with status: {final_state.get('status')}")

    except Exception as e:
        logger.exception(f"[API] Run {run_id} crashed: {e}")
        _run_store[run_id] = {
            "status": "failed",
            "run_id": run_id,
            "error": str(e),
            "failed_at": datetime.utcnow().isoformat() + "Z",
        }