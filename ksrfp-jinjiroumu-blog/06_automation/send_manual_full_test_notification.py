#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.artifact_fingerprint import (  # noqa: E402
    manifest_fingerprint,
    payload_matches_current_manifest,
)
from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json  # noqa: E402
from ksrfp_jinjiroumu_blog.notification import send_run_notification  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import LOGS_DIR, WORDPRESS_DIR  # noqa: E402


def compact_text(value: object, limit: int = 260) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def parse_drive_uploads(values: list[str]) -> dict[str, dict[str, str]]:
    uploads: dict[str, dict[str, str]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --drive-upload value: {value}")
        file_name, url = value.split("=", 1)
        file_name = file_name.strip()
        url = url.strip()
        if not file_name or not url:
            raise ValueError(f"Invalid --drive-upload value: {value}")
        uploads[file_name] = {
            "status": "uploaded",
            "file_name": file_name,
            "url": url,
            "file_id": drive_id_from_url(url),
        }
    return uploads


def load_drive_uploads_from_review_texts() -> dict[str, dict[str, str]]:
    uploads: dict[str, dict[str, str]] = {}
    for path in current_review_text_paths():
        payload = read_json(path, {}) or {}
        file_name = str(payload.get("file_name") or "")
        if not file_name:
            continue
        upload = payload.get("upload", {}) if isinstance(payload.get("upload"), dict) else {}
        url = upload.get("webViewLink") or upload.get("url") or upload.get("web_view_link")
        uploads[file_name] = {
            "status": str(upload.get("status") or payload.get("status") or "unknown"),
            "file_name": file_name,
            "url": str(url or ""),
            "file_id": str(upload.get("id") or upload.get("file_id") or drive_id_from_url(str(url or "")) or ""),
        }
    return uploads


def current_review_text_paths() -> list[Path]:
    manifest = read_json(PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json", {}) or {}
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    review_dir = PROJECT_ROOT / "03_generated" / "review-texts"
    if items:
        return [review_dir / f"review_text_item_{index}.json" for index in range(1, len(items) + 1)]
    return sorted(review_dir.glob("review_text_item_*.json"), key=item_index_from_path)


def item_index_from_path(path: Path) -> int:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def drive_id_from_url(url: str) -> str | None:
    marker = "/d/"
    if marker not in url:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        ids = query.get("id") or query.get("file_id")
        return ids[0] if ids else None
    return url.split(marker, 1)[1].split("/", 1)[0]


def load_publish_by_index() -> dict[int, dict[str, Any]]:
    if not log_is_current(LOGS_DIR / "wordpress_publish_latest.json"):
        return {}
    publish = read_json(LOGS_DIR / "wordpress_publish_latest.json", {}) or {}
    result = publish.get("result", {}) if isinstance(publish.get("result"), dict) else {}
    items = result.get("items", []) if isinstance(result.get("items"), list) else []
    return {
        int(item.get("item_index")): item
        for item in items
        if isinstance(item, dict) and item.get("item_index") is not None
    }


def load_featured_image_refresh_by_index() -> dict[int, dict[str, Any]]:
    if not log_is_current(LOGS_DIR / "wordpress_featured_image_refresh_latest.json"):
        return {}
    refresh = read_json(LOGS_DIR / "wordpress_featured_image_refresh_latest.json", {}) or {}
    items = refresh.get("items", []) if isinstance(refresh.get("items"), list) else []
    return {
        int(item.get("item_index")): item
        for item in items
        if isinstance(item, dict) and item.get("item_index") is not None
    }


def log_is_current(log_path: Path, reference_path: Path | None = None, slack_seconds: int = 2) -> bool:
    reference = reference_path or PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json"
    if not log_path.exists() or not reference.exists():
        return False
    payload = read_json(log_path, {}) or {}
    return (
        log_path.stat().st_mtime + slack_seconds >= reference.stat().st_mtime
        and payload_matches_current_manifest(payload)
    )


def build_articles(drive_uploads: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    payloads = read_json(PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json", {}) or {}
    items = payloads.get("items", []) if isinstance(payloads.get("items"), list) else []
    publish_by_index = load_publish_by_index()
    refresh_by_index = load_featured_image_refresh_by_index()
    articles: list[dict[str, Any]] = []
    for item_index, payload in enumerate(items, start=1):
        if not isinstance(payload, dict):
            continue
        wordpress = payload.get("wordpress", {}) if isinstance(payload.get("wordpress"), dict) else {}
        category = payload.get("category_assignment", {}) if isinstance(payload.get("category_assignment"), dict) else {}
        source = payload.get("source", {}) if isinstance(payload.get("source"), dict) else {}
        quality = payload.get("quality", {}) if isinstance(payload.get("quality"), dict) else {}
        featured_image = payload.get("featured_image", {}) if isinstance(payload.get("featured_image"), dict) else {}
        publish_item = publish_by_index.get(item_index, {})
        publish_result = publish_item.get("result", {}) if isinstance(publish_item.get("result"), dict) else {}
        post = publish_result.get("post", {}) if isinstance(publish_result.get("post"), dict) else {}
        media = publish_result.get("media", {}) if isinstance(publish_result.get("media"), dict) else {}
        refresh_item = refresh_by_index.get(item_index, {})
        refresh_media = refresh_item.get("media", {}) if isinstance(refresh_item.get("media"), dict) else {}
        refresh_post = refresh_item.get("post", {}) if isinstance(refresh_item.get("post"), dict) else {}
        current_post_id = post.get("id")
        refresh_post_id = refresh_item.get("post_id") or refresh_post.get("id")
        refresh_matches_current_post = (
            current_post_id is not None
            and refresh_post_id is not None
            and str(current_post_id) == str(refresh_post_id)
        )
        title = str(wordpress.get("title") or "")
        review_file = f"{str(wordpress.get('date') or '')[2:4]}{str(wordpress.get('date') or '')[5:7]}{str(wordpress.get('date') or '')[8:10]} {title}.txt"
        upload = drive_uploads.get(review_file, {})
        articles.append(
            {
                "item_index": item_index,
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
                "article_title": title,
                "wordpress_payload_ready_to_send": payload.get("ready_to_send"),
                "wordpress_payload_status": wordpress.get("status"),
                "wordpress_scheduled_date": wordpress.get("date"),
                "wordpress_category": category.get("name"),
                "wordpress_category_id": category.get("id"),
                "wordpress_post_id": post.get("id") or refresh_item.get("post_id") or refresh_post.get("id"),
                "wordpress_url": post.get("link") or refresh_post.get("link"),
                "featured_image_url": (
                    (refresh_media.get("source_url") if refresh_matches_current_post else None)
                    or (refresh_media.get("link") if refresh_matches_current_post else None)
                    or media.get("source_url")
                    or media.get("link")
                ),
                "draft_quality_passed": quality.get("draft_quality_passed"),
                "publication_ready": quality.get("publication_ready"),
                "fact_check_unverified": quality.get("fact_check_unverified"),
                "publication_gate": quality.get("publication_gate"),
                "review_text_file": review_file,
                "review_text_upload_status": upload.get("status") or "not_recorded",
                "review_text_drive_url": upload.get("url"),
                "featured_image_quality_ready": featured_image.get("wordpress_ready"),
                "featured_image_base_status": featured_image.get("base_status"),
                "featured_image_photo_source_exists": featured_image.get("photo_source_exists"),
            }
        )
    return articles


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    generation_log = read_json(LOGS_DIR / "weekly_latest.json", {}) or {}
    latest_run = read_json(LOGS_DIR / "latest_run.json", {}) or {}
    publish_log = read_json(LOGS_DIR / "wordpress_publish_latest.json", {}) or {}
    publish_result = publish_log.get("result", {}) if isinstance(publish_log.get("result"), dict) else {}
    publish_run_key = publish_result.get("run_key") or publish_log.get("run_key")
    verification_path = WORDPRESS_DIR / "wordpress_batch_verification_latest.json"
    verification_current = log_is_current(verification_path)
    verification = read_json(verification_path, {}) if verification_current else {}
    drive_uploads = load_drive_uploads_from_review_texts()
    drive_uploads.update(parse_drive_uploads(args.drive_upload or []))
    articles = build_articles(drive_uploads)
    first_article = articles[0] if articles else {}
    all_payload_ready = bool(articles) and all(bool(article.get("wordpress_payload_ready_to_send")) for article in articles)
    fact_check_unverified = sum(int(article.get("fact_check_unverified") or 0) for article in articles)
    all_drive_uploaded = bool(articles) and all(article.get("review_text_upload_status") == "uploaded" for article in articles)
    all_wordpress_saved = bool(articles) and all(bool(article.get("wordpress_post_id")) for article in articles)
    verification_ok = verification_current and verification.get("status") == "ok"
    status = "ok" if (
        len(articles) == 3
        and all_payload_ready
        and fact_check_unverified == 0
        and all_drive_uploaded
        and all_wordpress_saved
        and verification_ok
    ) else "partial"
    if not articles and generation_log.get("status") == "blocked_all_newsletter_issues_completed":
        status = "blocked_all_newsletter_issues_completed"
    payload: dict[str, Any] = {
        "status": status,
        "run_key": generation_log.get("run_key") or publish_run_key or latest_run.get("run_key") or latest_run.get("started_at") or args.started_at,
        "started_at": generation_log.get("started_at") or publish_run_key or latest_run.get("started_at") or args.started_at or datetime.now().isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "attempts": 1,
        "attempt_logs": [{"attempt": 1, "status": "ok", "finished_at": datetime.now().isoformat(timespec="seconds")}],
        "generated_article_count": len(articles),
        "articles": articles,
        "newsletter_issue_selection": generation_log.get("newsletter_issue_selection"),
        "newsletter_available_pdfs": generation_log.get("newsletter_available_pdfs"),
        "fact_check_unverified": fact_check_unverified,
        "publication_gate": "draft_saved_for_review"
        if status == "ok"
        else "all_newsletter_issues_completed"
        if status == "blocked_all_newsletter_issues_completed"
        else "blocked_until_final_verification",
        "wordpress_payload_ready_to_send": all_payload_ready,
        "wordpress_payload_status": "draft",
        "wordpress_scheduled_date": first_article.get("wordpress_scheduled_date"),
        "wordpress_category": first_article.get("wordpress_category"),
        "wordpress_category_id": first_article.get("wordpress_category_id"),
        "wordpress_tags": [],
        "arkhe_css_editor_set": verification_ok,
        "drive_status": "ok" if all_drive_uploaded else "needs_drive_upload",
        "wordpress_status": verification.get("status") if verification_current else "not_current",
        "error": "全ての人事労務だより号が記事作成済みです。未作成の号が見つからなかったため、記事作成を停止しました。"
        if status == "blocked_all_newsletter_issues_completed"
        else None,
        "outputs": {
            "latest_run": "07_logs/latest_run.json",
            "article_batch": "03_generated/articles/article_batch_latest.md",
            "review_text": "03_generated/review-texts/",
            "wordpress_payloads": "03_generated/wordpress-payloads/post_payloads_latest.json",
            "wordpress_publish": "07_logs/wordpress_publish_latest.json",
            "wordpress_verification": "04_wordpress/wordpress_batch_verification_latest.md",
            "notification": "07_logs/notifications/latest_notification.json",
        },
    }
    write_json(LOGS_DIR / "review_text_drive_manual_latest.json", {"status": "ok", "items": list(drive_uploads.values())})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Send manual full-run notification using the standard notifier.")
    parser.add_argument("--started-at", default=None)
    parser.add_argument(
        "--drive-upload",
        action="append",
        default=[],
        help="Review text upload mapping in the form file_name=url. Repeat for each file.",
    )
    args = parser.parse_args()
    payload = build_payload(args)
    if payload.get("status") != "blocked_all_newsletter_issues_completed":
        state_reconcile = run_local_step("wordpress_state_reconcile", ["06_automation/reconcile_wordpress_state_from_publish_log.py"])
        final_contract = run_local_step(
            "final_contract_pre_notification",
            ["06_automation/verify_final_run_contract.py", "--allow-missing-notification"],
        )
        payload["wordpress_state_reconcile"] = state_reconcile
        payload["final_contract"] = final_contract
        contract_payload = final_contract.get("payload") if isinstance(final_contract.get("payload"), dict) else {}
        if final_contract.get("returncode") != 0 or contract_payload.get("status") != "ok":
            payload["status"] = "partial"
            payload["publication_gate"] = "blocked_until_final_contract_passes"
            payload["error"] = "最終契約テストがOKではないため、成功扱いにしていません。"
        else:
            payload["status"] = "ok"
            payload["publication_gate"] = "draft_saved_for_review"
        git_hygiene = run_local_step("git_hygiene", ["06_automation/run_git_hygiene.py"])
        payload["git_hygiene"] = git_hygiene
        hygiene_payload = git_hygiene.get("payload") if isinstance(git_hygiene.get("payload"), dict) else {}
        if git_hygiene.get("returncode") != 0 or hygiene_payload.get("status") != "ok":
            payload["status"] = "partial"
            payload["publication_gate"] = "blocked_until_git_hygiene_passes"
            payload["error"] = "Git衛生チェックがOKではないため、成功扱いにしていません。"
    write_json(LOGS_DIR / "manual_full_test_latest.json", payload)
    write_json(LOGS_DIR / "automation_final_latest.json", payload)
    write_json(LOGS_DIR / "weekly_latest.json", payload)
    notification = send_run_notification(payload)
    payload["notification"] = notification
    if payload.get("status") == "ok":
        post_notification_contract = run_local_step(
            "final_contract_post_notification",
            ["06_automation/verify_final_run_contract.py"],
        )
        payload["post_notification_final_contract"] = post_notification_contract
        contract_payload = post_notification_contract.get("payload") if isinstance(post_notification_contract.get("payload"), dict) else {}
        if post_notification_contract.get("returncode") != 0 or contract_payload.get("status") != "ok":
            payload["status"] = "partial"
            payload["publication_gate"] = "blocked_until_final_contract_passes"
            payload["error"] = "通知後の最終契約テストがOKではありません。"
    write_json(LOGS_DIR / "manual_full_test_latest.json", payload)
    write_json(LOGS_DIR / "automation_final_latest.json", payload)
    write_json(LOGS_DIR / "weekly_latest.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    notification_sent = notification.get("status") in {"sent", "already_sent"}
    terminal_status_ok = payload.get("status") in {"ok", "blocked_all_newsletter_issues_completed"}
    return 0 if notification_sent and terminal_status_ok else 1


def run_local_step(name: str, args: list[str]) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
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


def parse_json_stdout(stdout: str) -> dict[str, Any]:
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


if __name__ == "__main__":
    raise SystemExit(main())
