from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from .io_utils import read_json, write_json, write_markdown
from .paths import CONFIG_DIR, STATE_DIR


STATE_VERSION = 1
PDF_COMPLETED_STATUSES = {
    "draft_saved_for_review",
    "wordpress_drafts_created",
    "articles_created",
    "completed",
    "completed_for_blog",
}


def stable_key(*parts: object) -> str:
    source = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def default_state() -> dict[str, Any]:
    return {
        "processed_pdfs": {
            "version": STATE_VERSION,
            "items": [],
            "note": "Google Driveから取得したPDFの分析状況と、号単位の記事作成完了状況を記録する。",
        },
        "topic_history": {
            "version": STATE_VERSION,
            "items": [],
            "note": "記事化済み・下書き投稿済みのテーマを記録し、重複生成を避ける。",
        },
        "fact_check_registry": {
            "version": STATE_VERSION,
            "items": [],
            "note": "一次情報確認済みの項目、確認URL、確認日、根拠メモを記録する。",
        },
        "automation_status": {
            "version": STATE_VERSION,
            "last_run_at": None,
            "last_status": "not_run",
            "safe_to_publish": False,
            "publication_ready": False,
            "last_selected_topic_key": None,
            "last_selected_pdf": None,
            "last_selected_topic": None,
            "last_error": None,
        },
        "scheduled_posts": {
            "version": STATE_VERSION,
            "items": [],
            "note": "WordPress下書き・予約投稿の日時、投稿ID、テーマを記録し、同じテーマの重複を避ける。",
        },
    }


def state_paths() -> dict[str, Any]:
    return {
        "processed_pdfs": STATE_DIR / "processed_pdfs.json",
        "topic_history": STATE_DIR / "topic_history.json",
        "fact_check_registry": STATE_DIR / "fact_check_registry.json",
        "automation_status": STATE_DIR / "automation_status.json",
        "scheduled_posts": STATE_DIR / "scheduled_posts.json",
        "readme": STATE_DIR / "state_summary.md",
    }


def ensure_state_files() -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    defaults = default_state()
    paths = state_paths()
    state: dict[str, Any] = {}
    for name in ("processed_pdfs", "topic_history", "fact_check_registry", "automation_status", "scheduled_posts"):
        path = paths[name]
        value = read_json(path, defaults[name])
        if value is None:
            value = defaults[name]
        if isinstance(value, dict) and isinstance(defaults.get(name), dict) and defaults[name].get("note"):
            value["note"] = defaults[name]["note"]
        state[name] = value
        write_json(path, value)
    if sync_processed_pdfs_from_scheduled_posts(state):
        write_json(paths["processed_pdfs"], state["processed_pdfs"])
    write_markdown(paths["readme"], render_state_summary(state))
    return state


def topic_key_from_row(row: dict[str, Any]) -> str:
    return stable_key(row.get("pdf_name"), row.get("section_group"), row.get("topic_title"))


def used_topic_keys(topic_history: dict[str, Any]) -> set[str]:
    used_statuses = {"drafted", "scheduled", "posted", "published"}
    return {
        str(item.get("topic_key"))
        for item in topic_history.get("items", [])
        if item.get("status") in used_statuses and item.get("topic_key")
    }


def configured_articles_per_run() -> int:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    try:
        return max(1, int(settings.get("articles_per_run") or 3))
    except (TypeError, ValueError):
        return 3


def is_pdf_issue_completed(item: dict[str, Any], required_count: int | None = None) -> bool:
    required = required_count or configured_articles_per_run()
    status = str(item.get("status") or "")
    if status in PDF_COMPLETED_STATUSES:
        return True
    completed_at = item.get("article_creation_completed_at") or item.get("completed_at")
    post_ids = item.get("wordpress_post_ids")
    post_count = len(post_ids) if isinstance(post_ids, list) else int(item.get("wordpress_post_count") or 0)
    return bool(completed_at and post_count >= required)


def completed_pdf_names(processed_pdfs: dict[str, Any], required_count: int | None = None) -> set[str]:
    return {
        str(item.get("pdf_name"))
        for item in processed_pdfs.get("items", [])
        if item.get("pdf_name") and is_pdf_issue_completed(item, required_count)
    }


def processed_pdf_item(processed_pdfs: dict[str, Any], pdf_name: str) -> dict[str, Any] | None:
    for item in processed_pdfs.get("items", []):
        if item.get("pdf_name") == pdf_name:
            return item
    return None


