#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.analyze_inputs import run  # noqa: E402


def write_run_log(payload: dict[str, object]) -> None:
    log_dir = PROJECT_ROOT / "07_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (log_dir / "latest_run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (log_dir / f"run-{timestamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        results = run()
        payload = {
            "status": "ok",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "gsc_queries": results["gsc"]["query_count"],
            "gsc_pages": results["gsc"]["page_count"],
            "posted_articles": results["posted_articles"]["article_count"],
            "posted_article_themes": results["posted_article_topics"]["theme_count"],
            "ga_sections": results["ga"]["section_count"],
            "ga_page_titles": results["ga_insights"]["page_title_count"],
            "newsletter_pdfs": results["newsletters"]["pdf_count"],
            "newsletter_topic_candidates": results["newsletters"]["topic_candidate_count"],
            "scored_topics": results["topic_selection"]["scored_topic_count"],
            "generated_article_count": results.get("articles", {}).get("generated_count")
            if isinstance(results.get("articles"), dict)
            else 1,
            "articles": summarize_articles(results),
            "top_topic": results["topic_selection"]["top_topics"][0]["topic_title"]
            if results["topic_selection"]["top_topics"]
            else None,
            "brief_status": results["article_brief"]["status"],
            "brief_selected_topic": results["article_brief"].get("selected", {}).get("topic_title"),
            "source_plan_status": results["source_plan"]["status"],
            "outline_status": results["article_outline"]["status"],
            "article_draft_status": results["article_draft"]["status"],
            "article_draft_characters": results["article_draft"].get("character_count"),
            "fact_check_unverified": results["fact_check"].get("unverified_count"),
            "publication_gate": results["fact_check"].get("publication_gate"),
            "draft_quality_passed": results["quality_check"]["draft_quality_passed"],
            "publication_ready": results["quality_check"]["publication_ready"],
            "safe_to_publish": results["quality_check"]["passed"],
            "featured_image_plan_status": results["featured_image_plan"].get("status"),
            "review_text_status": results.get("review_text", {}).get("status"),
            "review_text_file": results.get("review_text", {}).get("file_name"),
            "featured_image_file_name": results["featured_image_plan"].get("file_name"),
            "wordpress_payload_ready_to_send": results["wordpress_payload"].get("ready_to_send"),
            "wordpress_payload_status": results["wordpress_payload"].get("wordpress", {}).get("status"),
            "wordpress_scheduled_date": results["wordpress_payload"].get("wordpress", {}).get("date"),
            "wordpress_slug_set": "slug" in results["wordpress_payload"].get("wordpress", {}),
            "wordpress_author": results["wordpress_payload"].get("wordpress", {}).get("author"),
            "wordpress_category": results["wordpress_payload"].get("category_assignment", {}).get("name"),
            "wordpress_category_id": results["wordpress_payload"].get("category_assignment", {}).get("id"),
            "wordpress_tags": results["wordpress_payload"].get("wordpress", {}).get("tags"),
            "arkhe_css_editor_set": bool(results["wordpress_payload"].get("arkhe_css_editor", {}).get("css")),
            "drive_status": results["drive_status"].get("status"),
            "wordpress_status": results["wordpress_status"].get("status"),
            "automation_status": results["automation_status"].get("last_status"),
            "outputs": {
                "initial_report": "02_analysis/seo/initial_analysis_report.md",
                "ga_content_insights": "02_analysis/seo/ga_content_insights.md",
                "posted_article_theme_report": "02_analysis/cannibalization/posted_articles_theme_report.md",
                "topic_selection_report": "02_analysis/topic-selection/topic_selection_report.md",
                "article_batch": "03_generated/articles/article_batch_latest.md",
                "source_plan": "03_generated/outlines/source_check_plan_latest.md",
                "article_brief": "03_generated/outlines/article_brief_latest.md",
                "article_outline": "03_generated/outlines/article_outline_latest.md",
                "article_draft": "03_generated/articles/article_draft_latest.md",
                "fact_check": "03_generated/articles/fact_check_items_latest.md",
                "quality_check": "03_generated/articles/article_quality_check_latest.md",
                "featured_image_plan": "03_generated/images/featured_image_plan_latest.md",
                "review_text": "03_generated/review-texts/review_text_latest.md",
                "schedule_plan": "03_generated/wordpress-payloads/schedule_plan_latest.md",
                "wordpress_payload": "03_generated/wordpress-payloads/post_payload_latest.md",
                "wordpress_payloads": "03_generated/wordpress-payloads/post_payloads_latest.json",
                "drive_status": "05_drive/drive_status_latest.md",
                "wordpress_status": "04_wordpress/wordpress_status_latest.md",
                "state_summary": "08_state/state_summary.md",
            },
        }
        write_run_log(payload)
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
        write_run_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


def summarize_articles(results: dict[str, object]) -> list[dict[str, object]]:
    articles = results.get("articles", {}) if isinstance(results.get("articles"), dict) else {}
    summaries: list[dict[str, object]] = []
    for item in articles.get("items", []):
        if not isinstance(item, dict):
            continue
        selected = item.get("selected", {}) if isinstance(item.get("selected"), dict) else {}
        wordpress_payload = item.get("wordpress_payload", {}) if isinstance(item.get("wordpress_payload"), dict) else {}
        wordpress = wordpress_payload.get("wordpress", {}) if isinstance(wordpress_payload.get("wordpress"), dict) else {}
        category = wordpress_payload.get("category_assignment", {}) if isinstance(wordpress_payload.get("category_assignment"), dict) else {}
        review_text = item.get("review_text", {}) if isinstance(item.get("review_text"), dict) else {}
        summaries.append(
            {
                "item_index": item.get("item_index"),
                "topic": selected.get("topic_title"),
                "pdf": selected.get("pdf_name"),
                "section": selected.get("section_group"),
                "title": wordpress.get("title"),
                "scheduled_date": wordpress.get("date"),
                "category": category.get("name"),
                "category_id": category.get("id"),
                "review_text_file": review_text.get("file_name"),
                "drive_status": (review_text.get("upload") or {}).get("status")
                if isinstance(review_text.get("upload"), dict)
                else None,
            }
        )
    return summaries


if __name__ == "__main__":
    raise SystemExit(main())
