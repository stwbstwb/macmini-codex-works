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
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, LOGS_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    fetch_wordpress_posts,
    read_wordpress_credentials,
)


DEFAULT_INVALID_TITLES = {
    "同一労働同一賃金ガイドライン改正で中小企業が見直したい待遇説明",
    "65歳超雇用推進助成金で中小企業が確認したい高年齢者雇用管理",
    "女性活躍推進法の一般事業主行動計画で中小企業が確認したい実務",
}


def rendered_title(post: dict[str, Any]) -> str:
    title = post.get("title")
    if isinstance(title, dict):
        return str(title.get("raw") or title.get("rendered") or "")
    return str(title or "")


def build_inventory(status: str, per_page: int, invalid_titles: set[str]) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    credentials = read_wordpress_credentials()
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    posts = fetch_wordpress_posts(
        api_base,
        credentials["username"],
        credentials["application_password"],
        {
            "status": status,
            "per_page": str(per_page),
            "context": "edit",
            "_fields": "id,title,status,date,link,slug,categories,author,featured_media",
        },
    )
    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for post in posts:
        row = {
            "id": post.get("id"),
            "status": post.get("status"),
            "date": post.get("date"),
            "title": rendered_title(post),
            "link": post.get("link"),
            "categories": post.get("categories"),
            "author": post.get("author"),
            "featured_media": post.get("featured_media"),
        }
        rows.append(row)
        if row["title"] in invalid_titles:
            invalid.append(row)
    return {
        "status": "ok",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "wordpress_status_filter": status,
        "draft_count": len(rows),
        "invalid_202603_count": len(invalid),
        "invalid_202603_posts": invalid,
        "drafts": rows,
    }


def render_inventory(payload: dict[str, Any]) -> str:
    lines = [
        "# WordPress下書き一覧",
        "",
        f"- 生成日時: {payload.get('generated_at')}",
        f"- ステータス: {payload.get('status')}",
        f"- 下書き件数: {payload.get('draft_count')}",
        f"- 無効2026.3候補: {payload.get('invalid_202603_count')}",
        "",
        "## 無効2026.3候補",
    ]
    for post in payload.get("invalid_202603_posts", []):
        lines.append(f"- {post.get('id')} / {post.get('title')} / {post.get('link')}")
    lines.extend(["", "## 全下書き"])
    for post in payload.get("drafts", []):
        lines.append(f"- {post.get('id')} / {post.get('title')} / {post.get('date')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch WordPress draft inventory for cleanup verification.")
    parser.add_argument("--status", default="draft")
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--invalid-title", action="append", default=[])
    args = parser.parse_args()

    invalid_titles = set(DEFAULT_INVALID_TITLES)
    invalid_titles.update(args.invalid_title)
    payload = build_inventory(args.status, args.per_page, invalid_titles)
    write_json(LOGS_DIR / "wordpress_draft_inventory_latest.json", payload)
    write_json(LOGS_DIR / f"wordpress-draft-inventory-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json", payload)
    write_json(WORDPRESS_DIR / "wordpress_draft_inventory_latest.json", payload)
    write_markdown(WORDPRESS_DIR / "wordpress_draft_inventory_latest.md", render_inventory(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
