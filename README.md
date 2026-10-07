## License

Copyright © 2026 Manvendra Sang. All rights reserved.

This repository and all of its contents are proprietary software.

No permission is granted to use, copy, modify, reproduce, distribute,
publish, sublicense, sell, or incorporate any portion of this software
into another project without prior written permission from the copyright
holder.

This restriction applies to the current version and all historical
versions, commits, releases, branches, and other versions of the
repository.(all past commits and updates and future ones as well are included)

Viewing or accessing this repository does not grant a license or any
other right to use the software.

For licensing or commercial-use inquiries, contact the copyright holder.

## Architecture

| Layer | File | Responsibility |
|-------|------|----------------|
| Intake API | `app/api.py` | Ticket intake + processing over HTTP (:8001), SQLite-backed |
| Storage | `app/db.py` | SQLite: ticket queue, audit events, refund ledger |
| Ingestion | `app/ingestion/loader.py` | Load + validate tickets from JSON |
| Classifier | `app/agents/classifier.py` | Local-LLM triage with keyword fallback: category, urgency, confidence |
| Resolver | `app/agents/resolver.py` | Fixed tool pipeline: lookup, eligibility, refund/escalate, reply |
| Read Tools | `app/tools/read_tools.py` | get_customer, get_order, get_product, search_kb |
| Write Tools | `app/tools/write_tools.py` | check_eligibility, issue_refund, send_reply, escalate |
| Guardrails | `app/tools/write_tools.py` | Eligibility-first, confidence ≥0.65, ≤$200, ≤order total, one refund per order |
| Audit Log | `app/logging/audit.py` + SQLite | JSON audit trail per ticket, dual-written |
| Dashboard | `dashboard/app.py` | FastAPI log viewer (:8000) |
| Local LLM | `app/llm/local_llm.py` | Vendored TinyLlama-1.1B + optional QLoRA adapter, no keys |

## 1. Install

```bash
cd ticket-system
python3.11 -m venv myenv
myenv/bin/pip install -r requirements.txt
cp .env.example .env
```

Needs Python 3.11+, ~5 GB disk, ~4 GB VRAM for GPU (CPU works, slower).

## 2. Install model

```bash
myenv/bin/python scripts/download_model.py
ls models/tinyllama-1.1b-chat/
```

Downloads TinyLlama-1.1B-Chat (~2.2 GB, token-free) into `models/`.
Expect `model.safetensors`, `tokenizer.json`, `config.json`.

## 3. Verify model

```bash
myenv/bin/python -c "from app.llm.local_llm import chat; print(chat('Say OK', 'go', max_new_tokens=10))"
```

Expect `[LLM] Loading .../models/tinyllama-1.1b-chat...` then text.
First call is slow; later calls reuse loaded weights.

## 4. Train adapter

```bash
myenv/bin/python training/prepare_data.py --n 800 --seed 7
myenv/bin/pip install -r training/requirements-train.txt
myenv/bin/python training/train.py --epochs 2
```

Writes `data/finetune/train.jsonl` (960 rows), `data/finetune/eval.jsonl`
(127 rows), then QLoRA-trains `models/shopwave-lora/`.

## 5. Eval adapter

```bash
myenv/bin/python training/eval.py --adapter models/shopwave-lora
```

Exit 0 means category accuracy ≥ 0.8 with valid JSON and clean replies.
Baseline: 0.929 accuracy, 99/99 valid JSON, 28/28 replies.

## 6. Serve adapter

```bash
echo 'MODEL_ADAPTER_PATH=models/shopwave-lora' >> .env
```

Unset = base model only. No code changes needed.

## 7. Test

```bash
FAILURE_SIMULATION=false myenv/bin/python -m pytest tests/ -q
```

51 tests, ~2 min. Uses the real local model.

## 8. Run

Batch (all 20 tickets):

```bash
FAILURE_SIMULATION=false myenv/bin/python -m app.main
```

Specific tickets:

```bash
FAILURE_SIMULATION=false myenv/bin/python -m app.main --tickets TKT-008 TKT-018 --max-concurrent 2
```

API + dashboard:

```bash
myenv/bin/python -m uvicorn app.api:api --port 8001 &
myenv/bin/python -m uvicorn dashboard.app:app --port 8000
```

## 9. Resolve tickets

Via API:

```bash
curl -s localhost:8001/health
curl -s -X POST localhost:8001/tickets -H 'Content-Type: application/json' -d \
  '{"ticket_id":"TKT-101","customer_email":"henry.marsh@email.com","subject":"Lamp arrived broken","body":"My lamp arrived cracked. Order ORD-1008. Full refund please.","source":"email","created_at":"2024-03-15T10:00:00Z"}'
curl -s -X POST localhost:8001/tickets/TKT-101/process
curl -s 'localhost:8001/audit/events?ticket_id=TKT-101'
```

Via dashboard: open `http://localhost:8000`, filter by outcome, tier, escalation.

Outcomes: `refund_issued`, `order_cancelled`, `declined`, `informed`,
`escalated`, `error`. Every run writes the audit event to SQLite and
`logs/audit_log.json`. TKT-008 refunds $44.99; TKT-018 escalates (tier fraud).
