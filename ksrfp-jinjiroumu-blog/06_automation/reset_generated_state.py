#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR, STATE_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.state_manager import default_state, render_state_summary, state_paths  # noqa: E402


GENERATED_SUBDIRS = (
    "articles",
    "outlines",
    "review-texts",
    "wordpress-payloads",
    "images",
)

PRESERVED_NAMES = {".gitkeep", "README.md"}


def delete_generated_files() -> list[dict[str, Any]]:
    deleted: list[dict[str, Any]] = []
    for subdir in GENERATED_SUBDIRS:
        folder = GENERATED_DIR / subdir
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if path.name in PRESERVED_NAMES:
                continue
            if path.is_file() or path.is_symlink():
                path.unlink()
                deleted.append({"path": str(path.relative_to(PROJECT_ROOT)), "type": "file"})
    return deleted


def reset_state_files() -> dict[str, Any]:
    defaults = default_state()
    paths = state_paths()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {}
    for key in ("processed_pdfs", "topic_history", "fact_check_registry", "automation_status", "scheduled_posts"):
        state[key] = defaults[key]
        write_json(paths[key], state[key])
    write_markdown(paths["readme"], render_state_summary(state))
    return state


def render_reset_result(payload: dict[str, Any]) -> str:
    lines = [
        "# 生成物・履歴リセット結果",
        "",
        f"- 実行日時: {payload.get('finished_at')}",
        f"- ステータス: {payload.get('status')}",
        f"- 削除ファイル数: {len(payload.get('deleted_files', []))}",
        "",
        "## 初期化した状態ファイル",
        "",
    ]
    for path in payload.get("reset_state_files", []):
        lines.append(f"- {path}")
    if payload.get("deleted_files"):
        lines.extend(["", "## 削除した生成ファイル", ""])
        for item in payload.get("deleted_files", []):
            lines.append(f"- {item.get('path')}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset locally generated articles and article history.")
    parser.add_argument("--confirm", action="store_true", help="Required acknowledgement for local reset.")
    args = parser.parse_args()
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "deleted_files": [],
        "reset_state_files": [],
    }
    try:
        if not args.confirm:
            raise RuntimeError("Reset requires --confirm.")
        payload["deleted_files"] = delete_generated_files()
        reset_state_files()
        payload["reset_state_files"] = [
            str(state_paths()[name].relative_to(PROJECT_ROOT))
            for name in ("processed_pdfs", "topic_history", "fact_check_registry", "automation_status", "scheduled_posts", "readme")
        ]
        payload["status"] = "ok"
        return_code = 0
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        return_code = 1
    finally:
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        write_json(LOGS_DIR / "reset_generated_state_latest.json", payload)
        write_json(LOGS_DIR / f"reset-generated-state-{timestamp}.json", payload)
        write_markdown(LOGS_DIR / "reset_generated_state_latest.md", render_reset_result(payload))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
