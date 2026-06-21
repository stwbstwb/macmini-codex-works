#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.analyze_inputs import run  # noqa: E402
from ksrfp_jinjiroumu_blog.artifact_fingerprint import (  # noqa: E402
    current_manifest_digest,
    manifest_fingerprint,
    payload_matches_current_manifest,
)
from ksrfp_jinjiroumu_blog.external_preflight import run_external_preflight  # noqa: E402
from ksrfp_jinjiroumu_blog.image_gate import featured_image_gate_reasons  # noqa: E402
from ksrfp_jinjiroumu_blog.io_utils import read_json  # noqa: E402
from ksrfp_jinjiroumu_blog.notification import send_run_notification  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, GENERATED_DIR, LOGS_DIR  # noqa: E402


def load_retry_policy() -> dict[str, object]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    return settings.get(
        "retry_policy",
        {
            "max_attempts": 3,
            "retry_delay_seconds": 60,
            "continue_after_failure": True,
        },
    )


def load_completion_retry_policy() -> dict[str, object]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    retry_policy = settings.get("completion_retry_policy")
    if isinstance(retry_policy, dict):
        return retry_policy
    base = load_retry_policy()
    return {
        "max_attempts": base.get("max_attempts", 3),
        "retry_delay_seconds": base.get("retry_delay_seconds", 60),
    }


