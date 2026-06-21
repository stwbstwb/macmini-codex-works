from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .paths import LOGS_DIR


class RunState:
    def __init__(self, run_key: str):
        self.run_key = run_key or datetime.now().strftime("%Y%m%d")
        self.run_dir = LOGS_DIR / "runs" / safe_run_key(self.run_key)
        self.path = self.run_dir / "state.json"
        self.data = self._load()

    def mark(self, step: str, status: str = "ok", **details: object) -> None:
        self.data.setdefault("steps", {})[step] = {
            "status": status,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            **details,
        }
        self.save()

    def step(self, step: str) -> dict[str, Any]:
        value = self.data.get("steps", {}).get(step)
        return value if isinstance(value, dict) else {}

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.path, self.data)

    def _load(self) -> dict[str, Any]:
        data = read_json(self.path, None)
        if isinstance(data, dict):
            return data
        return {
            "run_key": self.run_key,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "steps": {},
        }


def safe_run_key(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in value).strip("-")
    if 8 <= len(cleaned) <= 80:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"run-{digest}"


def latest_run_key(default: str | None = None) -> str:
    weekly = read_json(LOGS_DIR / "weekly_latest.json", {}) or {}
    if isinstance(weekly, dict):
        for key in ("run_key", "started_at"):
            value = weekly.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return default or datetime.now().strftime("%Y%m%d")
