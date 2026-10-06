# Local Setup — fully offline model, no tokens or API keys

This project runs TinyLlama-1.1B-Chat vendored into `models/` plus an
optional locally fine-tuned adapter. Nothing phones home at runtime once
the weights are downloaded, and no login, token, or API key exists
anywhere in the codebase (`login.py` was removed).

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
  `grep -rni "hf_token\|api.key" app dashboard training scripts` should
  only match comments saying none are needed.

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
FAILURE_SIMULATION=false myenv/bin/python -m pytest tests/ -q   # 45 tests, ~2-4 min (uses real local model)
FAILURE_SIMULATION=false myenv/bin/python -m app.main --tickets TKT-008 TKT-018 --max-concurrent 2
myenv/bin/python -m uvicorn dashboard.app:app --port 8000        # http://localhost:8000
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ValueError: ... requires accelerate` | `myenv/bin/pip install accelerate` (now pinned in requirements) |
| LLM calls fall back to keyword results | model failed to load — read the `[LLM]` lines; check `models/` contents and VRAM (`nvidia-smi`) |
| `eval.py` accuracy low on base model | expected — base TinyLlama is weak at JSON; that is what the adapter fixes, run step 5 first |
| `eval.py --adapter` errors "does not exist" | training never ran — run step 5 first |
| Out of VRAM during training | lower `--epochs`, or edit `training/train.py`: grad accum 16, `max_seq_length` 512 |
| Slow first ticket | one-time weight load (~1 min); subsequent tickets reuse it |