def write_weekly_log(payload: dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (LOGS_DIR / "weekly_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (LOGS_DIR / f"weekly-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def first_value(*values: object) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def compact_text(value: object, limit: int = 260) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def build_source_fields(results: dict[str, object], wordpress_payload: dict[str, object]) -> dict[str, object | None]:
    article_brief = as_dict(results.get("article_brief"))
    selected = as_dict(article_brief.get("selected"))
    wordpress_source = as_dict(wordpress_payload.get("source"))

    def pick(key: str) -> object | None:
        return first_value(wordpress_source.get(key), selected.get(key))

    return {
        "source_pdf_name": pick("pdf_name"),
        "source_section_group": pick("section_group"),
        "source_topic_title": pick("topic_title"),
        "source_topic_key": pick("topic_key"),
        "source_labels": pick("labels"),
        "source_date_mentions": pick("date_mentions"),
        "source_excerpt": compact_text(pick("excerpt")),
        "source_nearest_article_title": pick("nearest_article_title"),
        "source_nearest_article_url": pick("nearest_article_url"),
        "source_nearest_similarity": pick("nearest_similarity"),
    }


def build_article_summaries(results: dict[str, object]) -> list[dict[str, object | None]]:
    articles = as_dict(results.get("articles"))
    summaries: list[dict[str, object | None]] = []
    for item in articles.get("items", []):
        if not isinstance(item, dict):
            continue
        selected = as_dict(item.get("selected"))
        wordpress_payload = as_dict(item.get("wordpress_payload"))
        wordpress = as_dict(wordpress_payload.get("wordpress"))
        category = as_dict(wordpress_payload.get("category_assignment"))
        quality = as_dict(item.get("quality_check"))
        fact_check = as_dict(item.get("fact_check"))
        review_text = as_dict(item.get("review_text"))
        upload = as_dict(review_text.get("upload"))
        image_plan = as_dict(item.get("featured_image_plan"))
        base_image = as_dict(image_plan.get("base_image"))
        outputs = as_dict(item.get("outputs"))
        image_generation_attempts = item.get("image_source_generation", [])
        image_generation_attempts = image_generation_attempts if isinstance(image_generation_attempts, list) else []
        summaries.append(
            {
                "item_index": item.get("item_index"),
                "source_pdf_name": selected.get("pdf_name"),
                "source_section_group": selected.get("section_group"),
                "source_topic_title": selected.get("topic_title"),
                "source_topic_key": selected.get("topic_key"),
                "source_labels": selected.get("labels"),
                "source_date_mentions": selected.get("date_mentions"),
                "source_excerpt": compact_text(selected.get("excerpt")),
                "source_nearest_article_title": selected.get("nearest_article_title"),
                "source_nearest_article_url": selected.get("nearest_article_url"),
                "source_nearest_similarity": selected.get("nearest_similarity"),
                "article_title": wordpress.get("title"),
                "wordpress_payload_ready_to_send": wordpress_payload.get("ready_to_send"),
                "wordpress_payload_status": wordpress.get("status"),
                "wordpress_scheduled_date": wordpress.get("date"),
                "wordpress_category": category.get("name"),
                "wordpress_category_id": category.get("id"),
                "draft_quality_passed": quality.get("draft_quality_passed"),
                "publication_ready": quality.get("publication_ready"),
                "fact_check_unverified": fact_check.get("unverified_count"),
                "publication_gate": fact_check.get("publication_gate"),
                "review_text_file": review_text.get("file_name"),
                "review_text_upload_status": upload.get("status"),
                "review_text_drive_url": upload.get("webViewLink"),
                "featured_image_quality_ready": image_plan.get("wordpress_ready"),
                "featured_image_base_status": base_image.get("status"),
                "featured_image_photo_source_exists": base_image.get("photo_source_exists"),
                "featured_image_source_path": base_image.get("source_path"),
                "featured_image_plan_path": outputs.get("featured_image_plan_json"),
                "featured_image_prompt": image_plan.get("prompt"),
                "image_generation_statuses": [
                    attempt.get("status")
                    for attempt in image_generation_attempts
                    if isinstance(attempt, dict)
                ],
                "blocked_reasons": wordpress_payload.get("blocked_reasons"),
            }
        )
    return summaries


def build_success_payload(started_at: str, results: dict[str, object], attempt_logs: list[dict[str, object]]) -> dict[str, object]:
    wordpress_payload = as_dict(results.get("wordpress_payload"))
    wordpress = as_dict(wordpress_payload.get("wordpress"))
    category = as_dict(wordpress_payload.get("category_assignment"))
    fact_check = as_dict(results.get("fact_check"))
    quality_check = as_dict(results.get("quality_check"))
    image_plan = as_dict(results.get("featured_image_plan"))
    drive_status = as_dict(results.get("drive_status"))
    wordpress_status = as_dict(results.get("wordpress_status"))
    source_fields = build_source_fields(results, wordpress_payload)
    article_summaries = build_article_summaries(results)
    newsletters = as_dict(results.get("newsletters"))
    issue_selection = as_dict(newsletters.get("issue_selection"))
    articles = as_dict(results.get("articles"))
    batch_quality = as_dict(articles.get("batch_quality"))
    payload = {
        "status": derive_generation_status(article_summaries, issue_selection, batch_quality),
        "run_key": started_at,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "attempts": len(attempt_logs),
        "attempt_logs": attempt_logs,
        "gsc_queries": results["gsc"]["query_count"],
        "gsc_pages": results["gsc"]["page_count"],
        "posted_articles": results["posted_articles"]["article_count"],
        "posted_article_themes": results["posted_article_topics"]["theme_count"],
        "ga_sections": results["ga"]["section_count"],
        "ga_page_titles": results["ga_insights"]["page_title_count"],
        "newsletter_pdfs": results["newsletters"]["pdf_count"],
        "newsletter_available_pdfs": results["newsletters"].get("available_pdf_count"),
        "newsletter_issue_selection": issue_selection,
        "newsletter_topic_candidates": results["newsletters"]["topic_candidate_count"],
        "scored_topics": results["topic_selection"]["scored_topic_count"],
        "generated_article_count": len(article_summaries),
        "article_batch_quality_passed": batch_quality.get("passed"),
        "article_batch_quality_status": batch_quality.get("status"),
        "article_batch_quality": {
            "max_intro_similarity": batch_quality.get("max_intro_similarity"),
            "max_summary_similarity": batch_quality.get("max_summary_similarity"),
            "max_h2_similarity": batch_quality.get("max_h2_similarity"),
            "image_backgrounds_unique": batch_quality.get("image_backgrounds_unique"),
            "intra_article_repetition_ok": batch_quality.get("intra_article_repetition_ok"),
            "title_uniqueness_ok": batch_quality.get("title_uniqueness_ok"),
            "title_pattern_diversity_ok": batch_quality.get("title_pattern_diversity_ok"),
            "structure_pattern_diversity_ok": batch_quality.get("structure_pattern_diversity_ok"),
        },
        "articles": article_summaries,
        "brief_selected_topic": as_dict(as_dict(results.get("article_brief")).get("selected")).get("topic_title"),
        "article_draft_characters": results["article_draft"].get("character_count"),
        "fact_check_unverified": fact_check.get("unverified_count", 0),
        "publication_gate": fact_check.get("publication_gate") or issue_selection.get("status"),
        "draft_quality_passed": quality_check.get("draft_quality_passed", False),
        "publication_ready": quality_check.get("publication_ready", False),
        "safe_to_publish": quality_check.get("passed", False),
        "featured_image_plan_status": image_plan.get("status"),
        "review_text_status": results.get("review_text", {}).get("status"),
        "review_text_file": results.get("review_text", {}).get("file_name"),
        "review_text_upload_status": results.get("review_text", {}).get("upload", {}).get("status")
        if isinstance(results.get("review_text"), dict)
        else None,
        "wordpress_payload_ready_to_send": wordpress_payload.get("ready_to_send") if isinstance(wordpress_payload, dict) else None,
        "wordpress_payload_status": wordpress.get("status"),
        "wordpress_scheduled_date": wordpress.get("date"),
        "wordpress_slug_set": "slug" in wordpress,
        "wordpress_author": wordpress.get("author"),
        "wordpress_category": category.get("name"),
        "wordpress_category_id": category.get("id"),
        "wordpress_tags": wordpress.get("tags"),
        "arkhe_css_editor_set": bool(wordpress_payload.get("arkhe_css_editor", {}).get("css"))
        if isinstance(wordpress_payload, dict)
        else False,
        "drive_status": drive_status.get("status"),
        "wordpress_status": wordpress_status.get("status"),
        "outputs": output_paths(),
    }
    payload.update(source_fields)
    return payload


def derive_generation_status(
    article_summaries: list[dict[str, object | None]],
    issue_selection: dict[str, object] | None = None,
    batch_quality: dict[str, object] | None = None,
) -> str:
    """Classify the generation stage without implying final WordPress completion."""
    issue_selection = issue_selection or {}
    batch_quality = batch_quality or {}
    if issue_selection.get("status") == "all_issues_completed":
        return "blocked_all_newsletter_issues_completed"
    if not article_summaries:
        return "blocked_no_articles"
    try:
        expected_articles = max(
            1,
            int((read_json(CONFIG_DIR / "project_settings.json", {}) or {}).get("articles_per_run") or 3),
        )
    except (TypeError, ValueError):
        expected_articles = 3
    if len(article_summaries) < expected_articles:
        return "blocked_insufficient_articles"
    if batch_quality and batch_quality.get("passed") is not True:
        return "blocked_batch_quality"
    if any(not article.get("wordpress_payload_ready_to_send") for article in article_summaries):
        if needs_external_image_generation_tool(article_summaries):
            return "needs_image_generation_tool"
        return "blocked_before_wordpress"
    if any(int(article.get("fact_check_unverified") or 0) > 0 for article in article_summaries):
        return "blocked_until_verified"
    if any(article.get("publication_gate") == "blocked_until_verified" for article in article_summaries):
        return "blocked_until_verified"
    return "generation_ready_for_wordpress"


def needs_external_image_generation_tool(article_summaries: list[dict[str, object | None]]) -> bool:
    if not article_summaries:
        return False
    for article in article_summaries:
        if article.get("draft_quality_passed") is not True:
            return False
        if article.get("publication_ready") is not True:
            return False
        if int(article.get("fact_check_unverified") or 0) > 0:
            return False
        statuses = article.get("image_generation_statuses")
        statuses = statuses if isinstance(statuses, list) else []
        blocked_reasons = article.get("blocked_reasons")
        blocked_reasons = blocked_reasons if isinstance(blocked_reasons, list) else []
        image_blocked = article.get("featured_image_quality_ready") is not True
        auth_blocked = "blocked_auth_required" in statuses
        image_reason_only = bool(blocked_reasons) and all(
            "アイキャッチ" in str(reason) or "写真" in str(reason) or "画像" in str(reason)
            for reason in blocked_reasons
        )
        if not (image_blocked and (auth_blocked or image_reason_only)):
            return False
    return True


def build_failure_payload(started_at: str, attempt_logs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "error",
        "run_key": started_at,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "attempts": len(attempt_logs),
        "attempt_logs": attempt_logs,
        "error": attempt_logs[-1].get("error") if attempt_logs else "Unknown error",
        "traceback": attempt_logs[-1].get("traceback") if attempt_logs else "",
        "outputs": output_paths(),
    }


def build_preflight_failure_payload(started_at: str, preflight: dict[str, object]) -> dict[str, object]:
    return {
        "status": "blocked_preflight_failed",
        "run_key": started_at,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "attempts": 0,
        "attempt_logs": [],
        "external_preflight": preflight,
        "error": "外部連携プリフライトがNGのため、記事生成・Drive保存・WordPress下書き保存へ進まず停止しました。",
        "outputs": output_paths(),
    }


def build_partial_draft_issue_payload(started_at: str, partial_issues: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "blocked_partial_draft_issue",
        "run_key": started_at,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "attempts": 0,
        "attempt_logs": [],
        "partial_draft_issues": partial_issues,
        "error": (
            "前回までのWordPress下書きが号単位で一部だけ残っています。"
            "このまま新規3件生成へ進むと同じ号で過剰な下書きを作る可能性があるため停止しました。"
        ),
        "outputs": output_paths(),
    }


def detect_partial_draft_issues() -> list[dict[str, object]]:
    state = read_json(PROJECT_ROOT / "08_state" / "processed_pdfs.json", {}) or {}
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    try:
        required_count = max(1, int(settings.get("articles_per_run") or 3))
    except (TypeError, ValueError):
        required_count = 3
    items = state.get("items", []) if isinstance(state.get("items"), list) else []
    partial: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        post_count = int(item.get("wordpress_post_count") or 0)
        status = str(item.get("status") or "")
        if status == "partially_drafted" or 0 < post_count < required_count:
            partial.append(
                {
                    "pdf_name": item.get("pdf_name"),
                    "period_key": item.get("period_key"),
                    "status": status,
                    "wordpress_post_count": post_count,
                    "required_article_count": item.get("required_article_count") or required_count,
                    "wordpress_post_ids": item.get("wordpress_post_ids"),
                    "created_topic_keys": item.get("created_topic_keys"),
                }
            )
    return partial


def expected_articles_per_run() -> int:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    try:
        return max(1, int(settings.get("articles_per_run") or 3))
    except (TypeError, ValueError):
        return 3


RESUMABLE_WEEKLY_STATUSES = {
    "generation_ready_for_wordpress",
    "needs_image_generation_tool",
    "needs_drive_upload_plugin",
    "partial",
    "error",
}


def existing_artifacts_need_resume(partial_issues: list[dict[str, object]]) -> bool:
    """Only resume current artifacts when the previous run is known unfinished."""
    if partial_issues:
        return True
    if not current_manifest_digest():
        return False
    latest = read_json(LOGS_DIR / "weekly_latest.json", {}) or {}
    if not isinstance(latest, dict):
        return False
    status = str(latest.get("status") or "")
    if status not in RESUMABLE_WEEKLY_STATUSES:
        return False
    if not payload_matches_current_manifest(latest):
        return False
    return True


def build_existing_artifact_resume_payload(
    started_at: str,
    partial_issues: list[dict[str, object]],
) -> dict[str, object] | None:
    """Build a weekly payload from the current manifest when a prior run can be resumed."""
    if not existing_artifacts_need_resume(partial_issues):
        return None
    resume = classify_existing_artifacts_for_resume()
    if resume.get("status") not in {"generation_ready_for_wordpress", "needs_image_generation_tool"}:
        return None
    partial_match = resume_matches_partial_issues(resume, partial_issues)
    if not partial_match.get("matched"):
        return None
    articles = resume.get("articles", [])
    payload = {
        "status": resume.get("status"),
        "run_key": started_at,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "attempts": 0,
        "attempt_logs": [
            {
                "attempt": 0,
                "status": "resumed_existing_artifacts",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "resume_status": resume.get("status"),
                "resume_reason": resume.get("reason"),
            }
        ],
        "generated_article_count": len(articles) if isinstance(articles, list) else 0,
        "articles": articles,
        "resume": {
            "status": resume.get("status"),
            "reason": resume.get("reason"),
            "partial_draft_issues": partial_issues,
            "partial_issue_match": partial_match,
            "blocked_reasons": resume.get("blocked_reasons"),
        },
        "publication_gate": "verified" if resume.get("status") == "generation_ready_for_wordpress" else "blocked_until_image_generation",
        "wordpress_payload_ready_to_send": all(
            bool(article.get("wordpress_payload_ready_to_send"))
            for article in articles
            if isinstance(article, dict)
        )
        if isinstance(articles, list)
        else False,
        "outputs": output_paths(),
    }
    if isinstance(articles, list) and articles:
        first = articles[0] if isinstance(articles[0], dict) else {}
        payload.update(
            {
                "source_pdf_name": first.get("source_pdf_name"),
                "source_section_group": first.get("source_section_group"),
                "source_topic_title": first.get("source_topic_title"),
                "wordpress_scheduled_date": first.get("wordpress_scheduled_date"),
                "wordpress_category": first.get("wordpress_category"),
                "wordpress_category_id": first.get("wordpress_category_id"),
                "wordpress_tags": [],
            }
        )
    return payload


def resume_matches_partial_issues(
    resume: dict[str, object],
    partial_issues: list[dict[str, object]],
) -> dict[str, object]:
    if not partial_issues:
        return {"matched": True, "reason": "no partial issue"}
    articles = resume.get("articles", [])
    articles = articles if isinstance(articles, list) else []
    article_pdf_names = {
        str(article.get("source_pdf_name") or "")
        for article in articles
        if isinstance(article, dict) and article.get("source_pdf_name")
    }
    article_topic_keys = {
        str(article.get("source_topic_key") or "")
        for article in articles
        if isinstance(article, dict) and article.get("source_topic_key")
    }
    for issue in partial_issues:
        if not isinstance(issue, dict):
            continue
        issue_pdf = str(issue.get("pdf_name") or "")
        if issue_pdf not in article_pdf_names:
            continue
        created_topic_keys = {
            str(value)
            for value in (issue.get("created_topic_keys") or [])
            if str(value)
        }
        if created_topic_keys and not created_topic_keys.issubset(article_topic_keys):
            return {
                "matched": False,
                "reason": "partial issue topic keys are not covered by current manifest",
                "partial_pdf_name": issue_pdf,
                "partial_topic_keys": sorted(created_topic_keys),
                "manifest_topic_keys": sorted(article_topic_keys),
            }
        return {
            "matched": True,
            "reason": "partial issue pdf and topic keys match current manifest",
            "partial_pdf_name": issue_pdf,
            "manifest_pdf_names": sorted(article_pdf_names),
        }
    return {
        "matched": False,
        "reason": "partial issue pdf does not match current manifest",
        "partial_pdf_names": [
            issue.get("pdf_name")
            for issue in partial_issues
            if isinstance(issue, dict)
        ],
        "manifest_pdf_names": sorted(article_pdf_names),
    }


def classify_existing_artifacts_for_resume() -> dict[str, object]:
    expected_count = expected_articles_per_run()
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    manifest = read_json(manifest_path, {}) or {}
    manifest_items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    if len(manifest_items) != expected_count:
        return {
            "status": "not_resumable",
            "reason": "current manifest item count does not match articles_per_run",
            "expected_count": expected_count,
            "actual_count": len(manifest_items),
        }
    quality_gate = resume_batch_quality_gate(expected_count, manifest_path)
    if not quality_gate.get("passed"):
        return {
            "status": "not_resumable",
            "reason": "current manifest batch quality gate is not passed",
            "batch_quality_gate": quality_gate,
        }

    article_rows: list[dict[str, object]] = []
    all_ready = True
    image_only_blocked = True
    blocked_reasons: list[dict[str, object]] = []
    for index, payload in enumerate(manifest_items, start=1):
        if not isinstance(payload, dict):
            all_ready = False
            image_only_blocked = False
            blocked_reasons.append({"item_index": index, "reason": "manifest item is not an object"})
            continue
        row = resume_article_summary(index, payload)
        article_rows.append(row)
        item_ready = bool(row.get("wordpress_payload_ready_to_send")) and bool(row.get("featured_image_quality_ready"))
        if not item_ready:
            all_ready = False
        quality_ready = (
            row.get("draft_quality_passed") is True
            and row.get("publication_ready") is True
            and int(row.get("fact_check_unverified") or 0) == 0
        )
        item_blocked_reasons = row.get("blocked_reasons")
        item_blocked_reasons = item_blocked_reasons if isinstance(item_blocked_reasons, list) else []
        image_reasons = row.get("featured_image_gate_reasons")
        image_reasons = image_reasons if isinstance(image_reasons, list) else []
        non_image_reasons = [
            reason
            for reason in item_blocked_reasons
            if not any(token in str(reason) for token in ("アイキャッチ", "写真", "画像"))
        ]
        if not quality_ready or non_image_reasons or not image_reasons:
            image_only_blocked = False
        if item_blocked_reasons or image_reasons:
            blocked_reasons.append(
                {
                    "item_index": index,
                    "payload_blocked_reasons": item_blocked_reasons,
                    "featured_image_gate_reasons": image_reasons,
                }
            )

    if all_ready:
        return {
            "status": "generation_ready_for_wordpress",
            "reason": "current manifest batch is ready and previous run is unfinished; resume completion pipeline",
            "articles": article_rows,
            "blocked_reasons": blocked_reasons,
        }
    if image_only_blocked:
        return {
            "status": "needs_image_generation_tool",
            "reason": "current manifest batch only waits for fresh article image sources",
            "articles": article_rows,
            "blocked_reasons": blocked_reasons,
        }
    return {
        "status": "not_resumable",
        "reason": "current manifest batch is blocked by non-image gates",
        "articles": article_rows,
        "blocked_reasons": blocked_reasons,
    }


def resume_batch_quality_gate(expected_count: int, manifest_path: Path) -> dict[str, object]:
    quality_path = GENERATED_DIR / "articles" / "article_batch_quality_latest.json"
    quality = read_json(quality_path, {}) or {}
    if not isinstance(quality, dict) or not quality:
        return {"passed": False, "reason": "article batch quality log is missing", "path": str(quality_path)}
    current = (
        quality_path.exists()
        and manifest_path.exists()
        and quality_path.stat().st_mtime + 120 >= manifest_path.stat().st_mtime
    )
    required_flags = {
        "passed": quality.get("passed") is True,
        "status_ok": quality.get("status") == "ok",
        "article_count": int(quality.get("article_count") or 0) == expected_count,
        "intra_article_repetition_ok": quality.get("intra_article_repetition_ok") is True,
        "title_uniqueness_ok": quality.get("title_uniqueness_ok") is True,
        "title_pattern_diversity_ok": quality.get("title_pattern_diversity_ok") is True,
        "structure_pattern_diversity_ok": quality.get("structure_pattern_diversity_ok") is True,
        "image_backgrounds_unique": quality.get("image_backgrounds_unique") is True,
        "current_for_manifest": current,
    }
    return {
        "passed": all(required_flags.values()),
        "path": "03_generated/articles/article_batch_quality_latest.json",
        "checks": required_flags,
        "actual": {
            "status": quality.get("status"),
            "passed": quality.get("passed"),
            "article_count": quality.get("article_count"),
        },
    }


def resume_article_summary(index: int, payload: dict[str, object]) -> dict[str, object | None]:
    wordpress = as_dict(payload.get("wordpress"))
    category = as_dict(payload.get("category_assignment"))
    source = as_dict(payload.get("source"))
    quality = as_dict(payload.get("quality"))
    featured = as_dict(payload.get("featured_image"))
    image_plan_path = GENERATED_DIR / "images" / f"featured_image_plan_item_{index}.json"
    image_plan = read_json(image_plan_path, {}) or {}
    base_image = as_dict(image_plan.get("base_image"))
    image_path = PROJECT_ROOT / str(image_plan.get("output_path") or "")
    image_exists = image_path.exists() and image_path.is_file() and image_path.stat().st_size > 0
    image_reasons = featured_image_gate_reasons(image_plan, image_exists=image_exists)
    return {
        "item_index": index,
        "source_pdf_name": source.get("pdf_name"),
        "source_section_group": source.get("section_group"),
        "source_topic_title": source.get("topic_title"),
        "source_topic_key": source.get("topic_key"),
        "source_labels": source.get("labels"),
        "source_date_mentions": source.get("date_mentions"),
        "source_excerpt": compact_text(source.get("excerpt")),
        "source_nearest_article_title": source.get("nearest_article_title"),
        "source_nearest_article_url": source.get("nearest_article_url"),
        "source_nearest_similarity": source.get("nearest_similarity"),
        "article_title": wordpress.get("title"),
        "wordpress_payload_ready_to_send": payload.get("ready_to_send"),
        "wordpress_payload_status": wordpress.get("status"),
        "wordpress_scheduled_date": wordpress.get("date"),
        "wordpress_category": category.get("name"),
        "wordpress_category_id": category.get("id"),
        "draft_quality_passed": quality.get("draft_quality_passed"),
        "publication_ready": quality.get("publication_ready"),
        "fact_check_unverified": quality.get("fact_check_unverified"),
        "publication_gate": quality.get("publication_gate"),
        "featured_image_quality_ready": featured.get("wordpress_ready") and not image_reasons,
        "featured_image_base_status": base_image.get("status") or featured.get("base_status"),
        "featured_image_photo_source_exists": base_image.get("photo_source_exists") or featured.get("photo_source_exists"),
        "featured_image_source_path": base_image.get("source_path"),
        "featured_image_plan_path": f"03_generated/images/featured_image_plan_item_{index}.json",
        "featured_image_prompt": image_plan.get("prompt"),
        "featured_image_gate_reasons": image_reasons,
        "blocked_reasons": payload.get("blocked_reasons"),
    }


def output_paths() -> dict[str, str]:
    return {
        "weekly_log": "07_logs/weekly_latest.json",
        "latest_run": "07_logs/latest_run.json",
        "initial_report": "02_analysis/seo/initial_analysis_report.md",
        "ga_content_insights": "02_analysis/seo/ga_content_insights.md",
        "posted_article_theme_report": "02_analysis/cannibalization/posted_articles_theme_report.md",
        "topic_selection_report": "02_analysis/topic-selection/topic_selection_report.md",
        "article_batch": "03_generated/articles/article_batch_latest.md",
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
        "git_hygiene": "07_logs/git_hygiene_latest.md",
        "notification": "07_logs/notifications/latest_notification.json",
        "external_preflight": "04_wordpress/external_preflight_latest.md",
    }


def main() -> int:
    with weekly_run_lock() as lock_result:
        if lock_result.get("status") != "acquired":
            payload = build_concurrent_run_payload(lock_result)
            write_weekly_log(payload)
            try:
                payload["notification"] = send_run_notification(payload)
            except Exception as exc:
                payload["notification"] = {"status": "error", "message": str(exc)}
            write_weekly_log(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return exit_code_for_payload(payload)
        return run_main_locked()


def exit_code_for_payload(payload: dict[str, object]) -> int:
    """Return non-zero for incomplete handoffs so automation does not treat them as done."""
    status = str(payload.get("status") or "")
    if status in {"ok", "blocked_all_newsletter_issues_completed", "blocked_concurrent_run"}:
        return 0
    if status in {"needs_image_generation_tool", "needs_drive_upload_plugin"}:
        return 2
    return 1


def run_main_locked() -> int:
    started_at = datetime.now().isoformat(timespec="seconds")
    retry_policy = load_retry_policy()
    max_attempts = int(retry_policy.get("max_attempts") or 3)
    retry_delay = int(retry_policy.get("retry_delay_seconds") or 60)
    attempt_logs: list[dict[str, object]] = []
    final_payload: dict[str, object]

    try:
        preflight = run_external_preflight(check_drive=True, check_smtp_login=True)
    except Exception as exc:
        preflight = {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    if preflight.get("status") != "ok":
        final_payload = build_preflight_failure_payload(started_at, preflight)
        write_weekly_log(final_payload)
        try:
            notification_result = send_run_notification(final_payload)
            final_payload["notification"] = notification_result
            write_weekly_log(final_payload)
        except Exception as exc:
            final_payload["notification"] = {"status": "error", "message": str(exc)}
            write_weekly_log(final_payload)
        print(json.dumps(final_payload, ensure_ascii=False, indent=2))
        return exit_code_for_payload(final_payload)

    partial_issues = detect_partial_draft_issues()
    resume_payload = build_existing_artifact_resume_payload(started_at, partial_issues)
    if resume_payload:
        final_payload = resume_payload
        write_weekly_log(final_payload)
        if final_payload.get("status") == "generation_ready_for_wordpress":
            final_payload = run_external_completion_pipeline(final_payload)
            write_weekly_log(final_payload)
        elif final_payload.get("status") == "needs_image_generation_tool":
            final_payload = defer_external_image_generation_payload(final_payload)
            write_weekly_log(final_payload)
        print(json.dumps(final_payload, ensure_ascii=False, indent=2))
        return exit_code_for_payload(final_payload)

    if partial_issues:
        final_payload = build_partial_draft_issue_payload(started_at, partial_issues)
        write_weekly_log(final_payload)
        try:
            notification_result = send_run_notification(final_payload)
            final_payload["notification"] = notification_result
            write_weekly_log(final_payload)
        except Exception as exc:
            final_payload["notification"] = {"status": "error", "message": str(exc)}
            write_weekly_log(final_payload)
        print(json.dumps(final_payload, ensure_ascii=False, indent=2))
        return exit_code_for_payload(final_payload)

    for attempt in range(1, max_attempts + 1):
        try:
            results = run()
            final_payload = build_success_payload(started_at, results, attempt_logs)
            generation_status = str(final_payload.get("status") or "")
            if should_retry_generation_status(generation_status) and attempt < max_attempts:
                attempt_logs.append(
                    {
                        "attempt": attempt,
                        "status": "retryable_generation_gate_failed",
                        "generation_status": generation_status,
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "article_batch_quality": final_payload.get("article_batch_quality"),
                        "articles": retry_summary(final_payload),
                    }
                )
                time.sleep(retry_delay)
                continue
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "status": "ok" if not should_retry_generation_status(generation_status) else "blocked",
                    "generation_status": generation_status,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "article_batch_quality": final_payload.get("article_batch_quality"),
                    "articles": retry_summary(final_payload),
                }
            )
            final_payload = build_success_payload(started_at, results, attempt_logs)
            break
        except Exception as exc:
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "status": "error",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            if attempt < max_attempts:
                time.sleep(retry_delay)
    else:
        final_payload = build_failure_payload(started_at, attempt_logs)

    write_weekly_log(final_payload)
    if final_payload.get("status") == "generation_ready_for_wordpress":
        final_payload = run_external_completion_pipeline(final_payload)
        write_weekly_log(final_payload)
    elif final_payload.get("status") == "needs_image_generation_tool":
        final_payload = defer_external_image_generation_payload(final_payload)
        write_weekly_log(final_payload)
    elif should_send_generation_stage_notification(final_payload):
        try:
            notification_result = send_run_notification(final_payload)
            final_payload["notification"] = notification_result
            write_weekly_log(final_payload)
        except Exception as exc:
            final_payload["notification"] = {"status": "error", "message": str(exc)}
            write_weekly_log(final_payload)
    else:
        try:
            notification_result = send_run_notification(final_payload)
            final_payload["notification"] = notification_result
        except Exception as exc:
            final_payload["notification"] = {"status": "error", "message": str(exc)}
        write_weekly_log(final_payload)

    print(json.dumps(final_payload, ensure_ascii=False, indent=2))
    return exit_code_for_payload(final_payload)


def defer_external_image_generation_payload(payload: dict[str, object]) -> dict[str, object]:
    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["notification"] = {
        "status": "deferred",
        "reason": "最終通知は画像生成、再構築、WordPress検証、Drive保存の後に送信する。",
    }
    payload["next_action"] = (
        "Codex画像生成ツールで、各記事の featured_image_source_path に新規写真背景を保存してください。"
        "その後 06_automation/continue_after_external_image_sources.py を実行してください。"
        "この続行スクリプトが再構築、WordPress保存、検証、Drive保存、最終通知まで進めます。"
    )
    payload["image_generation_required_items"] = [
        {
            "item_index": article.get("item_index"),
            "article_title": article.get("article_title"),
            "source_pdf_name": article.get("source_pdf_name"),
            "source_section_group": article.get("source_section_group"),
            "source_topic_title": article.get("source_topic_title"),
            "featured_image_source_path": article.get("featured_image_source_path"),
            "featured_image_plan_path": article.get("featured_image_plan_path"),
            "featured_image_prompt": article.get("featured_image_prompt"),
        }
        for article in payload.get("articles", [])
        if isinstance(article, dict)
    ]
    return payload


@contextmanager
def weekly_run_lock() -> Iterator[dict[str, object]]:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOGS_DIR / "run_weekly_automation.lock"
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield {
                    "status": "locked",
                    "lock_path": str(lock_path),
                    "message": "別の自動実行が進行中のため、この実行は二重実行防止でスキップしました。",
                }
                return
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            )
        )
        lock_file.flush()
        yield {"status": "acquired", "lock_path": str(lock_path)}
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        lock_file.close()


