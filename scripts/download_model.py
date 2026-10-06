"""
One-time model vendoring: downloads TinyLlama-1.1B-Chat weights into
`models/tinyllama-1.1b-chat/` so the project runs fully offline afterwards.

The repo is public — no token, login, or API key needed.

Usage:
    myenv/bin/python scripts/download_model.py
"""

import os
from pathlib import Path

REPO_ID = os.environ.get("BASE_MODEL_ID", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
TARGET = Path(__file__).parent.parent / "models" / "tinyllama-1.1b-chat"


def main() -> None:
    from huggingface_hub import snapshot_download

    TARGET.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(TARGET),
        # weight + tokenizer/config files only; skip redundant variants
        allow_patterns=["*.json", "*.model", "*.safetensors", "*.txt", "*.py"],
    )
    size_gb = sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) / 1e9
    print(f"Model ready at {path} ({size_gb:.2f} GB)")


if __name__ == "__main__":
    main()
