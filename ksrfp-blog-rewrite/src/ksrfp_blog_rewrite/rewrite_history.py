from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .io_utils import read_json, to_int, write_json
from .paths import REWRITE_HISTORY_PATH


def load_rewrite_history(path: Path = REWRITE_HISTORY_PATH) -> dict[str, Any]:
    history = read_json(path, {}) or {}
    if not isinstance(history, dict):
        history = {}
    items = history.get("items")
    if not isinstance(items, list):
        items = []
    return {
        "version": int(history.get("version") or 1),
        "updated_at": history.get("updated_at"),
        "items": [item for item in items if isinstance(item, dict)],
    }


def rewritten_post_ids(history: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for item in history.get("items", []):
        post_id = to_int(item.get("source_post_id"))
        if post_id and should_exclude_from_candidate_selection(item):
            ids.add(post_id)
    return ids


def should_exclude_from_candidate_selection(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "")
    if status in {"drive_package_ready", "drive_uploaded", "completed"}:
        return True
    if status == "article_generated":
        return latest_article_generation_passed(item)
    return False


def latest_article_generation_passed(item: dict[str, Any]) -> bool:
    events = item.get("events") if isinstance(item.get("events"), list) else []
    for event in reversed(events):
        if not isinstance(event, dict) or event.get("event_type") != "article_generated":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        quality_gate = details.get("quality_gate") if isinstance(details.get("quality_gate"), dict) else {}
        return bool(quality_gate.get("passed"))
    return False


def record_rewrite_event(
    *,
    source_post_id: int,
    source_title: str = "",
    source_url: str = "",
    status: str,
    event_type: str,
    details: dict[str, Any] | None = None,
    article_title: str = "",
    target_seo_keyword: str = "",
    path: Path = REWRITE_HISTORY_PATH,
) -> dict[str, Any]:
    if not source_post_id:
        raise ValueError("source_post_id is required.")

    now = datetime.now().isoformat(timespec="seconds")
    history = load_rewrite_history(path)
    items = history["items"]
    item = find_history_item(items, source_post_id)
    if item is None:
        item = {
            "source_post_id": source_post_id,
            "source_title": source_title,
            "source_url": source_url,
            "first_recorded_at": now,
            "events": [],
        }
        items.append(item)

    if source_title:
        item["source_title"] = source_title
    if source_url:
        item["source_url"] = source_url
    if article_title:
        item["article_title"] = article_title
    if target_seo_keyword:
        item["target_seo_keyword"] = target_seo_keyword

    item["status"] = status
    item["updated_at"] = now
    item.setdefault("events", []).append(
        {
            "event_type": event_type,
            "status": status,
            "recorded_at": now,
            "details": details or {},
        }
    )

    history["updated_at"] = now
    history["items"] = sorted(items, key=lambda value: to_int(value.get("source_post_id")))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, history)
    return history


def record_selected_candidate(selection: dict[str, Any]) -> dict[str, Any] | None:
    selected = selection.get("selected") if isinstance(selection.get("selected"), dict) else None
    if not selected:
        return None
    return record_rewrite_event(
        source_post_id=to_int(selected.get("post_id")),
        source_title=str(selected.get("title") or ""),
        source_url=str(selected.get("url") or ""),
        status="selected",
        event_type="candidate_selected",
        details={
            "score": selected.get("score"),
            "views_total": selected.get("views_total"),
            "views_recent": selected.get("views_recent"),
            "computed_character_count": selected.get("computed_character_count"),
            "h2_count": selected.get("h2_count"),
            "h3_count": selected.get("h3_count"),
            "reasons": selected.get("reasons") or [],
        },
    )


def record_article_generated(article: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any] | None:
    source = brief.get("source", {}) if isinstance(brief.get("source"), dict) else {}
    source_post_id = to_int(source.get("post_id") or article.get("source_post_id"))
    if not source_post_id:
        return None
    return record_rewrite_event(
        source_post_id=source_post_id,
        source_title=str(source.get("title") or ""),
        source_url=str(source.get("url") or ""),
        status="article_generated",
        event_type="article_generated",
        article_title=str(article.get("title") or ""),
        target_seo_keyword=str(article.get("target_seo_keyword") or ""),
        details={
            "quality": article.get("quality"),
            "quality_gate": article.get("quality_gate"),
        },
    )


def record_article_generation_failed(article: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any] | None:
    source = brief.get("source", {}) if isinstance(brief.get("source"), dict) else {}
    source_post_id = to_int(source.get("post_id") or article.get("source_post_id"))
    if not source_post_id:
        return None
    return record_rewrite_event(
        source_post_id=source_post_id,
        source_title=str(source.get("title") or ""),
        source_url=str(source.get("url") or ""),
        status="article_generation_failed",
        event_type="article_generation_failed",
        article_title=str(article.get("title") or ""),
        target_seo_keyword=str(article.get("target_seo_keyword") or ""),
        details={
            "quality": article.get("quality"),
            "quality_gate": article.get("quality_gate"),
        },
    )


def record_drive_package_ready(drive_package: dict[str, Any]) -> dict[str, Any] | None:
    source = drive_package.get("source", {}) if isinstance(drive_package.get("source"), dict) else {}
    source_post_id = to_int(source.get("post_id"))
    if not source_post_id:
        return None
    return record_rewrite_event(
        source_post_id=source_post_id,
        source_title=str(source.get("title") or ""),
        source_url=str(source.get("url") or ""),
        status="drive_package_ready",
        event_type="drive_package_ready",
        article_title=str(drive_package.get("title") or ""),
        details={
            "template": drive_package.get("template"),
            "text_file": drive_package.get("text_file"),
            "image_file": drive_package.get("image_file"),
            "same_file_base": drive_package.get("same_file_base"),
        },
    )


def find_history_item(items: list[dict[str, Any]], source_post_id: int) -> dict[str, Any] | None:
    for item in items:
        if to_int(item.get("source_post_id")) == source_post_id:
            return item
    return None