def build_concurrent_run_payload(lock_result: dict[str, object]) -> dict[str, object]:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "status": "blocked_concurrent_run",
        "run_key": now,
        "started_at": now,
        "finished_at": now,
        "attempts": 0,
        "attempt_logs": [],
        "error": lock_result.get("message"),
        "lock": lock_result,
        "outputs": output_paths(),
    }


def should_send_generation_stage_notification(payload: dict[str, object]) -> bool:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    notification = settings.get("notification", {}) if isinstance(settings.get("notification"), dict) else {}
    return notification.get("send_generation_stage_notifications") is True


def run_external_completion_pipeline(payload: dict[str, object]) -> dict[str, object]:
    """Run WordPress, verification, Drive upload, and final notification after generation gates pass."""
    started_at = datetime.now().isoformat(timespec="seconds")
    pipeline: dict[str, object] = {
        "status": "not_started",
        "started_at": started_at,
        "steps": [],
    }
    payload["completion_pipeline"] = pipeline

    publish = run_python_step_with_retries(
        "wordpress_publish",
        ["06_automation/run_wordpress_publish.py", "--all", "--execute"],
        success_payload_statuses={"created", "already_created"},
        terminal_payload_statuses={"state_payload_mismatch", "payload_count_mismatch", "no_payloads"},
        extra_env={"KSRFP_ALLOW_WORDPRESS_WRITE": "1"},
    )
    pipeline["steps"].append(publish)
    if publish.get("returncode") != 0 or publish.get("payload_status") not in {"created", "already_created"}:
        return finalize_pipeline_payload(payload, pipeline, "partial", "WordPress下書き保存に失敗または未完了です。")

    reconcile = run_python_step_with_retries(
        "wordpress_state_reconcile",
        ["06_automation/reconcile_wordpress_state_from_publish_log.py"],
        success_payload_statuses={"ok"},
        terminal_payload_statuses={"stale_publish_log", "publish_not_successful"},
    )
    pipeline["steps"].append(reconcile)
    if reconcile.get("returncode") != 0 or reconcile.get("payload_status") != "ok":
        return finalize_pipeline_payload(payload, pipeline, "partial", "WordPress下書き保存後の状態履歴補修がOKではありません。")

    verify = run_python_step_with_retries(
        "wordpress_verify_batch",
        ["06_automation/run_wordpress_verify_batch.py"],
        success_payload_statuses={"ok"},
    )
    pipeline["steps"].append(verify)
    if verify.get("returncode") != 0 or verify.get("payload_status") != "ok":
        return finalize_pipeline_payload(payload, pipeline, "partial", "WordPress読み返し検証がOKではありません。")

    drive = run_python_step_with_retries(
        "review_text_drive_upload",
        ["06_automation/run_review_text_batch_upload.py"],
        success_payload_statuses={"ok"},
        terminal_payload_statuses={"blocked_wordpress_not_verified", "blocked_wordpress_verification_stale"},
        terminal_predicate=drive_requires_plugin_upload,
    )
    pipeline["steps"].append(drive)
    if drive_requires_plugin_upload(drive):
        return defer_pipeline_payload(
            payload,
            pipeline,
            "needs_drive_upload_plugin",
            (
                "ローカルDrive APIトークンがないため、Codex Google Driveプラグインで確認用テキスト保存を続行してください。"
                "保存後、06_automation/record_drive_plugin_uploads.py に `--drive-upload 'ファイル名=Drive URL'` を3件分渡してURLを記録し、"
                "その後 06_automation/send_manual_full_test_notification.py を実行して最終通知を1通だけ送信してください。"
            ),
        )
    if drive.get("returncode") != 0 or drive.get("payload_status") != "ok":
        return finalize_pipeline_payload(payload, pipeline, "partial", "Google Drive確認用テキスト保存がOKではありません。")

    git_hygiene = run_python_step_with_retries(
        "git_hygiene",
        ["06_automation/run_git_hygiene.py"],
        success_payload_statuses={"ok"},
    )
    pipeline["steps"].append(git_hygiene)
    if git_hygiene.get("returncode") != 0 or git_hygiene.get("payload_status") != "ok":
        return finalize_pipeline_payload(payload, pipeline, "partial", "実行結果のGit衛生チェックがOKではありません。")

    notification = run_python_step_with_retries(
        "final_notification",
        ["06_automation/send_manual_full_test_notification.py"],
        success_payload_statuses={"ok", "blocked_all_newsletter_issues_completed"},
        terminal_payload_statuses={"partial"},
    )
    pipeline["steps"].append(notification)
    notification_payload = as_dict(notification.get("payload"))
    notification_result = as_dict(notification_payload.get("notification"))
    if notification_result.get("status") in {"sent", "already_sent"}:
        notification_payload["completion_pipeline"] = pipeline
        return notification_payload
    final_status = "ok" if notification.get("returncode") == 0 and notification.get("payload_status") == "ok" else "partial"
    message = None if final_status == "ok" else "最終通知メール送信がOKではありません。"
    return finalize_pipeline_payload(payload, pipeline, final_status, message)