def sync_processed_pdfs_from_scheduled_posts(state: dict[str, Any]) -> bool:
    scheduled_items = state.get("scheduled_posts", {}).get("items", [])
    if not isinstance(scheduled_items, list):
        return False
    required_count = configured_articles_per_run()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in scheduled_items:
        if not isinstance(item, dict):
            continue
        pdf_name = item.get("pdf_name")
        post_id = item.get("wordpress_post_id")
        status = str(item.get("wordpress_status") or item.get("status") or "")
        if not pdf_name or not post_id or status not in {"draft", "future", "scheduled", "posted", "publish", "published"}:
            continue
        grouped.setdefault(str(pdf_name), []).append(item)

    changed = False
    for pdf_name, items in grouped.items():
        post_ids = list(dict.fromkeys(item.get("wordpress_post_id") for item in items if item.get("wordpress_post_id")))
        if len(post_ids) < required_count:
            continue
        existing = processed_pdf_item(state["processed_pdfs"], pdf_name) or {}
        if (
            is_pdf_issue_completed(existing, required_count)
            and existing.get("publication_gate") == "draft_saved_for_review"
            and int(existing.get("fact_check_unverified") or 0) == 0
        ):
            continue
        created_topics = [
            {
                "topic_key": item.get("topic_key"),
                "section_group": item.get("section_group"),
                "topic_title": item.get("topic_title"),
                "wordpress_post_id": item.get("wordpress_post_id"),
                "wordpress_url": item.get("wordpress_url"),
            }
            for item in items
        ]
        latest_created_at = max((str(item.get("created_at") or "") for item in items), default=datetime.now().isoformat(timespec="seconds"))
        entry = {
            "pdf_name": pdf_name,
            "period_key": period_key(pdf_name),
            "drive_file_id": existing.get("drive_file_id"),
            "status": "draft_saved_for_review",
            "last_processed_at": existing.get("last_processed_at") or latest_created_at,
            "last_article_created_at": latest_created_at,
            "article_creation_completed_at": latest_created_at,
            "required_article_count": required_count,
            "wordpress_post_count": len(post_ids),
            "wordpress_post_ids": post_ids,
            "created_topic_keys": [item.get("topic_key") for item in items if item.get("topic_key")],
            "created_topics": created_topics,
            "selected_topic_key": items[-1].get("topic_key"),
            "selected_topic": items[-1].get("topic_title"),
            "publication_gate": "draft_saved_for_review",
            "fact_check_unverified": 0,
        }
        upsert_state_item(state["processed_pdfs"], "pdf_name", entry)
        changed = True
    return changed


def update_automation_status(results: dict[str, Any]) -> dict[str, Any]:
    state = ensure_state_files()
    article_items = []
    articles = results.get("articles", {}) if isinstance(results.get("articles"), dict) else {}
    for item in articles.get("items", []):
        if isinstance(item, dict):
            article_items.append(item)
    selected = results.get("article_brief", {}).get("selected", {}) if isinstance(results.get("article_brief"), dict) else {}
    quality = results.get("quality_check", {}) if isinstance(results.get("quality_check"), dict) else {}
    fact_check = results.get("fact_check", {}) if isinstance(results.get("fact_check"), dict) else {}
    selected_topics = [
        item.get("selected", {})
        for item in article_items
        if isinstance(item.get("selected"), dict)
    ]
    quality_items = [
        item.get("quality_check", {})
        for item in article_items
        if isinstance(item.get("quality_check"), dict)
    ]
    fact_items = [
        item.get("fact_check", {})
        for item in article_items
        if isinstance(item.get("fact_check"), dict)
    ]
    if selected_topics:
        selected = selected_topics[0]
    if quality_items:
        quality = quality_items[0]
    if fact_items:
        fact_check = fact_items[0]
    status = {
        "version": STATE_VERSION,
        "last_run_at": datetime.now().isoformat(timespec="seconds"),
        "last_status": "ok",
        "generated_article_count": len(article_items) if article_items else 1 if selected else 0,
        "safe_to_publish": all(bool(item.get("passed")) for item in quality_items) if quality_items else bool(quality.get("passed")),
        "publication_ready": all(bool(item.get("publication_ready")) for item in quality_items)
        if quality_items
        else bool(quality.get("publication_ready")),
        "draft_quality_passed": all(bool(item.get("draft_quality_passed")) for item in quality_items)
        if quality_items
        else bool(quality.get("draft_quality_passed")),
        "fact_check_unverified": sum(int(item.get("unverified_count") or 0) for item in fact_items)
        if fact_items
        else int(fact_check.get("unverified_count") or 0),
        "publication_gate": fact_check.get("publication_gate"),
        "last_selected_topic_key": topic_key_from_row(selected) if selected else None,
        "last_selected_pdf": selected.get("pdf_name") if selected else None,
        "last_selected_topic": selected.get("topic_title") if selected else None,
        "selected_topics": [
            {
                "topic_key": topic_key_from_row(topic),
                "pdf_name": topic.get("pdf_name"),
                "section_group": topic.get("section_group"),
                "topic_title": topic.get("topic_title"),
            }
            for topic in selected_topics
        ],
        "last_error": None,
    }
    write_json(state_paths()["automation_status"], status)
    state["automation_status"] = status
    if article_items:
        for item in article_items:
            item_selected = item.get("selected", {}) if isinstance(item.get("selected"), dict) else {}
            item_quality = item.get("quality_check", {}) if isinstance(item.get("quality_check"), dict) else {}
            item_fact_check = item.get("fact_check", {}) if isinstance(item.get("fact_check"), dict) else {}
            record_pdf_and_topic_history(state, results, item_selected, item_quality, item_fact_check)
    else:
        record_pdf_and_topic_history(state, results, selected, quality, fact_check)
    write_markdown(state_paths()["readme"], render_state_summary(state))
    return status


