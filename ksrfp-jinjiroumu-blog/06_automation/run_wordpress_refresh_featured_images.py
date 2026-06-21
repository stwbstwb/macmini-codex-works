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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.image_gate import featured_image_gate_reasons  # noqa: E402
from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR, STATE_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import read_wordpress_credentials, update_post, upload_media  # noqa: E402


def parse_mapping(values: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in values:
        if ":" not in value:
            raise ValueError(f"Invalid mapping: {value}")
        post_id_text, item_index_text = value.split(":", 1)
        items.append({"post_id": int(post_id_text), "item_index": int(item_index_text)})
    return items


def refresh_item(
    post_id: int,
    item_index: int,
    api_base: str,
    username: str,
    application_password: str,
) -> dict[str, Any]:
    image_plan_path = GENERATED_DIR / "images" / f"featured_image_plan_item_{item_index}.json"
    image_plan = read_json(image_plan_path, {}) or {}
    image_path = PROJECT_ROOT / str(image_plan.get("output_path", ""))
    image_file_exists = image_path.exists() and image_path.is_file() and image_path.stat().st_size > 0
    if not image_file_exists:
        raise RuntimeError(f"Featured image does not exist for item {item_index}: {image_path}")
    image_blocked_reasons = featured_image_gate_reasons(image_plan, image_exists=image_file_exists)
    if image_blocked_reasons:
        raise RuntimeError(f"Featured image is not ready for item {item_index}: {' / '.join(image_blocked_reasons)}")
    media = upload_media(
        api_base,
        username,
        application_password,
        image_path,
        str(image_plan.get("alt_text") or ""),
    )
    updated = update_post(
        api_base,
        username,
        application_password,
        post_id,
        {"featured_media": media["id"]},
    )
    return {
        "item_index": item_index,
        "post_id": post_id,
        "status": "updated",
        "image_plan_path": f"03_generated/images/{image_plan_path.name}",
        "image_path": str(image_path.relative_to(PROJECT_ROOT)),
        "media": {
            "id": media.get("id"),
            "source_url": media.get("source_url"),
            "alt_text": media.get("alt_text"),
        },
        "post": {
            "id": updated.get("id"),
            "status": updated.get("status"),
            "date": updated.get("date"),
            "link": updated.get("link"),
            "featured_media": updated.get("featured_media"),
        },
    }


def update_state_featured_media(items: list[dict[str, Any]]) -> None:
    state_path = STATE_DIR / "scheduled_posts.json"
    state = read_json(state_path, {}) or {}
    rows = state.get("items", []) if isinstance(state.get("items"), list) else []
    media_by_post = {item.get("post_id"): item.get("media", {}).get("id") for item in items}
    for row in rows:
        post_id = row.get("wordpress_post_id")
        if post_id in media_by_post:
            row["featured_media_id"] = media_by_post[post_id]
            row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(state_path, state)


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# WordPressアイキャッチ差し替え結果",
        "",
        f"- 実行日時: {payload.get('finished_at')}",
        f"- ステータス: {payload.get('status')}",
        "",
    ]
    for item in payload.get("items", []):
        media = item.get("media", {}) if isinstance(item.get("media"), dict) else {}
        post = item.get("post", {}) if isinstance(item.get("post"), dict) else {}
        lines.extend(
            [
                f"## {item.get('item_index')}件目",
                "",
                f"- 投稿ID: {item.get('post_id')}",
                f"- 投稿ステータス: {post.get('status')}",
                f"- 新メディアID: {media.get('id')}",
                f"- 画像URL: {media.get('source_url')}",
                f"- 画像ファイル: {item.get('image_path')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    WORDPRESS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "wordpress_featured_image_refresh_latest.json", payload)
    write_json(LOGS_DIR / f"wordpress-featured-image-refresh-{timestamp}.json", payload)
    write_json(WORDPRESS_DIR / "wordpress_featured_image_refresh_latest.json", payload)
    write_markdown(WORDPRESS_DIR / "wordpress_featured_image_refresh_latest.md", render_report(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh featured images for existing WordPress draft posts.")
    parser.add_argument(
        "--mapping",
        action="append",
        required=True,
        help="Mapping in the form POST_ID:ITEM_INDEX, for example 4740:1. Repeat for each item.",
    )
    args = parser.parse_args()
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "items": [],
    }
    try:
        if os.environ.get("KSRFP_ALLOW_WORDPRESS_WRITE") != "1":
            raise RuntimeError("Write guard is active. Set KSRFP_ALLOW_WORDPRESS_WRITE=1 to execute.")
        settings = read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}
        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")
        api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
        mappings = parse_mapping(args.mapping)
        payload["items"] = [
            refresh_item(
                int(item["post_id"]),
                int(item["item_index"]),
                api_base,
                str(credentials["username"]),
                str(credentials["application_password"]),
            )
            for item in mappings
        ]
        update_state_featured_media(payload["items"])
        payload["status"] = "ok"
        return_code = 0
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