def run_python_step_with_retries(
    name: str,
    args: list[str],
    success_payload_statuses: set[str],
    extra_env: dict[str, str] | None = None,
    terminal_payload_statuses: set[str] | None = None,
    terminal_predicate: Callable[[dict[str, object]], bool] | None = None,
) -> dict[str, object]:
    retry_policy = load_completion_retry_policy()
    try:
        max_attempts = max(1, int(retry_policy.get("max_attempts") or 3))
    except (TypeError, ValueError):
        max_attempts = 3
    try:
        retry_delay = max(0, int(retry_policy.get("retry_delay_seconds") or 60))
    except (TypeError, ValueError):
        retry_delay = 60
    terminal_payload_statuses = terminal_payload_statuses or set()
    attempts: list[dict[str, object]] = []
    last_step: dict[str, object] = {}
    for attempt in range(1, max_attempts + 1):
        step = run_python_step(name, args, extra_env=extra_env)
        step["attempt"] = attempt
        attempts.append(step)
        last_step = step
        payload_status = str(step.get("payload_status") or "")
        terminal = payload_status in terminal_payload_statuses
        if terminal_predicate is not None:
            terminal = terminal or bool(terminal_predicate(step))
        if step.get("returncode") == 0 and payload_status in success_payload_statuses:
            break
        if terminal or attempt >= max_attempts:
            break
        time.sleep(retry_delay)
    last_step = dict(last_step)
    last_step["attempt_count"] = len(attempts)
    last_step["attempts"] = attempts
    return last_step