def record_wordpress_scheduled_post(post_payload: dict[str, Any], publish_result: dict[str, Any]) -> dict[str, Any]:
    state = ensure_state_files()
    source = post_payload.get("source", {}) if isinstance(post_payload.get("source"), dict) else {}
    wordpress = post_payload.get("wordpress", {}) if isinstance(post_payload.get("wordpress"), dict) else {}
    schedule = post_payload.get("schedule_plan", {}) if isinstance(post_payload.get("schedule_plan"), dict) else {}
    post = publish_result.get("post", {}) if isinstance(publish_result.get("post"), dict) else {}
    media = publish_result.get("media", {}) if isinstance(publish_result.get("media"), dict) else {}
    featured_image = publish_result.get("featured_image", {}) if isinstance(publish_result.get("featured_image"), dict) else {}
    now = datetime.now().isoformat(timespec="seconds")
    topic_key = stable_key(source.get("pdf_name"), source.get("section_group"), source.get("topic_title"))

    scheduled_entry = {
        "wordpress_post_id": post.get("id"),
        "wordpress_url": post.get("link"),
        "wordpress_status": post.get("status"),
        "scheduled_local": schedule.get("scheduled_local") or wordpress.get("date") or post.get("date"),
        "scheduled_gmt": schedule.get("scheduled_gmt") or wordpress.get("date_gmt"),
        "status": "scheduled" if post.get("status") == "future" else "draft" if post.get("status") == "draft" else post.get("status") or "posted",
        "topic_key": topic_key,
        "pdf_name": source.get("pdf_name"),
        "section_group": source.get("section_group"),
        "topic_title": source.get("topic_title"),
        "title": wordpress.get("title"),
        "category_ids": wordpress.get("categories", []),
        "tags": wordpress.get("tags", []),
        "featured_media_id": media.get("id"),
        "featured_media_reused": bool(media.get("reused_existing_media")),
        "featured_image_path": featured_image.get("path"),
        "featured_image_sha256": featured_image.get("sha256"),
        "image_plan_path": featured_image.get("image_plan_path") or publish_result.get("image_plan_path"),
        "post_payload_path": featured_image.get("post_payload_path") or publish_result.get("post_payload_path"),
        "created_at": now,
    }
    upsert_state_item(state["scheduled_posts"], "wordpress_post_id", scheduled_entry)
    write_json(state_paths()["scheduled_posts"], state["scheduled_posts"])

    topic_entry = {
        "topic_key": topic_key,
        "pdf_name": source.get("pdf_name"),
        "section_group": source.get("section_group"),
        "topic_title": source.get("topic_title"),
        "status": "drafted" if scheduled_entry["status"] == "draft" else scheduled_entry["status"],
        "last_generated_at": now,
        "publication_gate": post_payload.get("quality", {}).get("publication_gate"),
        "fact_check_unverified": int(post_payload.get("quality", {}).get("fact_check_unverified") or 0),
        "wordpress_post_id": post.get("id"),
        "wordpress_url": post.get("link"),
    }
    upsert_state_item(state["topic_history"], "topic_key", topic_entry)
    write_json(state_paths()["topic_history"], state["topic_history"])

    record_pdf_article_creation(state, source, topic_entry, scheduled_entry)
    write_markdown(state_paths()["readme"], render_state_summary(state))
    return scheduled_entry


