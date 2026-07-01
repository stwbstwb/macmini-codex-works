#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import read_json  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    build_wordpress_publish_plan,
    existing_post_can_be_recovered,
    find_existing_posts_by_exact_title,
    format_duplicate_post,
    normalize_title_for_duplicate_check,
    publish_wordpress_payload,
    read_wordpress_credentials,
    recoverable_post_matches_payload_topic,
)
from ksrfp_jinjiroumu_blog.artifact_fingerprint import manifest_fingerprint  # noqa: E402
from ksrfp_jinjiroumu_blog.image_gate import featured_image_gate_reasons  # noqa: E402
from ksrfp_jinjiroumu_blog.run_state import RunState, latest_run_key  # noqa: E402
from ksrfp_jinjiroumu_blog.state_manager import stable_key  # noqa: E402


def write_log(payload: dict[str, object]) -> None:
    log_dir = PROJECT_ROOT / "07_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (log_dir / "wordpress_publish_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (log_dir / f"wordpress-publish-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="WordPress publish dry-run or guarded execution.")
    parser.add_argument("--execute", action="store_true", help="Actually upload media and create the scheduled post.")
    parser.add_argument("--all", action="store_true", help="Publish the current manifest batch from post_payloads_latest.json.")
    args = parser.parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        if args.execute and os.environ.get("KSRFP_ALLOW_WORDPRESS_WRITE") != "1":
            raise RuntimeError("Write guard is active. Set KSRFP_ALLOW_WORDPRESS_WRITE=1 to execute.")
        if args.all:
            result = publish_all_payloads(args.execute)
        else:
            result = publish_wordpress_payload(execute=args.execute)
        payload = {
            "status": result.get("status"),
            "mode": "execute" if args.execute else "dry_run",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            **manifest_fingerprint(),
            "result": result,
            "outputs": {
                "publish_plan": "04_wordpress/wordpress_publish_plan_latest.md",
                "publish_result": "04_wordpress/wordpress_publish_result_latest.md",
                "publish_log": "07_logs/wordpress_publish_latest.json",
            },
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        success_statuses = {"dry_run", "created", "updated_existing", "already_created"}
        return 0 if result.get("status") in success_statuses else 1
    except Exception as exc:
        build_wordpress_publish_plan()
        payload = {
            "status": "error",
            "mode": "execute" if args.execute else "dry_run",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            **manifest_fingerprint(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "outputs": {
                "publish_plan": "04_wordpress/wordpress_publish_plan_latest.md",
                "publish_log": "07_logs/wordpress_publish_latest.json",
            },
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


def publish_all_payloads(execute: bool) -> dict[str, object]:
    payload_dir = PROJECT_ROOT / "03_generated" / "wordpress-payloads"
    image_dir = PROJECT_ROOT / "03_generated" / "images"
    payload_paths = current_payload_paths(payload_dir)
    if not payload_paths:
        return {"status": "no_payloads", "items": []}
    expected_count = expected_articles_per_run()
    if len(payload_paths) != expected_count:
        return {
            "status": "payload_count_mismatch",
            "expected_count": expected_count,
            "actual_count": len(payload_paths),
            "items": [
                {"item_index": item_index_from_path(path), "payload_path": f"03_generated/wordpress-payloads/{path.name}"}
                for path in payload_paths
            ],
            "reason": "WordPress保存前の投稿ペイロード件数が設定件数と一致しません。",
        }

    state = RunState(latest_run_key())
    existing_step = state.step("wordpress_posts_created")
    existing_items = existing_step.get("items", []) if isinstance(existing_step.get("items"), list) else []
    if execute and existing_step.get("status") == "ok" and len(existing_items) >= len(payload_paths):
        match = existing_created_items_match_payloads(existing_items, payload_paths)
        if not match.get("matched"):
            return {
                "status": "state_payload_mismatch",
                "run_key": state.run_key,
                "state_path": str(state.path),
                "items": existing_items,
                "mismatch": match,
                "reason": "同一runのWordPress作成済み記録が現在の投稿ペイロードと一致しないため、重複作成防止で停止しました。",
            }
        if not match.get("requires_update"):
            return {
                "status": "already_created",
                "run_key": state.run_key,
                "state_path": str(state.path),
                "items": existing_items,
            }

    if execute:
        validate_batch_payloads_ready(payload_paths, image_dir)
        validate_unique_batch_image_sources(payload_paths, image_dir)
        validate_batch_wordpress_titles(payload_paths)

    items: list[dict[str, object]] = []
    for payload_path in payload_paths:
        index = item_index_from_path(payload_path)
        image_plan_path = image_dir / f"featured_image_plan_item_{index}.json"
        suffix = f"item_{index}"
        try:
            result = publish_wordpress_payload(
                execute=execute,
                post_payload_path=payload_path,
                image_plan_path=image_plan_path,
                output_suffix=suffix,
            )
            items.append(
                {
                    "item_index": index,
                    "status": result.get("status"),
                    "payload_path": f"03_generated/wordpress-payloads/{payload_path.name}",
                    "image_plan_path": f"03_generated/images/{image_plan_path.name}",
                    "result": result,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "item_index": index,
                    "status": "error",
                    "payload_path": f"03_generated/wordpress-payloads/{payload_path.name}",
                    "image_plan_path": f"03_generated/images/{image_plan_path.name}",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    statuses = {str(item.get("status")) for item in items}
    ok_execute_statuses = {"created", "updated_existing"}
    if statuses <= (ok_execute_statuses if execute else {"dry_run"}):
        status = "created" if execute else "dry_run"
    elif statuses & ok_execute_statuses or "dry_run" in statuses:
        status = "partial"
    else:
        status = "error"
    result = {"status": status, "run_key": state.run_key, "state_path": str(state.path), "items": items}
    if execute and status == "created":
        state.mark("wordpress_posts_created", items=items)
    return result


def existing_created_items_match_payloads(
    existing_items: list[object],
    payload_paths: list[Path],
) -> dict[str, object]:
    mismatches: list[dict[str, object]] = []
    update_reasons: list[dict[str, object]] = []
    existing_by_index = {
        int(item.get("item_index") or 0): item
        for item in existing_items
        if isinstance(item, dict) and item.get("item_index") is not None
    }
    for payload_path in payload_paths:
        index = item_index_from_path(payload_path)
        payload = read_json_file(payload_path)
        wordpress = payload.get("wordpress", {}) if isinstance(payload.get("wordpress"), dict) else {}
        source = payload.get("source", {}) if isinstance(payload.get("source"), dict) else {}
        expected_topic_key = stable_key(source.get("pdf_name"), source.get("section_group"), source.get("topic_title"))
        expected_title = wordpress.get("title")
        expected_date = str(wordpress.get("date") or "")
        expected_date_gmt = str(wordpress.get("date_gmt") or "")
        expected_payload_path = f"03_generated/wordpress-payloads/{payload_path.name}"
        existing = existing_by_index.get(index)
        if not isinstance(existing, dict):
            mismatches.append({"item_index": index, "reason": "missing_existing_item"})
            continue
        result = existing.get("result", {}) if isinstance(existing.get("result"), dict) else {}
        state_record = result.get("state_record", {}) if isinstance(result.get("state_record"), dict) else {}
        if existing.get("payload_path") != expected_payload_path:
            mismatches.append(
                {
                    "item_index": index,
                    "reason": "payload_path_mismatch",
                    "actual": existing.get("payload_path"),
                    "expected": expected_payload_path,
                }
            )
        if state_record.get("topic_key") != expected_topic_key:
            mismatches.append(
                {
                    "item_index": index,
                    "reason": "topic_key_mismatch",
                    "actual": state_record.get("topic_key"),
                    "expected": expected_topic_key,
                }
            )
        if state_record.get("title") != expected_title:
            mismatches.append(
                {
                    "item_index": index,
                    "reason": "title_mismatch",
                    "actual": state_record.get("title"),
                    "expected": expected_title,
                }
            )
        if expected_date and str(state_record.get("scheduled_local") or "")[:16] != expected_date[:16]:
            update_reasons.append(
                {
                    "item_index": index,
                    "reason": "scheduled_local_changed",
                    "actual": state_record.get("scheduled_local"),
                    "expected": expected_date,
                }
            )
        if expected_date_gmt and str(state_record.get("scheduled_gmt") or "")[:16] != expected_date_gmt[:16]:
            update_reasons.append(
                {
                    "item_index": index,
                    "reason": "scheduled_gmt_changed",
                    "actual": state_record.get("scheduled_gmt"),
                    "expected": expected_date_gmt,
                }
            )
    return {
        "matched": not mismatches,
        "mismatches": mismatches,
        "requires_update": bool(update_reasons),
        "update_reasons": update_reasons,
    }


def validate_batch_payloads_ready(payload_paths: list[Path], image_dir: Path) -> None:
    settings = read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}
    manifest = read_json_file(PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json")
    manifest_items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    expected_author = int((settings.get("wordpress_author") or {}).get("id") or 2)
    allowed_categories = {
        int(row.get("id"))
        for row in settings.get("wordpress_categories", [])
        if isinstance(row, dict) and row.get("id") is not None
    }
    blocked: list[str] = []
    for payload_path in payload_paths:
        index = item_index_from_path(payload_path)
        payload = read_json_file(payload_path)
        manifest_payload = manifest_items[index - 1] if index - 1 < len(manifest_items) and isinstance(manifest_items[index - 1], dict) else {}
        wordpress = payload.get("wordpress", {}) if isinstance(payload.get("wordpress"), dict) else {}
        manifest_wordpress = (
            manifest_payload.get("wordpress", {}) if isinstance(manifest_payload.get("wordpress"), dict) else {}
        )
        source = payload.get("source", {}) if isinstance(payload.get("source"), dict) else {}
        manifest_source = (
            manifest_payload.get("source", {}) if isinstance(manifest_payload.get("source"), dict) else {}
        )
        schedule_plan = payload.get("schedule_plan", {}) if isinstance(payload.get("schedule_plan"), dict) else {}
        image_plan_path = image_dir / f"featured_image_plan_item_{index}.json"
        image_plan = read_json_file(image_plan_path)
        image_path = PROJECT_ROOT / str(image_plan.get("output_path") or "")
        image_file_exists = image_path.exists() and image_path.is_file() and image_path.stat().st_size > 0
        image_reasons = featured_image_gate_reasons(image_plan, image_exists=image_file_exists)
        payload_ready = bool(payload.get("ready_to_send"))
        policy_violations = []
        raw_policy = source.get("policy_violations")
        if isinstance(raw_policy, list):
            policy_violations = [str(item) for item in raw_policy if str(item)]
        categories = wordpress.get("categories") if isinstance(wordpress.get("categories"), list) else []
        item_reasons: list[str] = []
        if not payload_path.exists():
            item_reasons.append("payload_missing")
        if manifest_wordpress.get("title") != wordpress.get("title"):
            item_reasons.append("manifest_title_mismatch")
        if manifest_source.get("topic_key") != source.get("topic_key"):
            item_reasons.append("manifest_topic_key_mismatch")
        if manifest_payload.get("ready_to_send") != payload.get("ready_to_send"):
            item_reasons.append("manifest_ready_to_send_mismatch")
        if not payload_ready:
            item_reasons.append("payload_not_ready")
        if wordpress.get("status") != "draft":
            item_reasons.append(f"wordpress_status_not_draft:{wordpress.get('status')}")
        if int(wordpress.get("author") or 0) != expected_author:
            item_reasons.append(f"wordpress_author_mismatch:{wordpress.get('author')} expected {expected_author}")
        if wordpress.get("tags") != []:
            item_reasons.append(f"wordpress_tags_not_empty:{wordpress.get('tags')}")
        if wordpress.get("slug"):
            item_reasons.append("wordpress_slug_must_be_empty")
        if len(categories) != 1 or not categories or int(categories[0]) not in allowed_categories:
            item_reasons.append(f"wordpress_category_invalid:{categories}")
        if not is_execution_date_target_time(wordpress.get("date"), schedule_plan):
            item_reasons.append(f"wordpress_date_not_execution_date_target_time:{wordpress.get('date')}")
        if not image_plan_path.exists():
            item_reasons.append("image_plan_missing")
        if not image_file_exists:
            item_reasons.append(f"featured_image_missing:{image_path}")
        item_reasons.extend(image_reasons)
        if policy_violations:
            item_reasons.append("source_policy_violations:" + " / ".join(policy_violations))
        if item_reasons:
            blocked.append(
                f"{index}件目 {payload_path.name}: "
                + " / ".join(dict.fromkeys(item_reasons))
            )
    if blocked:
        raise RuntimeError(
            "Batch WordPress publish preflight failed. No posts were created. "
            + " ; ".join(blocked)
        )


def is_execution_date_target_time(value: object, schedule_plan: dict[str, object]) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        target_date = schedule_execution_date(schedule_plan)
        target_hour, target_minute = schedule_target_time(schedule_plan)
    except (TypeError, ValueError):
        return False
    return (
        parsed.date() == target_date
        and parsed.hour == target_hour
        and parsed.minute == target_minute
        and parsed.second == 0
    )


def schedule_execution_date(schedule_plan: dict[str, object]) -> object:
    raw_date = str(schedule_plan.get("execution_date") or "").strip()
    if raw_date:
        return datetime.fromisoformat(raw_date[:10]).date()
    generated_at = str(schedule_plan.get("generated_at") or "").replace("Z", "+00:00")
    return datetime.fromisoformat(generated_at).date()


def schedule_target_time(schedule_plan: dict[str, object]) -> tuple[int, int]:
    raw_time = str(schedule_plan.get("target_time") or "09:00").strip()
    hour_text, minute_text, *_ = raw_time.split(":") + ["0"]
    return int(hour_text), int(minute_text)


def validate_batch_wordpress_titles(payload_paths: list[Path]) -> None:
    settings = read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}
    titles: list[dict[str, object]] = []
    for payload_path in payload_paths:
        payload = read_json_file(payload_path)
        wordpress = payload.get("wordpress", {}) if isinstance(payload.get("wordpress"), dict) else {}
        title = str(wordpress.get("title") or "").strip()
        if not title:
            raise RuntimeError(f"WordPress payload title is empty: {payload_path}")
        normalized = normalize_batch_title(title)
        titles.append(
            {
                "item_index": item_index_from_path(payload_path),
                "title": title,
                "normalized": normalized,
                "payload_path": f"03_generated/wordpress-payloads/{payload_path.name}",
                "payload": payload,
            }
        )

    seen: dict[str, dict[str, object]] = {}
    duplicate_titles: list[str] = []
    for row in titles:
        normalized = str(row["normalized"])
        if normalized in seen:
            duplicate_titles.append(f"{seen[normalized]['item_index']}件目 and {row['item_index']}件目: {row['title']}")
        else:
            seen[normalized] = row
    if duplicate_titles:
        raise RuntimeError("Duplicate titles inside generated batch: " + " / ".join(duplicate_titles))

    credentials = read_wordpress_credentials()
    if not credentials.get("ready"):
        raise RuntimeError("WordPress credentials are not ready.")
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    nonrecoverable: list[str] = []
    for row in titles:
        existing_matches = find_existing_posts_by_exact_title(
            api_base,
            credentials["username"],
            credentials["application_password"],
            str(row["title"]),
        )
        blocked_matches = [
            existing for existing in existing_matches
            if not existing_post_can_be_recovered(existing)
            or not recoverable_post_matches_payload_topic(existing, row.get("payload", {}))
        ]
        if blocked_matches:
            nonrecoverable.append(f"{row['item_index']}件目: " + " / ".join(format_duplicate_post(existing) for existing in blocked_matches))
    if nonrecoverable:
        raise RuntimeError(
            "Non-recoverable duplicate WordPress post titles found before batch publish. "
            "No posts were created. "
            + " / ".join(nonrecoverable)
        )


def normalize_batch_title(value: str) -> str:
    return normalize_title_for_duplicate_check(value)


def expected_articles_per_run() -> int:
    settings = read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}
    try:
        return max(1, int(settings.get("articles_per_run") or 3))
    except (TypeError, ValueError):
        return 3


def validate_unique_batch_image_sources(payload_paths: list[Path], image_dir: Path) -> None:
    seen: dict[str, dict[str, object]] = {}
    duplicates: list[dict[str, object]] = []
    for payload_path in payload_paths:
        index = item_index_from_path(payload_path)
        image_plan_path = image_dir / f"featured_image_plan_item_{index}.json"
        image_plan = read_json_file(image_plan_path)
        source_path_text = source_path_from_image_plan(image_plan)
        if not source_path_text:
            continue
        source_path = PROJECT_ROOT / source_path_text
        if not source_path.exists() or not source_path.is_file():
            continue
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        current = {
            "item_index": index,
            "source_path": source_path_text,
            "image_plan_path": f"03_generated/images/{image_plan_path.name}",
            "payload_path": f"03_generated/wordpress-payloads/{payload_path.name}",
        }
        if digest in seen:
            duplicates.append(
                {
                    "digest": digest,
                    "first": seen[digest],
                    "duplicate": current,
                }
            )
        else:
            seen[digest] = current
    if duplicates:
        details = "; ".join(
            f"item {item['first']['item_index']} and item {item['duplicate']['item_index']} "
            f"use the same photo source"
            for item in duplicates
        )
        raise RuntimeError(
            "Duplicate featured-image photo sources detected in the batch. "
            "Each article must use a different article-matched photo background before WordPress save. "
            + details
        )


def read_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def current_payload_paths(payload_dir: Path) -> list[Path]:
    manifest = read_json_file(payload_dir / "post_payloads_latest.json")
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    if items:
        return [payload_dir / f"post_payload_item_{index}.json" for index in range(1, len(items) + 1)]
    return sorted(payload_dir.glob("post_payload_item_*.json"), key=item_index_from_path)


def source_path_from_image_plan(image_plan: dict[str, object]) -> str:
    base_image = image_plan.get("base_image", {})
    if isinstance(base_image, dict):
        value = base_image.get("source_path")
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = image_plan.get("output_path")
    return value.strip() if isinstance(value, str) and value.strip() else ""


def item_index_from_path(path: Path) -> int:
    stem = path.stem
    try:
        return int(stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
