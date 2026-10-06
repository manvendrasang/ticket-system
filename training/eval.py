"""
Evaluate the adapter (or base model) on data/finetune/eval.jsonl.

Metrics:
- classification rows: JSON validity + category accuracy
- reply rows: non-empty, addresses customer by first name, no placeholders

Run:
    myenv/bin/python training/eval.py [--adapter models/shopwave-lora]

Exit code 0 only if category accuracy >= --min-acc (default 0.8).
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--min-acc", type=float, default=0.8)
    args = ap.parse_args()

    if args.adapter:
        if not Path(args.adapter).is_dir() or not any(Path(args.adapter).iterdir()):
            ap.error(f"adapter dir {args.adapter} does not exist — run training/train.py first")
        os.environ["MODEL_ADAPTER_PATH"] = args.adapter

    sys.path.insert(0, str(REPO_ROOT))
    from app.llm.local_llm import chat  # lazy load: base + optional adapter

    rows = [json.loads(l) for l in (REPO_ROOT / "data" / "finetune" / "eval.jsonl").read_text().splitlines()]
    cls_total = cls_valid = cls_correct = 0
    rep_total = rep_ok = 0
    for r in rows:
        msgs = r["messages"]
        system = next(m["content"] for m in msgs if m["role"] == "system")
        user = next(m["content"] for m in msgs if m["role"] == "user")
        expected = next(m["content"] for m in msgs if m["role"] == "assistant")
        out = chat(system, user, max_new_tokens=250)
        if "JSON object" in system:  # classification row
            cls_total += 1
            try:
                start = out.find("{")
                got = json.loads(out[start:out.rindex("}") + 1])
                cls_valid += 1
                if got.get("category") == json.loads(expected).get("category"):
                    cls_correct += 1
                else:
                    print(f"MISMATCH got={got.get('category')} want={json.loads(expected).get('category')}")
            except (ValueError, IndexError):
                print(f"INVALID JSON: {out[:120]}")
        else:  # reply row
            rep_total += 1
            name = user.splitlines()[0].split(":", 1)[1].strip()
            if out.strip() and name in out and "[" not in out and "]" not in out:
                rep_ok += 1
            else:
                print(f"WEAK REPLY: {out[:120]}")

    acc = cls_correct / max(cls_total, 1)
    print(f"classify: {cls_correct}/{cls_total} correct, {cls_valid}/{cls_total} valid JSON")
    print(f"replies: {rep_ok}/{rep_total} ok")
    print(f"accuracy={acc:.3f} (min {args.min_acc})")
    return 0 if acc >= args.min_acc else 1


if __name__ == "__main__":
    raise SystemExit(main())
