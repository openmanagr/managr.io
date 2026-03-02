"""
Tool stubs — minimal implementations that let the graph run end-to-end.
Each stub will be replaced with a full implementation in its own module.

Order we'll build them:
1. fetch_financials  → ERP / Apideck connector (next module)
2. run_ias29         → IAS 29 inflation engine (Module 3)
3. compile_statements → Statement builder (Module 4)
4. reconcile         → Reconciliation engine (Module 5)
5. analyse_variances → Variance calculator (Module 6)
6. generate_report   → Excel + PDF builder (Module 7)
7. deliver           → SendGrid delivery (Module 8)
"""

import logging
from datetime import datetime
from app.agent.state import AgentState
from app.agent.registry import registry, Tool

logger = logging.getLogger(__name__)


# ── Stub factory ──────────────────────────────────────────────────────────────

def _stub(tool_name: str, next_step: str, output_key: str, output_value):
    """Creates a stub tool function that logs and returns a minimal state update."""
    async def _fn(state: AgentState) -> dict:
        logger.info(f"[STUB:{tool_name}] Placeholder — replace with real implementation")
        return {
            output_key: output_value,
            "current_step": next_step,
        }
    _fn.__name__ = tool_name
    return _fn


# ── Fetch Financials stub ─────────────────────────────────────────────────────

async def fetch_financials_stub(state: AgentState) -> dict:
    """Returns a minimal trial balance structure for development."""
    logger.info(f"[STUB:fetch_financials] Returning mock trial balance")
    return {
        "trial_balance": {
            "period_end": state["period_end_date"],
            "currency": state["company_currency"],
            "accounts": [
                {"code": "4000", "name": "Revenue",          "debit": "0",       "credit": "150000", "balance": "150000"},
                {"code": "5000", "name": "Cost of Sales",    "debit": "90000",   "credit": "0",      "balance": "-90000"},
                {"code": "6000", "name": "Salaries",         "debit": "25000",   "credit": "0",      "balance": "-25000"},
                {"code": "6100", "name": "Rent",             "debit": "5000",    "credit": "0",      "balance": "-5000"},
                {"code": "6200", "name": "Utilities",        "debit": "2000",    "credit": "0",      "balance": "-2000"},
                {"code": "1000", "name": "Cash",             "debit": "40000",   "credit": "0",      "balance": "40000"},
                {"code": "1100", "name": "Accounts Rec.",    "debit": "35000",   "credit": "0",      "balance": "35000"},
                {"code": "1200", "name": "Inventory",        "debit": "25000",   "credit": "0",      "balance": "25000"},
                {"code": "2000", "name": "Accounts Pay.",    "debit": "0",       "credit": "15000",  "balance": "-15000"},
                {"code": "3000", "name": "Share Capital",    "debit": "0",       "credit": "65000",  "balance": "-65000"},
                {"code": "3100", "name": "Retained Earnings","debit": "0",       "credit": "28000",  "balance": "-28000"},
            ],
            "source_system": state["erp_system"],
            "pulled_at": datetime.utcnow().isoformat() + "Z",
        },
        "current_step": "fetch_financials",
    }


# ── IAS 29 stub ───────────────────────────────────────────────────────────────

async def run_ias29_stub(state: AgentState) -> dict:
    logger.info("[STUB:run_ias29] Returning mock IAS 29 adjustment")
    return {
        "ias29_adjustment": {
            "indexation_factor": "2.847",
            "cpi_base": "285.4",
            "cpi_end": "812.6",
            "restated_accounts": [],   # Full implementation in Module 3
            "net_monetary_gain_loss": "12500",
            "applied_at": datetime.utcnow().isoformat() + "Z",
        },
        "current_step": "run_ias29",
    }


# ── Compile Statements stub ───────────────────────────────────────────────────

async def compile_statements_stub(state: AgentState) -> dict:
    logger.info("[STUB:compile_statements] Compiling from mock trial balance")
    tb = state.get("trial_balance", {})
    accounts = {a["code"]: float(a["balance"]) for a in tb.get("accounts", [])}

    revenue = accounts.get("4000", 0)
    cogs    = abs(accounts.get("5000", 0))
    gross   = revenue - cogs
    opex    = abs(accounts.get("6000", 0)) + abs(accounts.get("6100", 0)) + abs(accounts.get("6200", 0))
    ebit    = gross - opex
    net     = ebit   # Simplified — no tax/interest in stub

    return {
        "financial_statements": {
            "income_statement": {
                "revenue": str(revenue),
                "cogs": str(cogs),
                "gross_profit": str(gross),
                "gross_margin_pct": f"{(gross/revenue*100):.1f}" if revenue else "0",
                "opex": str(opex),
                "ebit": str(ebit),
                "net_income": str(net),
            },
            "balance_sheet": {
                "assets": {
                    "cash": str(abs(accounts.get("1000", 0))),
                    "accounts_receivable": str(abs(accounts.get("1100", 0))),
                    "inventory": str(abs(accounts.get("1200", 0))),
                    "total": str(sum(abs(accounts.get(k, 0)) for k in ["1000","1100","1200"])),
                },
                "liabilities": {
                    "accounts_payable": str(abs(accounts.get("2000", 0))),
                    "total": str(abs(accounts.get("2000", 0))),
                },
                "equity": {
                    "share_capital": str(abs(accounts.get("3000", 0))),
                    "retained_earnings": str(abs(accounts.get("3100", 0))),
                    "total": str(abs(accounts.get("3000", 0)) + abs(accounts.get("3100", 0))),
                },
            },
            "cash_flow": {
                "operating": str(net + 5000),   # Simplified
                "investing": "0",
                "financing": "0",
                "net": str(net + 5000),
            },
            "comparative_period": None,
            "currency": state.get("company_currency", "USD"),
            "basis": "inflation_adjusted" if state.get("ias29_adjustment") else "historical_cost",
        },
        "current_step": "compile_statements",
    }


