"""
Local LLM wrapper using TinyLlama 1.1B.
Lazy-loads the model on first use so imports stay cheap and tests
that never call the LLM do not pay the download/GPU cost.
Thread-safe for concurrent run_in_executor calls. Deterministic
greedy decoding by default.
"""

import threading

MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
MAX_INPUT_TOKENS = 1024

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

        print(f"[LLM] Loading {MODEL_ID}...")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            dtype=torch.float16,
            device_map="auto",
        )
        _model.generation_config = GenerationConfig.from_pretrained(MODEL_ID)
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
