"""
Agent State — the single source of truth that flows through every node in the graph.

LangGraph passes this TypedDict between nodes. Each node reads what it needs,
writes its outputs back, and the graph decides what runs next based on it.

Design principles:
- Immutable inputs (company config, trigger) — set once at graph entry
- Accumulated outputs (financials, adjustments, report) — written by tool nodes
- Control fields (current_step, errors, requires_human_review) — drive routing
- All monetary values stored as Decimal strings to avoid float precision issues
"""

from typing import TypedDict, Optional, Annotated
from decimal import Decimal
import operator
from datetime import datetime, date


# ── Financial Data Structures ─────────────────────────────────────────────────

class TrialBalance(TypedDict):
    """Raw GL data pulled from the ERP."""
    period_end: str                    # ISO date: "2025-01-31"
    currency: str                      # "USD" | "ZWG"
    accounts: list[dict]               # [{code, name, debit, credit, balance}]
    source_system: str                 # "sage" | "xero" | "quickbooks"
    pulled_at: str                     # ISO datetime


class IAS29Adjustment(TypedDict):
    """Result of running the IAS 29 inflation restatement engine."""
    indexation_factor: str             # e.g. "2.847" — CPI end / CPI base
    cpi_base: str                      # CPI at the start of the historical period
    cpi_end: str                       # CPI at period end (from ZIMSTAT)
    restated_accounts: list[dict]      # [{code, historical_amount, restated_amount, gain_loss}]
    net_monetary_gain_loss: str        # IAS 29 §28 — monetary items gain/loss
    applied_at: str                    # ISO datetime


class FinancialStatements(TypedDict):
    """Compiled P&L, Balance Sheet, and Cash Flow — pre and post IAS 29."""
    income_statement: dict             # {revenue, cogs, gross_profit, opex, ebit, net_income}
    balance_sheet: dict                # {assets, liabilities, equity}
    cash_flow: dict                    # {operating, investing, financing, net}
    comparative_period: Optional[dict] # Same structure for prior period
    currency: str
    basis: str                         # "historical_cost" | "inflation_adjusted"


class Variance(TypedDict):
    """Month-on-month or budget-vs-actual variance for a line item."""
    account: str
    current: str
    prior: str
    variance_abs: str
    variance_pct: str
    flag: str                          # "ok" | "warn" | "alert" (>10%, >20%)
    commentary: Optional[str]          # Claude-generated explanation


class ReconciliationResult(TypedDict):
    """Output of the reconciliation tool."""
    items_checked: int
    discrepancies: list[dict]          # [{account, expected, actual, diff, note}]
    unreconciled_count: int
    passed: bool


# ── Report Structures ─────────────────────────────────────────────────────────

class ReportSection(TypedDict):
    """A single section of the management report (narrative + data)."""
    title: str
    narrative: str                     # Claude-generated prose
    data: Optional[dict]               # Supporting numbers/table
    charts: Optional[list[str]]        # S3 URLs of rendered Plotly charts


class GeneratedReport(TypedDict):
    """The final output artefact."""
    excel_s3_url: Optional[str]
    pdf_s3_url: Optional[str]
    sections: list[ReportSection]
    generated_at: str
    delivered_to: Optional[list[str]]  # Email addresses


# ── Main Agent State ──────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """
    The complete state object that flows through the LangGraph graph.

    Convention:
    - Fields ending in _at are ISO datetime strings
    - All monetary amounts are stored as strings (Decimal serialised)
    - errors uses Annotated[list, operator.add] so each node appends, not overwrites
    """

    # ── Immutable inputs (set at graph entry, never changed) ──────────────────
    run_id: str                              # UUID for this specific run
    company_id: str                          # Tenant identifier
    company_name: str
    company_currency: str                    # "USD" | "ZWG" | "ZAR"
    reporting_period: str                    # "2025-01" (YYYY-MM)
    period_end_date: str                     # "2025-01-31"
    trigger: str                             # "scheduled" | "manual" | "api"
    triggered_by: Optional[str]             # user_id if manual
    erp_system: str                          # "sage" | "xero" | "quickbooks"

    # ── Control & routing fields ──────────────────────────────────────────────
    current_step: str                        # Tracks which node is executing
    status: str                              # "running" | "awaiting_review" | "complete" | "failed"
    requires_human_review: bool              # Escalation flag — routes to review node
    review_reason: Optional[str]             # Why human review was triggered

    # ── Tool outputs (populated as each node runs) ────────────────────────────
    trial_balance: Optional[TrialBalance]
    ias29_adjustment: Optional[IAS29Adjustment]
    financial_statements: Optional[FinancialStatements]
    variances: Optional[list[Variance]]
    reconciliation: Optional[ReconciliationResult]
    report: Optional[GeneratedReport]

    # ── Claude reasoning context ──────────────────────────────────────────────
    # Accumulated messages for the LLM node — use operator.add to append
    messages: Annotated[list[dict], operator.add]

    # ── Audit & error tracking ────────────────────────────────────────────────
    # Annotated with operator.add means each node appends errors, not overwrites
    errors: Annotated[list[dict], operator.add]
    warnings: Annotated[list[dict], operator.add]
    step_durations: Annotated[list[dict], operator.add]  # [{step, duration_ms}]

    # ── Metadata ──────────────────────────────────────────────────────────────
    created_at: str
    updated_at: str


# ── State Factory ─────────────────────────────────────────────────────────────

def create_initial_state(
    run_id: str,
    company_id: str,
    company_name: str,
    company_currency: str,
    reporting_period: str,      # "2025-01"
    erp_system: str,
    trigger: str = "scheduled",
    triggered_by: Optional[str] = None,
) -> AgentState:
    """
    Build a clean initial AgentState to kick off a new graph run.
    Called by the API endpoint or the scheduler before invoking the graph.
    """
    from calendar import monthrange
    import uuid

    year, month = map(int, reporting_period.split("-"))
    last_day = monthrange(year, month)[1]
    period_end = f"{reporting_period}-{last_day:02d}"

    now = datetime.utcnow().isoformat() + "Z"

    return AgentState(
        run_id=run_id or str(uuid.uuid4()),
        company_id=company_id,
        company_name=company_name,
        company_currency=company_currency,
        reporting_period=reporting_period,
        period_end_date=period_end,
        trigger=trigger,
        triggered_by=triggered_by,
        erp_system=erp_system,

        current_step="start",
        status="running",
        requires_human_review=False,
        review_reason=None,

        trial_balance=None,
        ias29_adjustment=None,
        financial_statements=None,
        variances=None,
        reconciliation=None,
        report=None,

        messages=[],
        errors=[],
        warnings=[],
        step_durations=[],

        created_at=now,
        updated_at=now,
    )