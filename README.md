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
| Ingestion | `app/ingestion/loader.py` | Load + validate tickets from JSON |
| Classifier | `app/agents/classifier.py` | Claude triage: category, urgency, confidence |
| Resolver | `app/agents/resolver.py` | Agentic loop: tool selection + execution |
| Read Tools | `app/tools/read_tools.py` | get_customer, get_order, get_product, search_kb |
| Write Tools | `app/tools/write_tools.py` | check_eligibility, issue_refund, send_reply, escalate |
| Guardrails | `app/tools/write_tools.py` | Policy enforcement before every write |
| Audit Log | `app/logging/audit.py` | Full JSON audit trail per ticket |
| Dashboard | `dashboard/app.py` | FastAPI real-time log viewer |



# OLD METHOD FOR PROJECT RUN, STILL CAN BE USED BUT USE BELOW METHOD
<!-- # How to run
python -m venv myenv
source myenv/bin/activate
pip install -r requirements.txt
## all 20 tickets in data/tickets.json
FAILURE_SIMULATION=false myenv/bin/python -m app.main
## specific tickets, lower concurrency
FAILURE_SIMULATION=false myenv/bin/python -m app.main --tickets TKT-008 TKT-018 --max-concurrent 3
myenv/bin/python -m uvicorn dashboard.app:app --port 8000
# Tests
FAILURE_SIMULATION=false myenv/bin/python -m pytest tests/ -q -->


# NEW METHOD
## 0. Prerequisites

- Python 3.11+, ~4 GB free GPU VRAM (CPU works, slower), ~5 GB disk
- NVIDIA driver + CUDA for GPU use (checked: RTX 3050 4 GB works)

## 1. Environment

```bash
cd ticket-system
python3.11 -m venv myenv
myenv/bin/pip install -r requirements.txt
```

This installs `torch`, `transformers`, `peft`, `accelerate` (required for
`device_map="auto"`), plus the app/test stack.

## 2. Vendor the model (one-time download, token-free)

```bash
myenv/bin/python scripts/download_model.py
```

- Downloads the public `TinyLlama/TinyLlama-1.1B-Chat-v1.0` (~2.2 GB)
  into `models/tinyllama-1.1b-chat/` (gitignored, stays on your machine).
- Verify: `ls models/tinyllama-1.1b-chat/` shows `model.safetensors`,
  `tokenizer.json`, `config.json`.
- Verify no secrets exist:
  `grep -rni "hf_token\|api.key" app dashboard training scripts` → only
  comments saying none are needed.

## 3. Confirm the model loads locally

```bash
unset HF_TOKEN
myenv/bin/python -c "from app.llm.local_llm import chat; print(chat('Say OK', 'go', max_new_tokens=10))"
```

Expect `[LLM] Loading .../models/tinyllama-1.1b-chat...` then generated
text. First call is slow (weights move to GPU); later calls reuse memory.
`MODEL_PATH` in `.env` overrides the directory; if it is missing the
loader falls back to the Hub ID (network fetch, still token-free).

## 4. Build the fine-tune dataset

```bash
myenv/bin/python training/prepare_data.py --n 800 --seed 7
```

Writes `data/finetune/train.jsonl` (960 synthetic rows) and
`data/finetune/eval.jsonl` (127 rows: 10% holdout + all 20 real tickets,
never trained on). Eval covers all 11 ticket categories.

## 5. Fine-tune the adapter (QLoRA, fits 4 GB VRAM)

```bash
myenv/bin/pip install -r training/requirements-train.txt
myenv/bin/python training/train.py --epochs 2   # -> models/shopwave-lora/
```

4-bit NF4 base, LoRA r16 on attention+MLP, batch 1 × 8 accumulation.
Base weights are untouched; only the small adapter is saved.

## 6. Evaluate and serve the adapter

```bash
myenv/bin/python training/eval.py --adapter models/shopwave-lora
# exit 0 iff category accuracy >= 0.8; also checks JSON validity + replies
```

Serve it by setting in `.env`:

```
MODEL_ADAPTER_PATH=models/shopwave-lora
```

Unset/absent = base model only. No code changes needed either way.

## 7. Run the project

```bash
rm -f logs/issued_refunds.json
FAILURE_SIMULATION=false myenv/bin/python -m pytest tests/ -q   # 45 tests, ~4 min (uses real local model)
FAILURE_SIMULATION=false myenv/bin/python -m app.main --tickets TKT-008 TKT-018 --max-concurrent 2
myenv/bin/python -m uvicorn dashboard.app:app --port 8000        # http://localhost:8000
```










# Local model (no tokens or API keys anywhere)
myenv/bin/python scripts/download_model.py   # one-time: vendors weights into models/

# Fine-tune the support adapter (classification + replies)
myenv/bin/pip install -r training/requirements-train.txt
myenv/bin/python training/prepare_data.py    # builds data/finetune/{train,eval}.jsonl
myenv/bin/python training/train.py           # QLoRA -> models/shopwave-lora/
myenv/bin/python training/eval.py --adapter models/shopwave-lora
# Set MODEL_ADAPTER_PATH=models/shopwave-lora in .env to serve it