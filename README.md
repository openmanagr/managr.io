# OpenManagr 🤖📊

**Open-source AI accounting agent for Management **

managr automates the monthly financial close — pulling data from your ERP, applying IAS 29 inflation adjustments, reconciling the trial balance, and generating a management report with Claude-written commentary. Delivered to your accountant's inbox by the 5th of every month.

Built for Zimbabwean businesses navigating ZWG/USD dual-currency reporting and IFRS under hyperinflationary conditions.

---

## What it does

| Step          | What happens                                                                    |
| ------------- | ------------------------------------------------------------------------------- |
| **Pull**      | Connects to Sage, Xero, or QuickBooks via Apideck and fetches the trial balance |
| **Adjust**    | Applies IAS 29 restatement using ZIMSTAT CPI data and RBZ official rates        |
| **Compile**   | Builds P&L, Balance Sheet, and Cash Flow from the adjusted trial balance        |
| **Reconcile** | Checks debits = credits, balance sheet equation, and bank-to-GL balances        |
| **Analyse**   | Calculates month-on-month variances and flags outliers (>10% warn, >20% alert)  |
| **Review**    | Claude reads the numbers, writes narrative commentary, checks IFRS disclosures  |
| **Report**    | Generates a formatted Excel workbook + PDF management report                    |
| **Deliver**   | Sends to the accountant via SendGrid for review before the CFO sees it          |

If anything looks wrong — trial balance doesn't balance, a variance is unexplainable, potential fraud indicator — the agent stops and sends a human escalation alert instead of generating a report with bad numbers.

---

## Architecture

```
FastAPI  ──►  LangGraph StateGraph  ──►  Tool Registry
                     │
         ┌───────────┼───────────────┐
         ▼           ▼               ▼
   fetch_financials  run_ias29   llm_review (Claude)
   compile_stmts     reconcile   generate_report
   analyse_variances             deliver
```

- **Orchestrator**: LangGraph `StateGraph` — stateful, resumable, auditable
- **LLM**: Claude (Anthropic) — handles NLG, anomaly commentary, IFRS checks, routing decisions
- **Memory**: `AgentState` TypedDict flows through every node; Redis for session state (P1)
- **Database**: PostgreSQL + pgvector + TimescaleDB extensions (single DB, no Mongo/Cassandra)
- **Tools**: Self-registering pattern — add new connectors without touching the graph

Full architecture analysis: see `managr-architecture.jsx`

---

## Project structure

```
managr.io/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + run endpoints
│   │   ├── agent/
│   │   │   ├── state.py             # AgentState TypedDict — shared data contract
│   │   │   ├── registry.py          # Tool registry — routing, retries, timeouts
│   │   │   ├── graph.py             # LangGraph StateGraph — the orchestrator
│   │   │   └── nodes.py             # Graph nodes — thin wrappers over registry
│   │   └── tools/
│   │       ├── llm_review.py        # Claude analysis — narrative, anomalies, IFRS
│   │       └── stubs.py             # Mock implementations (replace module by module)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                        # Next.js dashboard (scaffold — coming in Phase 1)
├── docker-compose.yml
└── .env.example
```

---

## Quick start

### Prerequisites