def record_pdf_article_creation(
    state: dict[str, Any],
    source: dict[str, Any],
    topic_entry: dict[str, Any],
    scheduled_entry: dict[str, Any],
) -> None:
    pdf_name = source.get("pdf_name")
    if not pdf_name:
        return
    now = datetime.now().isoformat(timespec="seconds")
    existing = processed_pdf_item(state["processed_pdfs"], str(pdf_name)) or {}
    post_ids = list(existing.get("wordpress_post_ids") or [])
    post_id = scheduled_entry.get("wordpress_post_id")
    if post_id and post_id not in post_ids:
        post_ids.append(post_id)

    topic_keys = list(existing.get("created_topic_keys") or [])
    topic_key = topic_entry.get("topic_key")
    if topic_key and topic_key not in topic_keys:
        topic_keys.append(topic_key)

    created_topics = list(existing.get("created_topics") or [])
    if topic_key and not any(item.get("topic_key") == topic_key for item in created_topics if isinstance(item, dict)):
        created_topics.append(
            {
                "topic_key": topic_key,
                "section_group": source.get("section_group"),
                "topic_title": source.get("topic_title"),
                "wordpress_post_id": scheduled_entry.get("wordpress_post_id"),
                "wordpress_url": scheduled_entry.get("wordpress_url"),
            }
        )

    required_count = configured_articles_per_run()
    completed = len(post_ids) >= required_count
    if completed:
        for item in state["processed_pdfs"].get("items", []):
            if isinstance(item, dict) and item.get("pdf_name") == pdf_name:
                item.pop("last_failed_at", None)
                item.pop("last_failure_reason", None)
    entry = {
        "pdf_name": pdf_name,
        "period_key": period_key(str(pdf_name or "")),
        "drive_file_id": existing.get("drive_file_id"),
        "status": "draft_saved_for_review" if completed else "partially_drafted",
        "last_processed_at": existing.get("last_processed_at") or now,
        "last_article_created_at": now,
        "article_creation_completed_at": now if completed else existing.get("article_creation_completed_at"),
        "required_article_count": required_count,
        "wordpress_post_count": len(post_ids),
        "wordpress_post_ids": post_ids,
        "created_topic_keys": topic_keys,
        "created_topics": created_topics,
        "selected_topic_key": topic_key,
        "selected_topic": source.get("topic_title"),
        "publication_gate": topic_entry.get("publication_gate"),
        "fact_check_unverified": topic_entry.get("fact_check_unverified"),
    }
    upsert_state_item(state["processed_pdfs"], "pdf_name", entry)
    write_json(state_paths()["processed_pdfs"], state["processed_pdfs"])


def record_pdf_and_topic_history(
    state: dict[str, Any],
    results: dict[str, Any],
    selected: dict[str, Any],
    quality: dict[str, Any],
    fact_check: dict[str, Any],
) -> None:
    if not selected:
        return
    now = datetime.now().isoformat(timespec="seconds")
    topic_key = topic_key_from_row(selected)
    pdf_name = selected.get("pdf_name")
    existing_pdf = processed_pdf_item(state["processed_pdfs"], str(pdf_name)) or {}
    existing_status = str(existing_pdf.get("status") or "")
    existing_post_count = int(existing_pdf.get("wordpress_post_count") or 0)
    status = (
        existing_status
        if existing_status in {"partially_drafted", "draft_saved_for_review"} and existing_post_count > 0
        else "analyzed"
    )
    drive_status = results.get("drive_status", {}) if isinstance(results.get("drive_status"), dict) else {}
    latest_drive_pdf = drive_status.get("latest_drive_pdf") if isinstance(drive_status.get("latest_drive_pdf"), dict) else {}
    processed_pdf_entry = {
        "pdf_name": pdf_name,
        "period_key": period_key(str(pdf_name or "")),
        "drive_file_id": latest_drive_pdf.get("id") if latest_drive_pdf.get("name") == pdf_name else None,
        "status": status,
        "last_processed_at": now,
        "selected_topic_key": topic_key,
        "selected_topic": selected.get("topic_title"),
        "publication_gate": fact_check.get("publication_gate"),
        "fact_check_unverified": int(fact_check.get("unverified_count") or 0),
    }
    upsert_state_item(state["processed_pdfs"], "pdf_name", processed_pdf_entry)
    write_json(state_paths()["processed_pdfs"], state["processed_pdfs"])

    if quality.get("publication_ready"):
        topic_status = "generated_ready_before_wordpress"
    elif quality.get("draft_quality_passed"):
        topic_status = "generated_needs_external_gate"
    else:
        topic_status = "generated_quality_blocked"
    topic_entry = {
        "topic_key": topic_key,
        "pdf_name": pdf_name,
        "section_group": selected.get("section_group"),
        "topic_title": selected.get("topic_title"),
        "status": topic_status,
        "last_generated_at": now,
        "publication_gate": fact_check.get("publication_gate"),
        "fact_check_unverified": int(fact_check.get("unverified_count") or 0),
        "wordpress_post_id": None,
        "wordpress_url": None,
    }
    upsert_state_item(state["topic_history"], "topic_key", topic_entry)
    write_json(state_paths()["topic_history"], state["topic_history"])


