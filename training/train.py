"""
QLoRA fine-tune of TinyLlama-1.1B-Chat on data/finetune/train.jsonl.

Fits a 4GB laptop GPU: 4-bit NF4 base, LoRA adapters only, batch 1 with
gradient accumulation. Result is an adapter in models/shopwave-lora/
(base weights untouched).

Install first:
    myenv/bin/pip install -r training/requirements-train.txt

Run:
    myenv/bin/python training/prepare_data.py
    myenv/bin/python training/train.py [--epochs 2]
"""

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BASE = os.environ.get("MODEL_PATH", str(REPO_ROOT / "models" / "tinyllama-1.1b-chat"))
if Path(BASE).is_dir() and not any(Path(BASE).iterdir()):
    BASE = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"  # fall back before vendoring


def main() -> None:
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        from peft import LoraConfig
        from trl import SFTTrainer, SFTConfig
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit(
            f"Missing training dependency: {e}\n"
            "Install with: myenv/bin/pip install -r training/requirements-train.txt"
        )

    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--out", default=str(REPO_ROOT / "models" / "shopwave-lora"))
    args = ap.parse_args()

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
    )
    tok = AutoTokenizer.from_pretrained(BASE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE, quantization_config=bnb, device_map="auto"
    )
    model.config.use_cache = False

    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )

    ds = load_dataset("json", data_files=str(REPO_ROOT / "data" / "finetune" / "train.jsonl"))

    def fmt(ex):
        return {"text": tok.apply_chat_template(ex["messages"], tokenize=False)}

    ds = ds.map(fmt, remove_columns=["messages"])

    sft = SFTConfig(
        output_dir=args.out,
        seed=7,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=args.lr,
        logging_steps=10,
        save_steps=200,
        max_length=1024,
        packing=False,
        dataset_text_field="text",
        report_to="none",
    )
    trainer = SFTTrainer(model=model, args=sft, train_dataset=ds["train"], peft_config=lora)
    trainer.train()
    trainer.model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"adapter saved to {args.out}")


if __name__ == "__main__":
    main()