def run_python_step(
    name: str,
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> dict[str, object]:
    started_at = datetime.now().isoformat(timespec="seconds")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    command = [sys.executable, *args]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=900,
        check=False,
    )
    parsed = parse_json_stdout(completed.stdout)
    return {
        "name": name,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "command": " ".join(args),
        "returncode": completed.returncode,
        "payload_status": parsed.get("status") if isinstance(parsed, dict) else None,
        "payload": parsed,
        "stdout_tail": completed.stdout[-3000:],
        "stderr_tail": completed.stderr[-3000:],
    }


def parse_json_stdout(stdout: str) -> dict[str, object]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def drive_requires_plugin_upload(step: dict[str, object]) -> bool:
    payload = step.get("payload")
    if not isinstance(payload, dict):
        return False
    result = payload.get("result")
    if not isinstance(result, dict):
        return False
    items = result.get("items")
    if not isinstance(items, list):
        return False
    return bool(items) and all(
        isinstance(item, dict) and item.get("status") == "auth_required"
        for item in items
    )


def defer_pipeline_payload(
    payload: dict[str, object],
    pipeline: dict[str, object],
    status: str,
    message: str,
) -> dict[str, object]:
    pipeline["status"] = status
    pipeline["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["status"] = status
    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["next_action"] = message
    payload["notification"] = {
        "status": "deferred",
        "reason": "最終通知はDrive保存と最終検証の後に送信する。",
    }
    return payload


def finalize_pipeline_payload(
    payload: dict[str, object],
    pipeline: dict[str, object],
    status: str,
    message: str | None,
) -> dict[str, object]:
    pipeline["status"] = status
    pipeline["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["status"] = status
    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if message:
        payload["error"] = message
        try:
            notification_result = send_run_notification(payload)
            payload["notification"] = notification_result
        except Exception as exc:
            payload["notification"] = {"status": "error", "message": str(exc)}
    else:
        latest = read_json(LOGS_DIR / "weekly_latest.json", {}) or {}
        if isinstance(latest, dict) and latest.get("status") in {"ok", "partial"}:
            latest["completion_pipeline"] = pipeline
            return latest
        payload["notification"] = {"status": "sent_or_already_sent_by_final_notification_step"}
    return payload


def should_retry_generation_status(status: str) -> bool:
    return status in {
        "blocked_before_wordpress",
        "blocked_until_verified",
        "blocked_batch_quality",
        "blocked_insufficient_articles",
    }


def retry_summary(payload: dict[str, object]) -> list[dict[str, object | None]]:
    articles = payload.get("articles")
    if not isinstance(articles, list):
        return []
    rows: list[dict[str, object | None]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        rows.append(
            {
                "item_index": article.get("item_index"),
                "title": article.get("article_title"),
                "ready_to_send": article.get("wordpress_payload_ready_to_send"),
                "quality": article.get("draft_quality_passed"),
                "fact_unverified": article.get("fact_check_unverified"),
                "review_text_upload_status": article.get("review_text_upload_status"),
                "featured_image_ready": article.get("featured_image_quality_ready"),
            }
        )
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
