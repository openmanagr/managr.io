"""
LLM Review Tool — Claude analyses the compiled financial statements and variances.

This is where the agent's intelligence lives. Claude:
1. Reads the structured financial data from state
2. Generates section-by-section narrative commentary
3. Flags anomalies and IFRS disclosure requirements
4. Decides whether to proceed or escalate

Claude is the NLG service, insight synthesiser, reasoning engine, AND
decision classifier — all in one prompt. No separate ML services needed.

The prompt is structured as a series of tasks with clear output format
so we can parse Claude's response back into typed state updates.
"""

import json
import logging
from anthropic import AsyncAnthropic
from app.agent.state import AgentState, ReportSection
from app.agent.registry import registry, Tool
from datetime import datetime

logger = logging.getLogger(__name__)

client = AsyncAnthropic()  # Reads ANTHROPIC_API_KEY from env

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are managr, an AI accounting agent specialising in Zimbabwean businesses.

Your expertise:
- IFRS financial reporting (IAS 1, IAS 7, IAS 21, IAS 29)
- IAS 29 hyperinflationary economics — you understand the difference between 
  monetary and non-monetary items, indexation factors, and purchasing power gains/losses
- PAAB (Public Accountants and Auditors Board) Zimbabwe requirements
- ZWG/USD dual-currency reporting common in Zimbabwe
- Reading variance patterns: what's seasonal, what's a real problem, what needs disclosure

Your output style:
- Precise and professional — this goes to CFOs and auditors
- Specific numbers always: never "revenue increased" always "revenue increased 23.4% to $1.2m"
- Flag problems clearly — don't bury bad news in qualifications
- IAS 29 adjustments explained in plain English alongside the technical treatment

You always respond with valid JSON matching the exact schema requested.
Never add prose outside the JSON block."""


# ── Analysis Prompt ───────────────────────────────────────────────────────────

def build_analysis_prompt(state: AgentState) -> str:
    """
    Build the user-turn prompt with all financial context embedded.
    We pass structured data (not raw GL) so Claude can focus on analysis.
    """
    statements = state.get("financial_statements", {})
    variances = state.get("variances", [])
    reconciliation = state.get("reconciliation", {})
    ias29 = state.get("ias29_adjustment")

    period = state["reporting_period"]
    company = state["company_name"]
    currency = state["company_currency"]

    flagged_variances = [v for v in (variances or []) if v.get("flag") in ("warn", "alert")]

    prompt = f"""Analyse the following financial data for {company} — period ending {state['period_end_date']}.
Reporting currency: {currency}

## Financial Statements
{json.dumps(statements, indent=2)}

## Variance Analysis ({len(flagged_variances)} flagged items)
{json.dumps(flagged_variances, indent=2)}

## Reconciliation Results
{json.dumps(reconciliation, indent=2)}

{"## IAS 29 Inflation Adjustment" if ias29 else "## IAS 29: Not applicable (USD functional entity)"}
{json.dumps(ias29, indent=2) if ias29 else ""}

---

Respond with a JSON object matching this exact schema:

{{
  "decision": "proceed" | "re_reconcile" | "escalate",
  "decision_reason": "string — why you made this decision",
  
  "sections": [
    {{
      "title": "string",
      "narrative": "string — 2-4 sentences of professional commentary",
      "key_metrics": {{"metric_name": "value_string"}},
      "flags": ["string"] 
    }}
  ],
  
  "anomalies": [
    {{
      "account": "string",
      "description": "string",
      "severity": "info" | "warn" | "critical",
      "ifrs_reference": "string | null",
      "recommended_action": "string"
    }}
  ],
  
  "ifrs_disclosures_required": [
    {{
      "standard": "e.g. IAS 29.39",
      "requirement": "string",
      "status": "included" | "missing" | "review_required"
    }}
  ],
  
  "executive_summary": "string — 3-5 sentence paragraph for the CFO cover page"
}}

