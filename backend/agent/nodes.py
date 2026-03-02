"""
Graph Nodes — the functions LangGraph calls for each step in the workflow.

Each node:
1. Updates current_step in state (for routing + audit trail)
2. Delegates to the tool registry (keeps nodes thin)
3. Returns a partial state dict (LangGraph merges this with existing state)

Nodes are async because all real work (ERP calls, DB queries, LLM calls) is I/O bound.
"""

import logging
from datetime import datetime

from app.agent.state import AgentState
from app.agent.registry import registry

logger = logging.getLogger(__name__)


def _log_node(name: str, state: AgentState):
    logger.info(f"[Node:{name}] run_id={state['run_id']} company={state['company_id']} period={state['reporting_period']}")


# ── P0 Core Nodes ─────────────────────────────────────────────────────────────

async def fetch_financials_node(state: AgentState) -> dict:
    """
    Pull trial balance from the ERP via Apideck.
    The actual connector (Sage/Xero/QBO) is selected inside the tool
    based on state['erp_system'].
    """
    _log_node("fetch_financials", state)
    update = await registry.invoke("fetch_financials", state)
    update["current_step"] = "fetch_financials"
    return update


async def run_ias29_node(state: AgentState) -> dict:
    """
    Apply IAS 29 inflation restatement if company currency is ZWG.
    If currency is USD (dollarised), this node is a pass-through.
    """
    _log_node("run_ias29", state)

    # Skip IAS 29 for USD-functional entities
    if state.get("company_currency") == "USD":
        logger.info("[Node:run_ias29] Skipping — company is USD functional")
        return {
            "current_step": "run_ias29",
            "ias29_adjustment": None,
            "warnings": [{"node": "run_ias29", "message": "IAS 29 skipped — USD functional entity"}],
        }

    update = await registry.invoke("run_ias29", state)
    update["current_step"] = "run_ias29"
    return update


async def compile_statements_node(state: AgentState) -> dict:
    """
    Compile the trial balance (+ IAS 29 adjustments if applicable)
    into structured P&L, Balance Sheet, and Cash Flow statements.
    """
    _log_node("compile_statements", state)
    update = await registry.invoke("compile_statements", state)
    update["current_step"] = "compile_statements"
    return update


async def reconcile_node(state: AgentState) -> dict:
    """
    Run reconciliation checks:
    - Debits == Credits (trial balance integrity)
    - Balance sheet equation: Assets == Liabilities + Equity
    - Bank balance vs GL cash account
    - Intercompany eliminations (if applicable)
    """
    _log_node("reconcile", state)
    update = await registry.invoke("reconcile", state)
    update["current_step"] = "reconcile"
    return update


async def analyse_variances_node(state: AgentState) -> dict:
    """
    Calculate month-on-month and budget-vs-actual variances.
    Flags items >10% (warn) and >20% (alert) for LLM commentary.
    """
    _log_node("analyse_variances", state)
    update = await registry.invoke("analyse_variances", state)
    update["current_step"] = "analyse_variances"
    return update


# ── LLM Review Node ───────────────────────────────────────────────────────────

async def llm_review_node(state: AgentState) -> dict:
    """
    Claude reviews the compiled statements and variances.

    Claude's tasks in this node:
    1. Generate narrative commentary for each financial section
    2. Flag any anomalies that warrant human attention
    3. Check for IAS 29 / IFRS disclosure requirements
    4. Decide: proceed to report generation, or request re-reconciliation

    This is the 'brain' node — everything before feeds into it,
    everything after uses its output.
    """
    _log_node("llm_review", state)
    update = await registry.invoke("llm_review", state)
    update["current_step"] = update.get("current_step", "llm_review")
    return update


# ── Output Nodes ──────────────────────────────────────────────────────────────

async def generate_report_node(state: AgentState) -> dict:
    """
    Build the Excel workbook (.xlsx) and PDF management report.
    Uses the narrative from llm_review_node + charts from Plotly.
    Uploads to S3 and stores URLs in state.report.
    """
    _log_node("generate_report", state)
    update = await registry.invoke("generate_report", state)
    update["current_step"] = "generate_report"
    return update


async def deliver_node(state: AgentState) -> dict:
    """
    Send the report via SendGrid to the accountant/CFO.
    Marks the run as complete.
    """
    _log_node("deliver", state)
    update = await registry.invoke("deliver", state)
    update["current_step"] = "deliver"
    update["status"] = "complete"
    return update


# ── Control Flow Nodes ────────────────────────────────────────────────────────

async def human_escalation_node(state: AgentState) -> dict:
    """
    Called when the agent hits something it can't resolve automatically.
    Sends an alert email/notification with context and pauses the run.
    The run can be resumed once a human resolves the flagged issue.
    """
    _log_node("human_escalation", state)
    reason = state.get("review_reason", "Unspecified reason")
    logger.warning(f"[Node:human_escalation] run_id={state['run_id']} reason={reason}")

    # TODO: Send alert via SendGrid / WhatsApp Business API
    # For now, just mark the state
    return {
        "current_step": "human_escalation",
        "status": "awaiting_review",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


async def handle_failure_node(state: AgentState) -> dict:
    """
    Terminal failure handler.
    Logs the full error context and marks the run as failed.
    """
    _log_node("handle_failure", state)
    errors = state.get("errors", [])
    logger.error(f"[Node:handle_failure] run_id={state['run_id']} errors={errors}")

    return {
        "current_step": "handle_failure",
        "status": "failed",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }