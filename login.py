import os

from huggingface_hub import login

token = os.environ.get("HF_TOKEN")
if not token:
    raise SystemExit("Set HF_TOKEN in the environment instead of hardcoding it.")
login(token=token)