Required sections to cover:
1. Revenue & Gross Margin
2. Operating Expenses  
3. EBITDA & Net Income
4. Balance Sheet Health
5. Cash Flow
{f'6. IAS 29 Inflation Adjustment Impact' if ias29 else ''}

For the decision field:
- "proceed" if statements are clean and you have enough to write the report
- "re_reconcile" ONLY if reconciliation.passed=false and discrepancies look material
- "escalate" if there's a potential fraud indicator, going concern issue, or data integrity problem"""

    return prompt


# ── Tool Function ─────────────────────────────────────────────────────────────

async def llm_review(state: AgentState) -> dict:
    """
    The core Claude analysis node.
    Calls the Anthropic API with the full financial context,
    parses the structured JSON response, and returns a state update.
    """
    logger.info(f"[llm_review] Starting analysis for {state['company_name']} {state['reporting_period']}")

    prompt = build_analysis_prompt(state)

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    raw = response.content[0].text

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        analysis = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error(f"[llm_review] Failed to parse Claude response: {e}\nRaw: {raw[:500]}")
        return {
            "errors": [{"tool": "llm_review", "message": f"JSON parse error: {e}", "at": datetime.utcnow().isoformat() + "Z"}],
            "requires_human_review": True,
            "review_reason": "LLM returned unparseable response",
        }

    # ── Map Claude's decision to a routing signal ─────────────────────────────
    decision = analysis.get("decision", "proceed")
    requires_review = decision == "escalate"
    next_step = {
        "proceed":       "generate_report",
        "re_reconcile":  "re_reconcile",
        "escalate":      "human_escalation",
    }.get(decision, "generate_report")

    # ── Build ReportSection objects from Claude's analysis ────────────────────
    sections: list[ReportSection] = []
    for s in analysis.get("sections", []):
        sections.append(ReportSection(
            title=s.get("title", ""),
            narrative=s.get("narrative", ""),
            data={
                "key_metrics": s.get("key_metrics", {}),
                "flags": s.get("flags", []),
            },
            charts=None,  # Charts added by generate_report node
        ))

    # Add executive summary as the first section
    exec_summary = analysis.get("executive_summary", "")
    if exec_summary:
        sections.insert(0, ReportSection(
            title="Executive Summary",
            narrative=exec_summary,
            data=None,
            charts=None,
        ))

    # ── Append anomalies to warnings ──────────────────────────────────────────
    anomaly_warnings = [
        {
            "node": "llm_review",
            "severity": a.get("severity", "info"),
            "account": a.get("account"),
            "message": a.get("description"),
            "ifrs_reference": a.get("ifrs_reference"),
            "recommended_action": a.get("recommended_action"),
        }
        for a in analysis.get("anomalies", [])
    ]

    logger.info(
        f"[llm_review] Decision: {decision} | "
        f"Sections: {len(sections)} | "
        f"Anomalies: {len(anomaly_warnings)} | "
        f"IFRS disclosures: {len(analysis.get('ifrs_disclosures_required', []))}"
    )

    return {
        "current_step": next_step,
        "requires_human_review": requires_review,
        "review_reason": analysis.get("decision_reason") if requires_review else None,
        "report": {
            "sections": sections,
            "excel_s3_url": None,   # Populated by generate_report node
            "pdf_s3_url": None,
            "generated_at": None,
            "delivered_to": None,
        },
        "warnings": anomaly_warnings,
        "messages": [
            {"role": "user", "content": f"LLM review completed. Decision: {decision}. Anomalies: {len(anomaly_warnings)}"}
        ],
    }


# ── Register with the Tool Registry ──────────────────────────────────────────

registry.register(Tool(
    name="llm_review",
    description=(
        "Claude analyses compiled financial statements, generates narrative commentary, "
        "flags anomalies, checks IFRS disclosure requirements, and decides whether to "
        "proceed to report generation or escalate for human review."
    ),
    fn=llm_review,
    timeout_s=120,   # LLM calls can be slow with large financial data
    retries=1,       # Retry once on timeout — don't spam the API
    phase="p0",
    tags=["llm", "analysis", "narrative", "ifrs"],
))