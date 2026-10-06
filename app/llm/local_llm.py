"""
Local LLM wrapper using TinyLlama 1.1B.

Fully offline-capable: weights are loaded from a local directory
(`MODEL_PATH`, default `models/tinyllama-1.1b-chat` — see
`scripts/download_model.py`). No API keys, tokens, or Hub login are
used or required. If the local directory is missing, it falls back to
the Hub ID (one-time network fetch, still token-free for this public repo).

An optional QLoRA adapter (`MODEL_ADAPTER_PATH`, e.g.
`models/shopwave-lora` — see `training/`) is layered on top when present.

The model lazy-loads on first `chat()` call so imports stay cheap.
Thread-safe for concurrent run_in_executor calls. Deterministic
greedy decoding by default.
"""

import os
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HUB_MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "tinyllama-1.1b-chat"
MAX_INPUT_TOKENS = 1024


def _model_path() -> str:
    local = Path(os.environ.get("MODEL_PATH", str(DEFAULT_MODEL_PATH)))
    if local.is_dir() and any(local.iterdir()):
        return str(local)
    return HUB_MODEL_ID


def _adapter_path() -> str | None:
    p = os.environ.get("MODEL_ADAPTER_PATH", str(REPO_ROOT / "models" / "shopwave-lora"))
    return p if Path(p).is_dir() and any(Path(p).iterdir()) else None


_tokenizer = None
_model = None
_load_lock = threading.Lock()
_generate_lock = threading.Lock()


def _get_model():
    """Load tokenizer + model on first use (double-checked locking)."""
    global _tokenizer, _model
    if _model is not None:
        return _tokenizer, _model
    with _load_lock:
        if _model is not None:
            return _tokenizer, _model
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, GenerationConfig

        src = _model_path()
        print(f"[LLM] Loading {src}...")
        _tokenizer = AutoTokenizer.from_pretrained(src, local_files_only=Path(src).is_dir())
        try:
            _model = AutoModelForCausalLM.from_pretrained(
                src,
                dtype=torch.float16,
                device_map="auto",
                local_files_only=Path(src).is_dir(),
            )
        except ValueError:
            # accelerate not installed -> plain CPU load
            _model = AutoModelForCausalLM.from_pretrained(
                src,
                dtype=torch.float16,
                local_files_only=Path(src).is_dir(),
            )
        adapter = _adapter_path()
        if adapter is not None:
            from peft import PeftModel

            print(f"[LLM] Applying adapter {adapter}...")
            _model = PeftModel.from_pretrained(_model, adapter)
        _model.generation_config = GenerationConfig.from_pretrained(
            src, local_files_only=Path(src).is_dir()
        )
        _model.generation_config.max_length = None
        print("[LLM] Model loaded.")
        return _tokenizer, _model


def is_loaded() -> bool:
    return _model is not None


def chat(system_prompt: str, user_message: str, max_new_tokens: int = 400) -> str:
    import torch

    tokenizer, model = _get_model()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=MAX_INPUT_TOKENS)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    with _generate_lock:
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,  # greedy = deterministic
                pad_token_id=tokenizer.eos_token_id,
            )
    new_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