def upsert_state_item(collection: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
    items = collection.setdefault("items", [])
    for index, item in enumerate(items):
        if item.get(key) == entry.get(key):
            items[index] = {**item, **entry}
            return
    items.append(entry)


def period_key(name: str) -> str:
    import re

    match = re.search(r"(20\d{2})\.(\d{1,2})", name)
    if not match:
        return "0000-00"
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def render_state_summary(state: dict[str, Any]) -> str:
    processed_pdfs = state.get("processed_pdfs", {}).get("items", [])
    topic_history = state.get("topic_history", {}).get("items", [])
    fact_checks = state.get("fact_check_registry", {}).get("items", [])
    scheduled_posts = state.get("scheduled_posts", {}).get("items", [])
    status = state.get("automation_status", {})
    lines = [
        "# 状態管理サマリー",
        "",
        "## 現在の状態",
        "",
        f"- 最終実行日時: {status.get('last_run_at') or '未実行'}",
        f"- 最終ステータス: {status.get('last_status')}",
        f"- 生成記事数: {status.get('generated_article_count', 0)}",
        f"- 下書き品質: {status.get('draft_quality_passed')}",
        f"- 公開可能: {status.get('publication_ready')}",
        f"- 送信可能: {status.get('safe_to_publish')}",
        f"- 未確認ファクト数: {status.get('fact_check_unverified', 0)}",
        f"- 公開ゲート: {status.get('publication_gate') or '未判定'}",
        f"- 直近テーマ: {status.get('last_selected_topic') or '未選定'}",
        f"- 直近PDF: {status.get('last_selected_pdf') or '未選定'}",
        "",
        "## 今回選定テーマ",
        "",
    ]
    selected_topics = status.get("selected_topics", []) if isinstance(status.get("selected_topics"), list) else []
    if selected_topics:
        for topic in selected_topics:
            lines.append(
                f"- {topic.get('pdf_name')} / {topic.get('section_group')}: {topic.get('topic_title')}"
            )
    else:
        lines.append("- 未選定")
    lines.extend(
        [
            "",
        "## 管理ファイル",
        "",
        "- `08_state/processed_pdfs.json`: 処理済みPDFを管理する。",
        "- `08_state/topic_history.json`: 投稿済み・下書き生成済みテーマを管理する。",
        "- `08_state/fact_check_registry.json`: 一次情報確認済みの根拠を管理する。",
        "- `08_state/automation_status.json`: 直近実行状態と公開ゲートを管理する。",
        "- `08_state/scheduled_posts.json`: WordPress下書き・予約投稿の投稿IDと日時を管理する。",
        "",
        "## 件数",
        "",
        f"- 処理済みPDF: {len(processed_pdfs)}件",
        f"- 記事作成済み号: {sum(1 for item in processed_pdfs if isinstance(item, dict) and is_pdf_issue_completed(item))}件",
        f"- テーマ履歴: {len(topic_history)}件",
        f"- 確認済み根拠: {len(fact_checks)}件",
        f"- WordPress投稿履歴: {len(scheduled_posts)}件",
        "",
        "## 運用メモ",
        "",
        "- Google DriveからPDFを取得して記事化候補に使った時点で、PDF名・Drive ID・処理日時を記録する。",
        "- WordPress下書きが1回の実行件数分作成できた号は、記事作成済み号として扱い、次回以降の自動実行では新しい順にスキップして未作成号まで遡る。",
        "- WordPressに下書き保存または予約投稿できた時点で、テーマキー・投稿ID・投稿URLを記録する。",
        "- 法律、制度、日付、数値の根拠を確認した時点で、確認URL・確認日・根拠メモを記録する。",
        "- 下書き保存または予約投稿を作成した時点で、設定日時と投稿IDを記録する。",
        "- 未確認ファクトが残る場合は、`safe_to_publish` を `false` のまま維持する。",
        ]
    )
    return "\n".join(lines)
