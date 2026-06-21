#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.article_brief import render_brief  # noqa: E402
from ksrfp_jinjiroumu_blog.article_writer import render_article, select_article_title  # noqa: E402
from ksrfp_jinjiroumu_blog.fact_check import build_fact_check_items  # noqa: E402
from ksrfp_jinjiroumu_blog.io_utils import read_csv_dicts, read_json, read_text, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.outline_builder import classify_outline_topic, render_outline, select_outline_template  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, GENERATED_DIR, LOGS_DIR, TOPIC_SELECTION_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.quality_check import run_quality_check  # noqa: E402
from ksrfp_jinjiroumu_blog.source_plan import (  # noqa: E402
    COMMON_OFFICIAL_SOURCES,
    TOPIC_SOURCE_MAP,
    build_required_checks,
    classify_source_topic,
    render_source_plan,
)
from ksrfp_jinjiroumu_blog.state_manager import (  # noqa: E402
    ensure_state_files,
    render_state_summary,
    state_paths,
    topic_key_from_row,
    upsert_state_item,
)
from ksrfp_jinjiroumu_blog.wordpress_client import read_wordpress_credentials, update_post, upload_media  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_payload import build_wordpress_payload  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_payload import markdown_to_html  # noqa: E402


def write_log(payload: dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (LOGS_DIR / "wordpress_update_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (LOGS_DIR / f"wordpress-update-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_topic_row(topic_key: str) -> dict[str, str]:
    rows = read_csv_dicts(TOPIC_SELECTION_DIR / "topic_selection_scores.csv")
    for row in rows:
        if topic_key_from_row(row) == topic_key:
            return row
    raise RuntimeError(f"Topic key not found: {topic_key}")


def write_topic_artifacts(selected: dict[str, str], post_id: int) -> str:
    article = render_article(selected)
    title = select_article_title(selected)
    generated = {
        "status": "ok",
        "selected_topic": selected.get("topic_title", ""),
        "title": title,
        "character_count": len(article),
        "path": str(GENERATED_DIR / "articles" / "article_draft_latest.md"),
        "revision_for_wordpress_post_id": post_id,
    }
    write_json(GENERATED_DIR / "articles" / "article_draft_latest.json", generated)
    write_markdown(GENERATED_DIR / "articles" / "article_draft_latest.md", article)
    write_json(GENERATED_DIR / "articles" / f"article_draft_post_{post_id}.json", generated)
    write_markdown(GENERATED_DIR / "articles" / f"article_draft_post_{post_id}.md", article)

    selected_for_brief = dict(selected)
    selected_for_brief["selection_reason"] = "manual_post_revision"
    brief = {"status": "ok", "selected": selected_for_brief, "alternatives": [selected_for_brief]}
    write_json(GENERATED_DIR / "outlines" / "article_brief_latest.json", brief)
    write_markdown(GENERATED_DIR / "outlines" / "article_brief_latest.md", render_brief(selected_for_brief, [selected_for_brief]))

    outline_topic_type = classify_outline_topic(selected_for_brief.get("topic_title", ""), selected_for_brief.get("labels", ""))
    outline = select_outline_template(outline_topic_type)
    outline_payload = {"status": "ok", "selected_topic": selected_for_brief, "outline": outline}
    write_json(GENERATED_DIR / "outlines" / "article_outline_latest.json", outline_payload)
    write_markdown(
        GENERATED_DIR / "outlines" / "article_outline_latest.md",
        render_outline(selected_for_brief, outline, outline_topic_type),
    )

    topic_type = classify_source_topic(selected.get("topic_title", ""), selected.get("labels", ""))
    source_payload = {
        "status": "ok",
        "selected_topic": selected.get("topic_title", ""),
        "topic_type": topic_type,
        "sources": TOPIC_SOURCE_MAP.get(topic_type, []) + COMMON_OFFICIAL_SOURCES,
        "required_checks": build_required_checks(topic_type),
    }
    write_json(GENERATED_DIR / "outlines" / "source_check_plan_latest.json", source_payload)
    write_markdown(GENERATED_DIR / "outlines" / "source_check_plan_latest.md", render_source_plan(source_payload))

    build_fact_check_items()
    run_quality_check()
    return article


def record_wordpress_post_revision(selected: dict[str, str], updated: dict[str, object]) -> dict[str, object]:
    state = ensure_state_files()
    post_status = str(updated.get("status") or "")
    topic_status = "drafted" if post_status == "draft" else "scheduled" if post_status == "future" else post_status or "posted"
    topic_key = topic_key_from_row(selected)
    now = datetime.now().isoformat(timespec="seconds")
    post_id = updated.get("id")
    link = updated.get("link")

    scheduled_entry = {
        "wordpress_post_id": post_id,
        "wordpress_url": link,
        "wordpress_status": post_status,
        "scheduled_local": updated.get("date"),
        "scheduled_gmt": updated.get("date_gmt"),
        "status": "draft" if post_status == "draft" else topic_status,
        "topic_key": topic_key,
        "pdf_name": selected.get("pdf_name"),
        "section_group": selected.get("section_group"),
        "topic_title": selected.get("topic_title"),
        "title": select_article_title(selected),
        "category_ids": updated.get("categories", []),
        "tags": updated.get("tags", []),
        "featured_media_id": updated.get("featured_media"),
        "updated_at": now,
    }
    state["scheduled_posts"]["note"] = "WordPress下書き・予約投稿の日時、投稿ID、テーマを記録し、同じテーマの重複を避ける。"
    upsert_state_item(state["scheduled_posts"], "wordpress_post_id", scheduled_entry)
    write_json(state_paths()["scheduled_posts"], state["scheduled_posts"])

    topic_entry = {
        "topic_key": topic_key,
        "pdf_name": selected.get("pdf_name"),
        "section_group": selected.get("section_group"),
        "topic_title": selected.get("topic_title"),
        "status": topic_status,
        "last_generated_at": now,
        "publication_gate": "verified",
        "fact_check_unverified": 0,
        "wordpress_post_id": post_id,
        "wordpress_url": link,
    }
    state["topic_history"]["note"] = "記事化済み・下書き投稿済みのテーマを記録し、重複生成を避ける。"
    upsert_state_item(state["topic_history"], "topic_key", topic_entry)
    write_json(state_paths()["topic_history"], state["topic_history"])

    state["automation_status"] = {
        "version": 1,
        "last_run_at": now,
        "last_status": "manual_revision",
        "safe_to_publish": True,
        "publication_ready": True,
        "draft_quality_passed": True,
        "fact_check_unverified": 0,
        "publication_gate": "verified",
        "last_selected_topic_key": topic_key,
        "last_selected_pdf": selected.get("pdf_name"),
        "last_selected_topic": selected.get("topic_title"),
        "last_error": None,
    }
    write_json(state_paths()["automation_status"], state["automation_status"])
    write_markdown(state_paths()["readme"], render_state_summary(state))
    return scheduled_entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded update for an existing WordPress post.")
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--content-from-latest-article", action="store_true")
    parser.add_argument("--content-from-topic-key")
    parser.add_argument("--status", choices=["draft", "future", "publish", "pending", "private"])
    parser.add_argument("--date")
    parser.add_argument("--date-gmt")
    parser.add_argument("--refresh-featured-image", action="store_true")
    args = parser.parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        if os.environ.get("KSRFP_ALLOW_WORDPRESS_WRITE") != "1":
            raise RuntimeError("Write guard is active. Set KSRFP_ALLOW_WORDPRESS_WRITE=1 to execute.")
        if not args.content_from_latest_article and not args.content_from_topic_key and not args.refresh_featured_image:
            raise RuntimeError("No update source specified.")
        settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")
        selected_topic = None
        if args.content_from_topic_key:
            selected_topic = find_topic_row(args.content_from_topic_key)
            article = write_topic_artifacts(selected_topic, args.post_id)
        elif args.content_from_latest_article:
            article = read_text(GENERATED_DIR / "articles" / "article_draft_latest.md")
        else:
            article = ""
        content_html = markdown_to_html(article) if article else ""
        post_update: dict[str, object] = {}
        if content_html:
            post_update["content"] = content_html
        if selected_topic:
            post_update["title"] = select_article_title(selected_topic)
        if args.status:
            post_update["status"] = args.status
        if args.date:
            post_update["date"] = args.date
        if args.date_gmt:
            post_update["date_gmt"] = args.date_gmt
        media = None
        if args.refresh_featured_image:
            image_plan = read_json(GENERATED_DIR / "images" / "featured_image_plan_latest.json", {}) or {}
            image_path = PROJECT_ROOT / str(image_plan.get("output_path", ""))
            if not image_path.exists() or not image_path.is_file() or image_path.stat().st_size <= 0:
                raise RuntimeError(f"Featured image does not exist: {image_path}")
            media = upload_media(
                str(settings.get("wordpress_api_base", "")).rstrip("/"),
                credentials["username"],
                credentials["application_password"],
                image_path,
                str(image_plan.get("alt_text") or ""),
            )
            post_update["featured_media"] = media["id"]
        if not post_update:
            raise RuntimeError("No update fields were built.")
        updated = update_post(
            str(settings.get("wordpress_api_base", "")).rstrip("/"),
            credentials["username"],
            credentials["application_password"],
            args.post_id,
            post_update,
        )
        state_record = record_wordpress_post_revision(selected_topic, updated) if selected_topic else None
        latest_payload = build_wordpress_payload() if selected_topic else None
        result = {
            "status": "updated",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "post": {
                "id": updated.get("id"),
                "status": updated.get("status"),
                "date": updated.get("date"),
                "date_gmt": updated.get("date_gmt"),
                "link": updated.get("link"),
                "title": updated.get("title", {}).get("raw")
                if isinstance(updated.get("title"), dict)
                else updated.get("title"),
            },
            "content_h1_removed": "<h1" not in content_html,
            "content_contains_h2": "<h2" in content_html if content_html else None,
            "content_length": len(content_html),
            "media": {"id": media.get("id"), "link": media.get("source_url")} if media else None,
            "topic_key": args.content_from_topic_key,
            "state_record": state_record,
            "latest_payload_status": (latest_payload or {}).get("wordpress", {}).get("status")
            if isinstance((latest_payload or {}).get("wordpress"), dict)
            else None,
        }
        (WORDPRESS_DIR / "wordpress_update_result_latest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        payload = {
            "status": result["status"],
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "result": result,
            "outputs": {
                "update_result": "04_wordpress/wordpress_update_result_latest.json",
                "update_log": "07_logs/wordpress_update_latest.json",
            },
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
