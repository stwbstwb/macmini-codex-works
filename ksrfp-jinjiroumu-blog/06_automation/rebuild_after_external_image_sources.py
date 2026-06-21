#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.analyze_inputs import (  # noqa: E402
    LATEST_OUTPUTS,
    evaluate_article_batch_quality,
    render_article_batch,
    render_article_batch_quality,
    snapshot_latest_outputs,
)
from ksrfp_jinjiroumu_blog.image_plan import build_featured_image_plan  # noqa: E402
from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR, WORDPRESS_PAYLOAD_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.review_text import build_review_text_file  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_payload import build_wordpress_payload  # noqa: E402


RESTORE_KEYS = (
    "article_brief_json",
    "article_brief_md",
    "source_plan_json",
    "source_plan_md",
    "article_outline_json",
    "article_outline_md",
    "article_draft_json",
    "article_draft_md",
    "fact_check_json",
    "fact_check_md",
    "fact_check_csv",
    "quality_check_json",
    "quality_check_md",
)


def main() -> int:
    started_at = datetime.now().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": started_at,
        "finished_at": None,
        "items": [],
    }
    try:
        batch = read_json(GENERATED_DIR / "articles" / "article_batch_latest.json", {}) or {}
        items = batch.get("items", []) if isinstance(batch.get("items"), list) else []
        if not items:
            raise RuntimeError("article_batch_latest.json does not contain items.")

        rebuilt_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            index = int(item.get("item_index") or len(rebuilt_items) + 1)
            restore_latest_outputs(item)
            image_plan = build_featured_image_plan()
            wordpress_payload = build_wordpress_payload()
            review_text = build_review_text_file(upload=False)
            outputs = snapshot_latest_outputs(index)
            item = {
                **item,
                "featured_image_plan": image_plan,
                "wordpress_payload": wordpress_payload,
                "review_text": review_text,
                "outputs": outputs,
                "rebuilt_after_external_image_source_at": datetime.now().isoformat(timespec="seconds"),
            }
            rebuilt_items.append(item)

        batch["items"] = rebuilt_items
        batch["generated_count"] = len(rebuilt_items)
        batch["batch_quality"] = evaluate_article_batch_quality(rebuilt_items)
        batch["status"] = "ok" if rebuilt_items and batch["batch_quality"].get("passed") else "quality_warning"
        write_json(GENERATED_DIR / "articles" / "article_batch_latest.json", batch)
        write_markdown(GENERATED_DIR / "articles" / "article_batch_latest.md", render_article_batch(batch))
        write_json(GENERATED_DIR / "articles" / "article_batch_quality_latest.json", batch["batch_quality"])
        write_markdown(
            GENERATED_DIR / "articles" / "article_batch_quality_latest.md",
            render_article_batch_quality(batch["batch_quality"]),
        )
        write_json(
            WORDPRESS_PAYLOAD_DIR / "post_payloads_latest.json",
            {"items": [item["wordpress_payload"] for item in rebuilt_items]},
        )
        payload["items"] = summarize_items(rebuilt_items)
        payload["batch_quality"] = batch["batch_quality"]
        payload["status"] = "ok" if all(item.get("ready_to_send") for item in payload["items"]) else "blocked"
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


def restore_latest_outputs(item: dict[str, Any]) -> None:
    outputs = item.get("outputs", {}) if isinstance(item.get("outputs"), dict) else {}
    for key in RESTORE_KEYS:
        latest_path = LATEST_OUTPUTS.get(key)
        item_path_text = outputs.get(key)
        if not latest_path or not item_path_text:
            continue
        source = PROJECT_ROOT / str(item_path_text)
        if source.exists():
            latest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, latest_path)


def summarize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        image_plan = item.get("featured_image_plan", {}) if isinstance(item.get("featured_image_plan"), dict) else {}
        base_image = image_plan.get("base_image", {}) if isinstance(image_plan.get("base_image"), dict) else {}
        wordpress_payload = item.get("wordpress_payload", {}) if isinstance(item.get("wordpress_payload"), dict) else {}
        wordpress = wordpress_payload.get("wordpress", {}) if isinstance(wordpress_payload.get("wordpress"), dict) else {}
        rows.append(
            {
                "item_index": item.get("item_index"),
                "title": wordpress.get("title"),
                "ready_to_send": wordpress_payload.get("ready_to_send"),
                "blocked_reasons": wordpress_payload.get("blocked_reasons"),
                "image_status": image_plan.get("status"),
                "image_wordpress_ready": image_plan.get("wordpress_ready"),
                "photo_source_path": base_image.get("source_path"),
                "photo_source_fresh": base_image.get("photo_source_fresh"),
                "source_match": base_image.get("source_match"),
            }
        )
    return rows


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "rebuild_after_external_image_sources_latest.json", payload)
    write_json(LOGS_DIR / f"rebuild-after-external-image-sources-{timestamp}.json", payload)


if __name__ == "__main__":
    raise SystemExit(main())
