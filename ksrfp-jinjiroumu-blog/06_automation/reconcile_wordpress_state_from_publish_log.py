#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.artifact_fingerprint import (  # noqa: E402
    manifest_fingerprint,
    payload_matches_current_manifest,
)
from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.state_manager import record_wordpress_scheduled_post  # noqa: E402


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def is_current(path: Path, reference: Path, slack_seconds: int = 120) -> bool:
    if not path.exists() or not reference.exists():
        return False
    payload = read_json(path, {}) or {}
    return path.stat().st_mtime + slack_seconds >= reference.stat().st_mtime and payload_matches_current_manifest(payload)


def reconcile() -> dict[str, Any]:
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    publish_path = LOGS_DIR / "wordpress_publish_latest.json"
    publish = read_json(publish_path, {}) or {}
    publish_result = publish.get("result", {}) if isinstance(publish.get("result"), dict) else {}
    items = publish_result.get("items", []) if isinstance(publish_result.get("items"), list) else []
    payload: dict[str, Any] = {
        "status": "not_started",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "publish_log": rel(publish_path),
        "publish_log_current": is_current(publish_path, manifest_path),
        "items": [],
    }
    if not payload["publish_log_current"]:
        payload["status"] = "stale_publish_log"
        payload["reason"] = "WordPress保存ログが現在の投稿ペイロードより古いため、状態補修には使いません。"
        return payload
    if publish.get("status") not in {"created", "already_created"}:
        payload["status"] = "publish_not_successful"
        payload["reason"] = "WordPress保存ログが成功ステータスではありません。"
        payload["publish_status"] = publish.get("status")
        return payload
    for item in items:
        if not isinstance(item, dict):
            continue
        payload_path = PROJECT_ROOT / str(item.get("payload_path") or "")
        post_payload = read_json(payload_path, {}) or {}
        result = item.get("result", {}) if isinstance(item.get("result"), dict) else {}
        post = result.get("post", {}) if isinstance(result.get("post"), dict) else {}
        if not post_payload or not post.get("id"):
            payload["items"].append(
                {
                    "item_index": item.get("item_index"),
                    "status": "skipped",
                    "payload_path": rel(payload_path),
                    "reason": "payload or post id is missing",
                }
            )
            continue
        state_record = record_wordpress_scheduled_post(post_payload, result)
        payload["items"].append(
            {
                "item_index": item.get("item_index"),
                "status": "recorded",
                "payload_path": rel(payload_path),
                "wordpress_post_id": post.get("id"),
                "state_record": state_record,
            }
        )
    payload["status"] = "ok" if payload["items"] and all(item.get("status") == "recorded" for item in payload["items"]) else "partial"
    return payload


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# WordPress状態履歴補修",
        "",
        f"- ステータス: {payload.get('status')}",
        f"- 生成日時: {payload.get('generated_at')}",
        f"- WordPress保存ログ: {payload.get('publish_log')}",
        f"- 保存ログ最新性: {payload.get('publish_log_current')}",
        "",
    ]
    for item in payload.get("items", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('item_index')}件目: {item.get('status')} / post_id={item.get('wordpress_post_id') or 'なし'}")
    if payload.get("reason"):
        lines.extend(["", f"理由: {payload.get('reason')}"])
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "wordpress_state_reconcile_latest.json", payload)
    write_json(LOGS_DIR / f"wordpress-state-reconcile-{timestamp}.json", payload)
    write_markdown(LOGS_DIR / "wordpress_state_reconcile_latest.md", render_report(payload))


def main() -> int:
    payload = reconcile()
    write_logs(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
