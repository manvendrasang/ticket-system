"""Pytest bootstrap: isolated temp SQLite DB for the whole session."""

import os
import tempfile

_fd, _path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_PATH"] = _path
os.environ["SESSION_IDLE_TIMEOUT_SECONDS"] = "3600"
