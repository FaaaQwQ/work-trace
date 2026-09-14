"""Shared Work trace paths and capture switch for the Python components."""
import json
import os
from pathlib import Path


def root_dir():
    value = os.environ.get("WORKTRACE_HOME")
    if not value:
        return None
    root = Path(value)
    profile = os.environ.get("AW_PROFILE")
    return root / "profiles" / profile if profile else root


def capture_state():
    root = root_dir()
    if root is None:
        return {"paused": False, "generation": ""}
    try:
        return json.loads((root / "capture.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"paused": False, "generation": ""}


def write_capture_state(state):
    root = root_dir()
    if root:
        root.mkdir(parents=True, exist_ok=True)
        temp = root / "capture.json.tmp"
        temp.write_text(json.dumps(state), encoding="utf-8")
        temp.replace(root / "capture.json")
