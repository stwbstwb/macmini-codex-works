#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import traceback
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
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, LOGS_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    fetch_wordpress_media,
    fetch_wordpress_post,
    read_arkhe_css_editor_meta,
    read_wordpress_credentials,
)


FORBIDDEN_CONTENT_PATTERNS = (
    "人事労務だより",
    "掲載されて",
    "取り上げられて",
    "柏谷横浜社労士事務所では",
    "相談を承",
    "出典PDF",
)


def text_from_rendered(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("rendered") or value.get("raw") or "")
    return str(value or "")


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def load_publish_items() -> list[dict[str, Any]]:
    publish_path = LOGS_DIR / "wordpress_publish_latest.json"
    manifest_path = PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json"
    if not publish_path.exists():
        raise RuntimeError("WordPress publish log is missing.")
    if not manifest_path.exists():
        raise RuntimeError("WordPress payload manifest is missing.")
    if publish_path.stat().st_mtime + 120 < manifest_path.stat().st_mtime:
        raise RuntimeError("WordPress publish log is stale for the current payload manifest.")
    publish = read_json(LOGS_DIR / "wordpress_publish_latest.json", {}) or {}
    if not payload_matches_current_manifest(publish):
        raise RuntimeError("WordPress publish log manifest digest does not match the current payload manifest.")
    result = publish.get("result", {}) if isinstance(publish.get("result"), dict) else {}
    items = result.get("items", []) if isinstance(result.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def load_refreshed_media_by_post() -> dict[int, int]:
    payload = read_json(LOGS_DIR / "wordpress_featured_image_refresh_latest.json", {}) or {}
    items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
    result: dict[int, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        post_id = int(item.get("post_id") or 0)
        media = item.get("media", {}) if isinstance(item.get("media"), dict) else {}
        media_id = int(media.get("id") or 0)
        if post_id and media_id:
            result[post_id] = media_id
    return result


def verify_item(
    item: dict[str, Any],
    api_base: str,
    settings: dict[str, Any],
    username: str,
    application_password: str,
    refreshed_media_by_post: dict[int, int],
) -> dict[str, Any]:
    result = item.get("result", {}) if isinstance(item.get("result"), dict) else {}
    post_result = result.get("post", {}) if isinstance(result.get("post"), dict) else {}
    media_result = result.get("media", {}) if isinstance(result.get("media"), dict) else {}
    post_id = int(post_result.get("id") or 0)
    media_id = int(refreshed_media_by_post.get(post_id) or media_result.get("id") or 0)
    payload_path = PROJECT_ROOT / str(item.get("payload_path") or "")
    payload = read_json(payload_path, {}) or {}
    wordpress = payload.get("wordpress", {}) if isinstance(payload.get("wordpress"), dict) else {}

    post = fetch_wordpress_post(api_base, username, application_password, post_id)
    media = fetch_wordpress_media(api_base, username, application_password, int(post.get("featured_media") or media_id))
    arkhe = read_arkhe_css_editor_meta(settings, username, application_password, post_id)

    rendered_content = text_from_rendered(post.get("content"))
    plain_content = strip_html(rendered_content)
    h1_count = len(re.findall(r"<h1\b", rendered_content, flags=re.IGNORECASE))
    forbidden_found = [pattern for pattern in FORBIDDEN_CONTENT_PATTERNS if pattern in plain_content]
    checks = {
        "status_draft": post.get("status") == "draft",
        "date_matches": str(post.get("date") or "") == str(wordpress.get("date") or "")[:19],
        "author_matches": int(post.get("author") or 0) == int(wordpress.get("author") or 0),
        "categories_match": sorted(post.get("categories") or []) == sorted(wordpress.get("categories") or []),
        "tags_empty": not post.get("tags"),
        "slug_empty": not str(post.get("slug") or ""),
        "featured_media_matches": int(post.get("featured_media") or 0) == media_id,
        "media_is_supported_image": media.get("mime_type") in {"image/png", "image/jpeg", "image/webp"},
        "h1_duplicate_absent": h1_count == 0,
        "content_has_h2": "<h2" in rendered_content,
        "content_has_h3": "<h3" in rendered_content,
        "arkhe_css_saved": bool(arkhe.get("matches_expected")),
        "forbidden_content_absent": not forbidden_found,
    }
    title = text_from_rendered(post.get("title"))
    return {
        "item_index": item.get("item_index"),
        "status": "ok" if all(checks.values()) else "partial",
        "post_id": post_id,
        "title": title,
        "post_url": post.get("link"),
        "media_id": media_id,
        "media_url": media.get("source_url"),
        "expected": {
            "date": wordpress.get("date"),
            "author": wordpress.get("author"),
            "categories": wordpress.get("categories"),
            "tags": wordpress.get("tags"),
        },
        "actual": {
            "status": post.get("status"),
            "date": post.get("date"),
            "author": post.get("author"),
            "categories": post.get("categories"),
            "tags": post.get("tags"),
            "featured_media": post.get("featured_media"),
            "slug": post.get("slug"),
            "h1_count": h1_count,
        },
        "checks": checks,
        "forbidden_found": forbidden_found,
        "arkhe_css_editor": arkhe,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# WordPress下書き一括検証",
        "",
        f"- 実行日時: {payload.get('finished_at')}",
        f"- ステータス: {payload.get('status')}",
        f"- 検証件数: {len(payload.get('items', []))}",
        "",
    ]
    for item in payload.get("items", []):
        lines.extend(
            [
                f"## {item.get('item_index')}件目",
                "",
                f"- ステータス: {item.get('status')}",
                f"- 投稿ID: {item.get('post_id')}",
                f"- タイトル: {item.get('title')}",
                f"- URL: {item.get('post_url')}",
                f"- アイキャッチ: {item.get('media_url')}",
                "",
                "### チェック",
                "",
            ]
        )
        for key, value in item.get("checks", {}).items():
            lines.append(f"- {key}: {value}")
        if item.get("forbidden_found"):
            lines.extend(["", f"- 禁止表現: {', '.join(item.get('forbidden_found', []))}"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    WORDPRESS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "wordpress_batch_verify_latest.json", payload)
    write_json(LOGS_DIR / f"wordpress-batch-verify-{timestamp}.json", payload)
    write_json(WORDPRESS_DIR / "wordpress_batch_verification_latest.json", payload)
    write_markdown(WORDPRESS_DIR / "wordpress_batch_verification_latest.md", render_report(payload))


def main() -> int:
    started_at = datetime.now().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": started_at,
        "finished_at": None,
        **manifest_fingerprint(),
        "items": [],
    }
    try:
        settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
        api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")
        items = load_publish_items()
        refreshed_media_by_post = load_refreshed_media_by_post()
        if not items:
            raise RuntimeError("No WordPress publish items found.")
        try:
            expected_count = max(1, int(settings.get("articles_per_run") or 3))
        except (TypeError, ValueError):
            expected_count = 3
        if len(items) != expected_count:
            raise RuntimeError(f"WordPress publish item count mismatch: expected {expected_count}, got {len(items)}.")
        payload["items"] = [
            verify_item(
                item,
                api_base,
                settings,
                str(credentials["username"]),
                str(credentials["application_password"]),
                refreshed_media_by_post,
            )
            for item in items
        ]
        payload["status"] = "ok" if all(item.get("status") == "ok" for item in payload["items"]) else "partial"
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
