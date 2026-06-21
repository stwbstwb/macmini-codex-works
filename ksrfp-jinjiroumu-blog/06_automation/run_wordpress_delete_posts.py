#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, LOGS_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    basic_auth_token,
    fetch_wordpress_post,
    read_wordpress_credentials,
)
from ksrfp_jinjiroumu_blog.io_utils import read_json  # noqa: E402


def delete_post(api_base: str, username: str, application_password: str, post_id: int) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    request = Request(
        f"{api_base}/posts/{post_id}?{urlencode({'force': 'true'})}",
        headers={"Authorization": f"Basic {token}"},
        method="DELETE",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_summary(post: dict[str, Any] | None) -> dict[str, Any] | None:
    if not post:
        return None
    title = post.get("title") if isinstance(post.get("title"), dict) else {}
    return {
        "id": post.get("id"),
        "status": post.get("status"),
        "date": post.get("date"),
        "link": post.get("link"),
        "title": title.get("raw") or title.get("rendered") or "",
    }


def render_delete_result(payload: dict[str, Any]) -> str:
    lines = [
        "# WordPress下書き削除結果",
        "",
        f"- 実行日時: {payload.get('finished_at')}",
        f"- ステータス: {payload.get('status')}",
        "",
        "## 対象投稿",
        "",
    ]
    for item in payload.get("items", []):
        before = item.get("before") or {}
        lines.extend(
            [
                f"### 投稿ID {item.get('post_id')}",
                f"- 削除結果: {item.get('status')}",
                f"- 削除前ステータス: {before.get('status') or '取得不可'}",
                f"- タイトル: {before.get('title') or '取得不可'}",
                f"- URL: {before.get('link') or '取得不可'}",
                "",
            ]
        )
        if item.get("error"):
            lines.extend([f"- エラー: {item.get('error')}", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    WORDPRESS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "wordpress_delete_latest.json", payload)
    write_json(LOGS_DIR / f"wordpress-delete-{timestamp}.json", payload)
    write_json(WORDPRESS_DIR / "wordpress_delete_result_latest.json", payload)
    write_markdown(WORDPRESS_DIR / "wordpress_delete_result_latest.md", render_delete_result(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete selected WordPress posts via REST API.")
    parser.add_argument("--post-ids", nargs="+", type=int, required=True, help="WordPress post IDs to delete.")
    parser.add_argument("--force", action="store_true", help="Required acknowledgement for permanent deletion.")
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": started_at,
        "finished_at": None,
        "post_ids": args.post_ids,
        "items": [],
    }

    try:
        if not args.force:
            raise RuntimeError("Permanent deletion requires --force.")
        if os.environ.get("KSRFP_ALLOW_WORDPRESS_WRITE") != "1":
            raise RuntimeError("Write guard is active. Set KSRFP_ALLOW_WORDPRESS_WRITE=1 to execute.")

        settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
        api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")

        for post_id in args.post_ids:
            item: dict[str, Any] = {"post_id": post_id, "status": "not_started", "before": None}
            try:
                before = fetch_wordpress_post(
                    api_base,
                    str(credentials["username"]),
                    str(credentials["application_password"]),
                    post_id,
                )
                item["before"] = post_summary(before)
            except HTTPError as exc:
                if exc.code == 404:
                    item["status"] = "already_missing"
                    payload["items"].append(item)
                    continue
                raise

            result = delete_post(
                api_base,
                str(credentials["username"]),
                str(credentials["application_password"]),
                post_id,
            )
            item["status"] = "deleted" if result.get("deleted") else "delete_response_received"
            item["delete_response"] = {
                "deleted": result.get("deleted"),
                "previous": post_summary(result.get("previous") if isinstance(result.get("previous"), dict) else None),
            }
            payload["items"].append(item)

        statuses = {str(item.get("status")) for item in payload["items"]}
        payload["status"] = "ok" if statuses <= {"deleted", "already_missing"} else "partial"
        return_code = 0 if payload["status"] == "ok" else 1
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()
        return_code = 1
    finally:
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_logs(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