# ── Reconcile stub ────────────────────────────────────────────────────────────

async def reconcile_stub(state: AgentState) -> dict:
    logger.info("[STUB:reconcile] Running basic debit/credit check")
    tb = state.get("trial_balance", {})
    accounts = tb.get("accounts", [])

    total_debits  = sum(float(a["debit"])  for a in accounts)
    total_credits = sum(float(a["credit"]) for a in accounts)
    balanced = abs(total_debits - total_credits) < 0.01

    return {
        "reconciliation": {
            "items_checked": len(accounts),
            "discrepancies": [] if balanced else [
                {"account": "Trial Balance", "expected": str(total_credits), "actual": str(total_debits), "diff": str(total_debits - total_credits), "note": "Debits ≠ Credits"}
            ],
            "unreconciled_count": 0 if balanced else 1,
            "passed": balanced,
        },
        "current_step": "reconcile",
        **({"requires_human_review": True, "review_reason": "Trial balance does not balance"} if not balanced else {}),
    }


# ── Analyse Variances stub ────────────────────────────────────────────────────

async def analyse_variances_stub(state: AgentState) -> dict:
    logger.info("[STUB:analyse_variances] Returning mock variances")
    # Real implementation will compare to prior period from DB
    return {
        "variances": [
            {"account": "Revenue",      "current": "150000", "prior": "128000", "variance_abs": "22000", "variance_pct": "17.2", "flag": "warn",  "commentary": None},
            {"account": "Cost of Sales","current": "90000",  "prior": "71680",  "variance_abs": "18320", "variance_pct": "25.6", "flag": "alert", "commentary": None},
            {"account": "Gross Margin", "current": "40.0",   "prior": "44.0",   "variance_abs": "-4.0",  "variance_pct": "-9.1", "flag": "warn",  "commentary": None},
            {"account": "Salaries",     "current": "25000",  "prior": "24000",  "variance_abs": "1000",  "variance_pct": "4.2",  "flag": "ok",    "commentary": None},
        ],
        "current_step": "analyse_variances",
    }


# ── Generate Report stub ──────────────────────────────────────────────────────

async def generate_report_stub(state: AgentState) -> dict:
    logger.info("[STUB:generate_report] Skipping file generation in stub mode")
    existing_report = state.get("report") or {}
    return {
        "report": {
            **existing_report,
            "excel_s3_url": "https://stub-s3/report.xlsx",
            "pdf_s3_url":   "https://stub-s3/report.pdf",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "delivered_to": None,
        },
        "current_step": "generate_report",
    }


# ── Deliver stub ──────────────────────────────────────────────────────────────

async def deliver_stub(state: AgentState) -> dict:
    logger.info(f"[STUB:deliver] Would email report to accountant")
    report = state.get("report") or {}
    return {
        "report": {**report, "delivered_to": ["accountant@stub.com"]},
        "current_step": "deliver",
        "status": "complete",
    }


# ── Register all stubs ────────────────────────────────────────────────────────

_STUBS = [
    Tool(name="fetch_financials",   description="Pull trial balance from ERP via Apideck",          fn=fetch_financials_stub,  phase="p0", tags=["erp", "data"]),
    Tool(name="run_ias29",          description="Apply IAS 29 inflation restatement (ZWG entities)", fn=run_ias29_stub,         phase="p0", tags=["ias29", "zimbabwe"]),
    Tool(name="compile_statements", description="Build P&L, Balance Sheet, Cash Flow from TB",       fn=compile_statements_stub,phase="p0", tags=["statements"]),
    Tool(name="reconcile",          description="Run reconciliation checks on compiled statements",   fn=reconcile_stub,         phase="p0", tags=["reconciliation"]),
    Tool(name="analyse_variances",  description="Calculate MoM and budget variances, flag outliers", fn=analyse_variances_stub, phase="p0", tags=["variances", "analysis"]),
    Tool(name="generate_report",    description="Build Excel workbook + PDF management report",       fn=generate_report_stub,   phase="p0", tags=["report", "excel", "pdf"]),
    Tool(name="deliver",            description="Send report via SendGrid to accountant / CFO",       fn=deliver_stub,           phase="p0", tags=["email", "delivery"]),
]

for tool in _STUBS:
    registry.register(tool)