- Python 3.11+
- An Anthropic API key — [get one here](https://console.anthropic.com)
- Docker + Docker Compose (optional but recommended)

### Run locally

```bash
# 1. Clone
git clone https://github.com/yourusername/managr.io.git
cd managr.io

# 2. Environment
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY

# 3. Install
cd backend
pip install -r requirements.txt

# 4. Start
uvicorn app.main:app --reload

# 5. Verify
curl http://localhost:8000/health
# → {"status":"healthy","tools_registered":8}
```

### Run with Docker

```bash
docker-compose up -d
```

### Trigger a run

```bash
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "acme-001",
    "company_name": "Acme Zimbabwe (Pvt) Ltd",
    "company_currency": "ZWG",
    "reporting_period": "2025-01",
    "erp_system": "xero",
    "trigger": "manual"
  }'

# Returns: {"run_id": "uuid", "status": "running", ...}

# Poll for result
curl http://localhost:8000/api/v1/runs/{run_id}
```

---

## Environment variables

```bash
# .env — copy from .env.example and fill in

# Required
ANTHROPIC_API_KEY=sk-ant-...          # Claude API key

# ERP (needed when fetch_financials stub is replaced)
APIDECK_API_KEY=...
APIDECK_APPLICATION_ID=...

# Database (needed for P1 — persistence, multi-tenant)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/managr
REDIS_URL=redis://localhost:6379/0

# Email delivery
SENDGRID_API_KEY=...
FROM_EMAIL=reports@yourdomain.com

# Zimbabwe-specific (needed for IAS 29 engine)
RBZ_API_URL=https://www.rbz.co.zw/...   # RBZ official rate feed
ZIMSTAT_CPI_URL=...                      # ZIMSTAT CPI data endpoint

# Storage (needed for report delivery)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET=managr-reports

# App
FRONTEND_URL=http://localhost:3000
SECRET_KEY=generate-a-random-string
ENVIRONMENT=development
```

---

## API reference

| Method | Endpoint                | Description                                  |
| ------ | ----------------------- | -------------------------------------------- |
| `GET`  | `/health`               | Health check — shows registered tool count   |
| `GET`  | `/api/v1/tools`         | List all registered tools and their metadata |
| `POST` | `/api/v1/runs`          | Start a new agent run                        |
| `GET`  | `/api/v1/runs/{run_id}` | Poll run status + result                     |

---

## Build roadmap

The agent runs end-to-end today using stub tools. Replace each stub with a real implementation:

### P0 — Current sprint

- [x] Agent state (`state.py`)
- [x] Tool registry (`registry.py`)
- [x] LangGraph orchestrator (`graph.py`)
- [x] Claude review node (`tools/llm_review.py`)
- [x] All stubs (graph runs end-to-end)
- [ ] `fetch_financials` — Apideck REST connector (Sage, Xero, QuickBooks)
- [ ] `run_ias29` — IAS 29 engine with ZIMSTAT CPI + RBZ rate feed
- [ ] `compile_statements` — IFRS-compliant P&L / BS / CF builder
- [ ] `reconcile` — bank-to-GL + balance sheet equation checks
- [ ] `analyse_variances` — MoM variances with prior period from DB
- [ ] `generate_report` — ExcelJS workbook + WeasyPrint PDF
- [ ] `deliver` — SendGrid with attachments

### P1 — After first live customer

- [ ] PostgreSQL models + Alembic migrations
- [ ] Redis session manager
- [ ] Auth0 / Clerk authentication + RBAC
- [ ] Multi-tenant company isolation (Row-Level Security)
- [ ] Celery scheduled jobs (3rd-of-month trigger)
- [ ] Next.js dashboard — CFO view + analytics

### P2 — After 6 months data

- [ ] Trend analysis (Prophet)
- [ ] Anomaly detection (statistical, not ML)
- [ ] ZIMSTAT CPI auto-fetch
- [ ] WhatsApp Business API delivery
- [ ] IFRS knowledge base (pgvector RAG)

---

## Zimbabwe-specific features

**IAS 29 — Hyperinflationary Economics**
Monetary items (cash, receivables, payables) are not restated. Non-monetary items (inventory, PPE, equity) are restated using the ZIMSTAT CPI index. The net monetary gain/loss is recognised in the income statement per IAS 29 §28.

**Dual-currency reporting**
Many Zimbabwean entities maintain USD functional books alongside ZWG statutory reporting. The agent handles both and flags the IAS 21 translation requirement where applicable.

**PAAB compliance**
Checks for required IFRS disclosures relevant to PAAB (Public Accountants and Auditors Board) registrants, including IAS 29 disclosure requirements and going concern indicators.

**RBZ rate feed**
Official USD/ZWG exchange rates from the Reserve Bank of Zimbabwe, used for IAS 21 retranslation of foreign currency transactions.

---

## Contributing

This is an early-stage project. If you're a Zimbabwean accountant, CFO, or developer — feedback on the IAS 29 implementation and local ERP integrations is especially welcome.

1. Fork the repo
2. Create a branch: `git checkout -b feature/ias29-engine`
3. Run tests: `pytest`
4. Open a PR

---

## License

MIT — see `LICENSE`
