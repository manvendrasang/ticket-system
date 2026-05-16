"""
Local LLM wrapper using TinyLlama 1.1B.
"""

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, GenerationConfig

MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

print(f"[LLM] Loading {MODEL_ID}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    dtype=torch.float16,
    device_map="auto",
)

model.generation_config = GenerationConfig.from_pretrained(MODEL_ID)
model.generation_config.max_length = None

print("[LLM] Model loaded.")


def chat(system_prompt: str, user_message: str, max_new_tokens: int = 400) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.2,
            top_p=0.9,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()