# ShopWave Autonomous Support Resolution Agent

> Processes customer support tickets end-to-end using Claude + async Python.  
> Each ticket gets classified, resolved via multi-step tool chains, validated, and logged — automatically.

---

## Architecture

```
Ticket Ingestion → Classifier → Agent Loop → Tool Layer → Validator → Reply/Escalate
                                    ↑              ↓
                              AgentState       Audit Logger
```

| Layer | File | Responsibility |
|-------|------|----------------|
| Ingestion | `app/ingestion/loader.py` | Load + validate tickets from JSON |
| Classifier | `app/agents/classifier.py` | Claude triage: category, urgency, confidence |
| Resolver | `app/agents/resolver.py` | Agentic loop: tool selection + execution |
| Read Tools | `app/tools/read_tools.py` | get_customer, get_order, get_product, search_kb |
| Write Tools | `app/tools/write_tools.py` | check_eligibility, issue_refund, send_reply, escalate |
| Guardrails | `app/tools/write_tools.py` | Policy enforcement before every write |
| Audit Log | `app/logging/audit.py` | Full JSON audit trail per ticket |
| Dashboard | `dashboard/app.py` | FastAPI real-time log viewer |

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Native async, `asyncio.TaskGroup` structured concurrency |
| AI | Anthropic Claude (claude-sonnet-4-20250514) | Best tool-use accuracy + structured outputs |
| Schemas | Pydantic v2 | All tool I/O validated before agent sees it |
| Dashboard | FastAPI + plain HTML | Zero-dependency demo UI |
| Containerisation | Docker + Compose | One-command reproducibility for judges |

---

## Environment Setup

**1. Get your Anthropic API key** from https://console.anthropic.com

**2. Create your `.env` file:**
```bash
cp .env.example .env
# Edit .env and paste your ANTHROPIC_API_KEY
```

---

## Docker Quickstart (Recommended)

### First time: Install Docker on Windows
1. Download Docker Desktop from https://www.docker.com/products/docker-desktop
2. Install with "Use WSL 2" checked
3. Restart and open Docker Desktop
4. Verify: `docker --version` and `docker run hello-world`

### Run the agent
```powershell
# Clone and enter the project
git clone https://github.com/yourname/shopwave-agent
cd shopwave-agent

# Set your API key
copy .env.example .env
# (Edit .env with your key)

# Build and run all 20 tickets
docker compose up --build

# Stop when done
docker compose down

# View streaming logs
docker compose logs -f

# Rebuild after code changes
docker compose up --build --force-recreate
```

### Run with dashboard
```powershell
# Terminal 1: run the agent
docker compose up --build

# Terminal 2: start the dashboard
docker compose --profile dashboard up dashboard

# Open http://localhost:8000 in your browser
```

---

## Non-Docker Quickstart

```powershell
# Requires Python 3.11+
python --version

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set environment
copy .env.example .env
# Edit .env with your API key

# Run all 20 tickets
python -m app.main

# Run specific tickets only
python -m app.main --tickets TKT-008 TKT-018

# Override concurrency
python -m app.main --max-concurrent 3

# Run the dashboard separately
python -m uvicorn dashboard.app:app --reload --port 8000
```

---

## How It Works: End-to-End Flow

For each ticket:

1. **Classify** — Claude makes one structured call, returns `{category, urgency, resolvability, confidence}`. If `confidence < 0.6`, retries once then forces escalation.

2. **Gather Context** — Agent calls `get_customer` (always first), then `get_order`, `get_product`, and `search_knowledge_base` based on ticket content.

3. **Plan & Execute** — Claude reasons over gathered context, decides action (refund / escalate / inform / cancel), and calls write tools. `check_refund_eligibility` is always called before `issue_refund`.

4. **Validate** — All tool outputs pass through Pydantic schemas. Guardrails block: refund > $200, missing eligibility check, low confidence write attempts.

5. **Reply** — `send_reply` is always the last tool called. Message is personalised with customer first name and tier.

6. **Audit** — Full event written to `logs/audit_log.json` with timestamps, tool chain, confidence, outcome, and reasoning.

---

## Expected Output

**Terminal during run:**
```
─── ShopWave Autonomous Support Resolution Agent ───
Loaded 20 tickets from data/tickets.json
Max concurrent: 5 | Failure simulation: true

→ Starting TKT-001: I want to return my headphones
→ Starting TKT-002: Wrong item delivered
→ Starting TKT-003: Where is my order?
→ Starting TKT-004: Need refund urgently - fraud on my account
→ Starting TKT-005: Refund request - changed my mind
✓ INFORMED TKT-003 | 3 tools | 4820ms
✓ REFUND ISSUED TKT-001 | 7 tools | 6234ms
↑ ESCALATED TKT-004 | 4 tools | 5102ms
...
```

**Audit log** (`logs/audit_log.json`):
One JSON object per line, one per ticket. See Section 8 of the spec for full schema.

---

## Logs

| File | Contents |
|------|----------|
| `logs/audit_log.json` | One JSON line per ticket — full audit trail |
| `logs/dead_letter.json` | Tickets that failed completely after all retries |

---

## Running Tests

```bash
# Tool unit tests (no API key needed)
FAILURE_SIMULATION=false python -m pytest tests/test_tools.py -v

# Classifier tests (requires API key)
python -m pytest tests/test_classifier.py -v

# Resolver integration tests (requires API key — makes real calls)
python -m pytest tests/test_resolver.py -v -s
```

---

## Demo Script for Judges

**Show these in order:**

1. `docker compose up --build` — one command, everything runs
2. Watch concurrent processing in terminal logs (5 tickets simultaneously)
3. Open `logs/audit_log.json` → highlight TKT-008 (7 tool calls in sequence)
4. Show TKT-018 (tier fraud detected, escalated with fraud signal)
5. Run with `FAILURE_SIMULATION=true` → show retry events in audit log
6. Show TKT-015 (replacement request → correct escalation path)
7. Open `http://localhost:8000` → live dashboard with filters

**Pitch line:**  
*"This system processes 20 tickets in parallel, makes up to 7 tool calls per ticket, validates every output against Pydantic schemas, and never issues a refund without first checking eligibility. Every decision is logged with full reasoning, timestamps, and confidence scores."*

---

## Troubleshooting

**Docker not starting:**
- Ensure Docker Desktop is running (whale icon in taskbar)
- Run `docker system prune` if disk space is low

**API key errors:**
- Verify `.env` file exists (not `.env.example`)
- Confirm key starts with `sk-ant-`
- Check key has sufficient credits

**Rate limit errors:**
- Lower `MAX_CONCURRENT_TICKETS` in `.env` to 2 or 3

**No output in dashboard:**
- Run the agent first (`docker compose up`) to generate `logs/audit_log.json`
- Dashboard reads from the log file — no live streaming between services

---

## Hackathon Constraint Checklist

- ✅ **3+ tool calls per ticket** — complex tickets use 7 tool calls
- ✅ **Concurrent processing** — `asyncio.TaskGroup` with bounded semaphore (5 concurrent)
- ✅ **Graceful failure recovery** — timeout retry with exponential backoff, dead letter queue
- ✅ **Explainability** — full audit log with reasoning, confidence, tool chain, timestamps
- ✅ **Business guardrails** — eligibility-before-refund, $200 cap, tier verification
- ✅ **Escalation path** — warranty/replacement/fraud/large-refund all properly escalated
- ✅ **Docker** — one-command build and run
- ✅ **Failure simulation** — 8% timeout rate, 5% malformed response, policy violation detection
