#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, LOGS_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    fetch_wordpress_media,
    fetch_wordpress_post,
    read_wordpress_credentials,
)


REFRESH_LOG = LOGS_DIR / "wordpress_featured_image_refresh_latest.json"


def main() -> int:
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "items": [],
        "checks": {},
    }
    try:
        settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
        api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")
        refresh = read_json(REFRESH_LOG, {}) or {}
        items = refresh.get("items", []) if isinstance(refresh.get("items"), list) else []
        if not items:
            raise RuntimeError("No featured image refresh items found.")

        verified = [
            verify_item(
                item,
                api_base,
                str(credentials["username"]),
                str(credentials["application_password"]),
            )
            for item in items
        ]
        media_ids = [item.get("actual", {}).get("featured_media") for item in verified]
        media_urls = [item.get("media_url") for item in verified]
        payload["items"] = verified
        payload["checks"] = {
            "all_posts_draft": all(item.get("checks", {}).get("status_draft") for item in verified),
            "all_featured_media_matches": all(
                item.get("checks", {}).get("featured_media_matches") for item in verified
            ),
            "all_media_supported_images": all(
                item.get("checks", {}).get("media_is_supported_image") for item in verified
            ),
            "all_alt_text_matches": all(item.get("checks", {}).get("alt_text_matches") for item in verified),
            "media_ids_unique": len(media_ids) == len(set(media_ids)),
            "media_urls_unique": len(media_urls) == len(set(media_urls)),
            "item_count": len(verified),
        }
        payload["status"] = "ok" if all(payload["checks"].values()) else "partial"
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


def verify_item(item: dict[str, Any], api_base: str, username: str, application_password: str) -> dict[str, Any]:
    post_id = int(item.get("post_id") or 0)
    item_index = int(item.get("item_index") or 0)
    expected_media_id = int(item.get("media", {}).get("id") or 0) if isinstance(item.get("media"), dict) else 0
    image_plan = read_json(PROJECT_ROOT / "03_generated" / "images" / f"featured_image_plan_item_{item_index}.json", {}) or {}
    expected_alt_text = str(image_plan.get("alt_text") or "")
    post = fetch_wordpress_post(api_base, username, application_password, post_id)
    actual_media_id = int(post.get("featured_media") or 0)
    media = fetch_wordpress_media(api_base, username, application_password, actual_media_id)
    checks = {
        "status_draft": post.get("status") == "draft",
        "featured_media_matches": actual_media_id == expected_media_id,
        "media_is_supported_image": media.get("mime_type") in {"image/png", "image/jpeg", "image/webp"},
        "alt_text_matches": not expected_alt_text or str(media.get("alt_text") or "") == expected_alt_text,
    }
    return {
        "status": "ok" if all(checks.values()) else "partial",
        "item_index": item_index,
        "post_id": post_id,
        "title": rendered_text(post.get("title")),
        "expected_media_id": expected_media_id,
        "expected_alt_text": expected_alt_text,
        "media_url": media.get("source_url"),
        "media_alt_text": media.get("alt_text"),
        "actual": {
            "status": post.get("status"),
            "date": post.get("date"),
            "featured_media": actual_media_id,
        },
        "checks": checks,
    }


def rendered_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("rendered") or value.get("raw") or "")
    return str(value or "")


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# WordPressアイキャッチ差し替え検証",
        "",
        f"- 実行日時: {payload.get('finished_at')}",
        f"- ステータス: {payload.get('status')}",
        "",
        "## 全体チェック",
        "",
    ]
    for key, value in payload.get("checks", {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    for item in payload.get("items", []):
        lines.extend(
            [
                f"## {item.get('item_index')}件目",
                "",
                f"- ステータス: {item.get('status')}",
                f"- 投稿ID: {item.get('post_id')}",
                f"- タイトル: {item.get('title')}",
                f"- 期待メディアID: {item.get('expected_media_id')}",
                f"- 実メディアID: {item.get('actual', {}).get('featured_media')}",
                f"- 画像URL: {item.get('media_url')}",
                f"- 期待alt: {item.get('expected_alt_text')}",
                f"- 実alt: {item.get('media_alt_text')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "wordpress_featured_image_refresh_verify_latest.json", payload)
    write_json(LOGS_DIR / f"wordpress-featured-image-refresh-verify-{timestamp}.json", payload)
    write_json(WORDPRESS_DIR / "wordpress_featured_image_refresh_verify_latest.json", payload)
    write_markdown(WORDPRESS_DIR / "wordpress_featured_image_refresh_verify_latest.md", render_report(payload))


if __name__ == "__main__":
    raise SystemExit(main())
