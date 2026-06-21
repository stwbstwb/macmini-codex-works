#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import read_json, read_text, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.artifact_fingerprint import current_manifest_digest  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR, STATE_DIR, WORDPRESS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.state_manager import stable_key  # noqa: E402
from ksrfp_jinjiroumu_blog.article_brief import source_policy_violations  # noqa: E402


FORBIDDEN_CONTENT_PATTERNS = (
    "人事労務だより",
    "掲載されていた",
    "取り上げられていた",
    "出典PDF",
    "制度・ニュースの概要",
    "ニュースとして読むだけ",
    "柏谷横浜社労士事務所では",
    "相談を承",
)

TEMPLATE_HEADING_PATTERNS = (
    "導入前チェックリスト",
    "申請前のチェックリスト",
    "実務チェックリスト",
    "導入時のチェックリスト",
    "対応前チェックリスト",
    "確認チェックリスト",
)


class Contract:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, passed: bool, **details: Any) -> None:
        self.checks.append({"name": name, "passed": bool(passed), **details})

    def ok(self) -> bool:
        return all(check.get("passed") is True for check in self.checks)


def load_settings() -> dict[str, Any]:
    return read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}


def expected_count(settings: dict[str, Any]) -> int:
    try:
        return max(1, int(settings.get("articles_per_run") or 3))
    except (TypeError, ValueError):
        return 3


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def is_current(path: Path, reference: Path, slack_seconds: int = 120) -> bool:
    if not path.exists() or not reference.exists():
        return False
    return path.stat().st_mtime + slack_seconds >= reference.stat().st_mtime


def mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def load_manifest() -> dict[str, Any]:
    return read_json(GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json", {}) or {}


def payload_manifest_digest(payload: dict[str, Any]) -> str:
    value = payload.get("manifest_sha256")
    if isinstance(value, str) and value:
        return value
    fingerprint = payload.get("manifest_fingerprint")
    if isinstance(fingerprint, dict) and isinstance(fingerprint.get("manifest_sha256"), str):
        return str(fingerprint.get("manifest_sha256") or "")
    return ""


def payload_matches_manifest(payload: dict[str, Any]) -> bool:
    digest = current_manifest_digest()
    return bool(digest) and payload_manifest_digest(payload) == digest


def item_index_from_path(path: Path) -> int:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def current_item_paths(directory: Path, prefix: str, suffix: str, count: int) -> list[Path]:
    return [directory / f"{prefix}_{index}.{suffix}" for index in range(1, count + 1)]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.is_file() else ""


def nonempty_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip().lower()


def is_monday_0900(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.weekday() == 0 and parsed.hour == 9 and parsed.minute == 0 and parsed.second == 0


def expected_review_file_name(title: str, wordpress_date: Any) -> str:
    text = str(wordpress_date or "")
    return f"{text[2:4]}{text[5:7]}{text[8:10]} {title}.txt"


def drive_url_has_file_id(value: Any) -> bool:
    url = str(value or "")
    return "/d/" in url or "id=" in url


def text_contains_forbidden(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = read_text(path)
    return [pattern for pattern in FORBIDDEN_CONTENT_PATTERNS if pattern in text]


def validate_payloads(contract: Contract, settings: dict[str, Any], count: int) -> list[dict[str, Any]]:
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    manifest = load_manifest()
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    contract.add(
        "wordpress_payload_manifest_count",
        len(items) == count,
        expected=count,
        actual=len(items),
        path=rel(manifest_path),
    )

    allowed_categories = {
        int(row.get("id"))
        for row in settings.get("wordpress_categories", [])
        if isinstance(row, dict) and row.get("id") is not None
    }
    expected_author = int((settings.get("wordpress_author") or {}).get("id") or 0)
    title_rows: list[dict[str, Any]] = []
    payload_rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        payload_path = GENERATED_DIR / "wordpress-payloads" / f"post_payload_item_{index}.json"
        payload = read_json(payload_path, {}) or {}
        manifest_payload = items[index - 1] if index - 1 < len(items) and isinstance(items[index - 1], dict) else {}
        wordpress = payload.get("wordpress", {}) if isinstance(payload.get("wordpress"), dict) else {}
        manifest_wordpress = (
            manifest_payload.get("wordpress", {}) if isinstance(manifest_payload.get("wordpress"), dict) else {}
        )
        quality = payload.get("quality", {}) if isinstance(payload.get("quality"), dict) else {}
        featured = payload.get("featured_image", {}) if isinstance(payload.get("featured_image"), dict) else {}
        source = payload.get("source", {}) if isinstance(payload.get("source"), dict) else {}
        manifest_source = (
            manifest_payload.get("source", {}) if isinstance(manifest_payload.get("source"), dict) else {}
        )
        title = str(wordpress.get("title") or "")
        categories = wordpress.get("categories") if isinstance(wordpress.get("categories"), list) else []
        title_rows.append({"item_index": index, "title": title, "normalized": normalize_title(title)})
        payload_rows.append({"item_index": index, "path": payload_path, "payload": payload, "source": source, "title": title})
        contract.add(f"payload_{index}_exists", payload_path.exists(), path=rel(payload_path))
        contract.add(f"payload_{index}_manifest_title_matches_item", manifest_wordpress.get("title") == wordpress.get("title"), manifest=manifest_wordpress.get("title"), item=wordpress.get("title"))
        contract.add(f"payload_{index}_manifest_topic_matches_item", manifest_source.get("topic_key") == source.get("topic_key"), manifest=manifest_source.get("topic_key"), item=source.get("topic_key"))
        contract.add(f"payload_{index}_manifest_ready_matches_item", manifest_payload.get("ready_to_send") == payload.get("ready_to_send"), manifest=manifest_payload.get("ready_to_send"), item=payload.get("ready_to_send"))
        contract.add(f"payload_{index}_ready_to_send", payload.get("ready_to_send") is True, path=rel(payload_path))
        contract.add(f"payload_{index}_status_draft", wordpress.get("status") == "draft", actual=wordpress.get("status"))
        contract.add(f"payload_{index}_author", int(wordpress.get("author") or 0) == expected_author, actual=wordpress.get("author"), expected=expected_author)
        contract.add(f"payload_{index}_tags_empty", wordpress.get("tags") == [], actual=wordpress.get("tags"))
        contract.add(f"payload_{index}_slug_not_set", "slug" not in wordpress or not wordpress.get("slug"), actual=wordpress.get("slug"))
        contract.add(f"payload_{index}_one_allowed_category", len(categories) == 1 and int(categories[0]) in allowed_categories, actual=categories)
        contract.add(f"payload_{index}_date_monday_0900", is_monday_0900(wordpress.get("date")), actual=wordpress.get("date"))
        contract.add(f"payload_{index}_quality_ready", quality.get("draft_quality_passed") is True and quality.get("publication_ready") is True and quality.get("safe_to_publish") is True, actual=quality)
        contract.add(f"payload_{index}_facts_verified", int(quality.get("fact_check_unverified") or 0) == 0 and quality.get("publication_gate") == "verified", actual=quality)
        contract.add(f"payload_{index}_image_ready", featured.get("wordpress_ready") is True and featured.get("photo_source_exists") is True and featured.get("photo_source_fresh") is True, actual=featured)
        policy_violations = source_policy_violations({key: str(value or "") for key, value in source.items()})
        contract.add(f"payload_{index}_source_policy_fit", not policy_violations, violations=policy_violations, source=source)

    normalized_titles = [row["normalized"] for row in title_rows if row["normalized"]]
    contract.add(
        "payload_titles_unique",
        len(normalized_titles) == len(set(normalized_titles)) == count,
        titles=[row["title"] for row in title_rows],
    )
    return payload_rows


def validate_article_quality(contract: Contract, count: int) -> None:
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    quality_path = GENERATED_DIR / "articles" / "article_batch_quality_latest.json"
    quality = read_json(quality_path, {}) or {}
    contract.add("article_batch_quality_current", is_current(quality_path, manifest_path), path=rel(quality_path), mtime=mtime_iso(quality_path))
    contract.add("article_batch_quality_passed", quality.get("status") == "ok" and quality.get("passed") is True, actual={"status": quality.get("status"), "passed": quality.get("passed")})
    for key in (
        "image_backgrounds_unique",
        "intra_article_repetition_ok",
        "title_uniqueness_ok",
        "title_pattern_diversity_ok",
        "structure_pattern_diversity_ok",
    ):
        contract.add(f"article_batch_quality_{key}", quality.get(key) is True, actual=quality.get(key))
    contract.add("article_batch_quality_count", int(quality.get("article_count") or 0) == count, actual=quality.get("article_count"), expected=count)


def validate_text_outputs(contract: Contract, payload_rows: list[dict[str, Any]]) -> None:
    for row in payload_rows:
        index = int(row["item_index"])
        title = str(row["title"])
        paths = [
            GENERATED_DIR / "articles" / f"article_draft_item_{index}.md",
            GENERATED_DIR / "wordpress-payloads" / f"post_content_item_{index}.html",
            GENERATED_DIR / "review-texts" / f"review_text_item_{index}.txt",
        ]
        for path in paths:
            forbidden = text_contains_forbidden(path)
            template_headings = [pattern for pattern in TEMPLATE_HEADING_PATTERNS if path.exists() and pattern in read_text(path)]
            contract.add(f"text_{index}_{path.suffix[1:]}_exists", path.exists(), path=rel(path))
            contract.add(f"text_{index}_{path.suffix[1:]}_forbidden_absent", not forbidden, path=rel(path), forbidden=forbidden)
            contract.add(f"text_{index}_{path.suffix[1:]}_template_heading_absent", not template_headings, path=rel(path), template_headings=template_headings)
        contract.add(f"text_{index}_title_nonempty", bool(title.strip()), title=title)


def validate_images(contract: Contract, count: int) -> None:
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    source_digests: dict[str, int] = {}
    output_digests: dict[str, int] = {}
    scene_types: list[str] = []
    for index in range(1, count + 1):
        plan_path = GENERATED_DIR / "images" / f"featured_image_plan_item_{index}.json"
        plan = read_json(plan_path, {}) or {}
        base = plan.get("base_image", {}) if isinstance(plan.get("base_image"), dict) else {}
        scene = plan.get("scene_profile", {}) if isinstance(plan.get("scene_profile"), dict) else {}
        output_path = PROJECT_ROOT / str(plan.get("output_path") or "")
        source_path = PROJECT_ROOT / str(base.get("source_path") or "")
        source_hash = digest(source_path)
        output_hash = digest(output_path)
        required_after = str(base.get("required_new_after") or plan.get("generated_at") or "")
        source_mtime = datetime.fromtimestamp(source_path.stat().st_mtime).isoformat(timespec="seconds") if nonempty_file(source_path) else None
        fresh_by_mtime = True
        if source_mtime and required_after:
            fresh_by_mtime = source_mtime >= required_after[:19]
        contract.add(f"image_plan_{index}_current", is_current(plan_path, manifest_path), path=rel(plan_path), mtime=mtime_iso(plan_path))
        contract.add(f"image_plan_{index}_wordpress_ready", plan.get("wordpress_ready") is True, actual=plan.get("wordpress_ready"))
        contract.add(f"image_plan_{index}_base_status", base.get("status") == "photo_source_copied", actual=base.get("status"))
        contract.add(f"image_plan_{index}_source_match", base.get("source_match") == "fresh_article_source", actual=base.get("source_match"))
        contract.add(f"image_plan_{index}_photo_source_exists", nonempty_file(source_path), source_path=rel(source_path))
        contract.add(f"image_plan_{index}_photo_source_fresh", base.get("photo_source_fresh") is True and fresh_by_mtime, actual=base.get("photo_source_fresh"), required_after=required_after, source_mtime=source_mtime)
        contract.add(f"image_plan_{index}_output_exists", nonempty_file(output_path), output_path=rel(output_path))
        contract.add(f"image_plan_{index}_photorealistic_required", plan.get("photorealistic_required") is True, actual=plan.get("photorealistic_required"))
        contract.add(f"image_plan_{index}_alt_text_present", bool(str(plan.get("alt_text") or "").strip()), actual=plan.get("alt_text"))
        contract.add(
            f"image_plan_{index}_scene_profile_present",
            all(str(scene.get(key) or "").strip() for key in ("scene_type", "backdrop", "people", "elements")),
            actual=scene,
        )
        prompt = str(plan.get("prompt") or "")
        contract.add(
            f"image_plan_{index}_prompt_requires_new_photo",
            all(fragment in prompt for fragment in ("brand-new", "photorealistic", "Do not reuse", "Variation requirement")),
            prompt_excerpt=prompt[:300],
        )
        if scene.get("scene_type"):
            scene_types.append(str(scene.get("scene_type")))
        if source_hash:
            contract.add(f"image_plan_{index}_source_hash_unique_so_far", source_hash not in source_digests, duplicate_of=source_digests.get(source_hash))
            source_digests[source_hash] = index
        if output_hash:
            contract.add(f"image_plan_{index}_output_hash_unique_so_far", output_hash not in output_digests, duplicate_of=output_digests.get(output_hash))
            output_digests[output_hash] = index
    contract.add(
        "image_plan_scene_types_diverse",
        len(scene_types) == count and len(set(scene_types)) >= min(count, 2),
        scene_types=scene_types,
    )


def validate_wordpress(contract: Contract, payload_rows: list[dict[str, Any]], count: int) -> list[int]:
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    publish_path = LOGS_DIR / "wordpress_publish_latest.json"
    verify_path = WORDPRESS_DIR / "wordpress_batch_verification_latest.json"
    publish = read_json(publish_path, {}) or {}
    publish_result = publish.get("result", {}) if isinstance(publish.get("result"), dict) else {}
    publish_items = publish_result.get("items", []) if isinstance(publish_result.get("items"), list) else []
    verify = read_json(verify_path, {}) or {}
    verify_items = verify.get("items", []) if isinstance(verify.get("items"), list) else []
    publish_current = is_current(publish_path, manifest_path)
    contract.add("wordpress_publish_log_current", publish_current, path=rel(publish_path), mtime=mtime_iso(publish_path))
    contract.add(
        "wordpress_publish_manifest_digest_matches",
        payload_matches_manifest(publish),
        actual=payload_manifest_digest(publish),
        expected=current_manifest_digest(),
    )
    contract.add("wordpress_publish_status", publish.get("status") in {"created", "already_created"}, actual=publish.get("status"))
    contract.add("wordpress_publish_item_count", len(publish_items) == count, actual=len(publish_items), expected=count)
    post_ids: list[int] = []
    expected_by_index = {int(row["item_index"]): row for row in payload_rows}
    for item in publish_items:
        if not isinstance(item, dict):
            continue
        index = int(item.get("item_index") or 0)
        expected_row = expected_by_index.get(index, {})
        expected_payload_path = expected_row.get("path") if isinstance(expected_row.get("path"), Path) else None
        expected_source = expected_row.get("source", {}) if isinstance(expected_row.get("source"), dict) else {}
        expected_topic_key = stable_key(
            expected_source.get("pdf_name"),
            expected_source.get("section_group"),
            expected_source.get("topic_title"),
        )
        result = item.get("result", {}) if isinstance(item.get("result"), dict) else {}
        post = result.get("post", {}) if isinstance(result.get("post"), dict) else {}
        state_record = result.get("state_record", {}) if isinstance(result.get("state_record"), dict) else {}
        post_id = int(post.get("id") or 0)
        if publish_current and post_id:
            post_ids.append(post_id)
        contract.add(f"wordpress_publish_item_{index}_created_or_reused", item.get("status") in {"created", "updated_existing", "already_created"}, actual=item.get("status"))
        contract.add(f"wordpress_publish_item_{index}_state_recorded", bool(result.get("state_record")), actual=result.get("state_record"))
        if expected_payload_path:
            contract.add(
                f"wordpress_publish_item_{index}_payload_path_matches",
                str(item.get("payload_path") or "") == rel(expected_payload_path),
                actual=item.get("payload_path"),
                expected=rel(expected_payload_path),
            )
        contract.add(
            f"wordpress_publish_item_{index}_state_topic_matches",
            state_record.get("topic_key") == expected_topic_key,
            actual=state_record.get("topic_key"),
            expected=expected_topic_key,
        )
        contract.add(
            f"wordpress_publish_item_{index}_state_title_matches",
            state_record.get("title") == expected_row.get("title"),
            actual=state_record.get("title"),
            expected=expected_row.get("title"),
        )

    contract.add("wordpress_verify_log_current", is_current(verify_path, manifest_path), path=rel(verify_path), mtime=mtime_iso(verify_path))
    contract.add(
        "wordpress_verify_manifest_digest_matches",
        payload_matches_manifest(verify),
        actual=payload_manifest_digest(verify),
        expected=current_manifest_digest(),
    )
    contract.add("wordpress_verify_status", verify.get("status") == "ok", actual=verify.get("status"))
    contract.add("wordpress_verify_item_count", len(verify_items) == count, actual=len(verify_items), expected=count)
    for item in verify_items:
        if not isinstance(item, dict):
            continue
        index = int(item.get("item_index") or 0)
        expected_row = expected_by_index.get(index, {})
        checks = item.get("checks", {}) if isinstance(item.get("checks"), dict) else {}
        contract.add(f"wordpress_verify_item_{index}_status_ok", item.get("status") == "ok", actual=item.get("status"))
        contract.add(f"wordpress_verify_item_{index}_all_checks", bool(checks) and all(value is True for value in checks.values()), checks=checks)
        contract.add(f"wordpress_verify_item_{index}_forbidden_absent", not item.get("forbidden_found"), forbidden=item.get("forbidden_found"))
        contract.add(
            f"wordpress_verify_item_{index}_title_matches_payload",
            item.get("title") == expected_row.get("title"),
            actual=item.get("title"),
            expected=expected_row.get("title"),
        )
        if publish_current and post_ids:
            contract.add(
                f"wordpress_verify_item_{index}_post_id_from_current_publish",
                int(item.get("post_id") or 0) in post_ids,
                actual=item.get("post_id"),
                expected=post_ids,
            )
    return post_ids


def validate_drive(contract: Contract, payload_rows: list[dict[str, Any]], count: int) -> None:
    manifest_path = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"
    expected_by_index = {int(row["item_index"]): row for row in payload_rows}
    for index in range(1, count + 1):
        metadata_path = GENERATED_DIR / "review-texts" / f"review_text_item_{index}.json"
        metadata = read_json(metadata_path, {}) or {}
        upload = metadata.get("upload", {}) if isinstance(metadata.get("upload"), dict) else {}
        output_path = PROJECT_ROOT / str(metadata.get("output_path") or "")
        expected_row = expected_by_index.get(index, {})
        expected_payload = expected_row.get("payload", {}) if isinstance(expected_row.get("payload"), dict) else {}
        expected_wordpress = (
            expected_payload.get("wordpress", {}) if isinstance(expected_payload.get("wordpress"), dict) else {}
        )
        expected_file_name = expected_review_file_name(str(expected_row.get("title") or ""), expected_wordpress.get("date"))
        contract.add(f"drive_review_text_{index}_metadata_current", is_current(metadata_path, manifest_path), path=rel(metadata_path), mtime=mtime_iso(metadata_path))
        contract.add(
            f"drive_review_text_{index}_manifest_digest_matches",
            payload_matches_manifest(metadata),
            actual=payload_manifest_digest(metadata),
            expected=current_manifest_digest(),
        )
        contract.add(f"drive_review_text_{index}_file_name_matches", metadata.get("file_name") == expected_file_name, actual=metadata.get("file_name"), expected=expected_file_name)
        contract.add(f"drive_review_text_{index}_file_exists", nonempty_file(output_path), path=rel(output_path))
        contract.add(f"drive_review_text_{index}_uploaded", upload.get("status") == "uploaded", actual=upload)
        url = upload.get("webViewLink") or upload.get("url")
        contract.add(f"drive_review_text_{index}_url_recorded", bool(url), actual=url)
        contract.add(f"drive_review_text_{index}_url_has_file_id", drive_url_has_file_id(url), actual=url)


def validate_state(contract: Contract, payload_rows: list[dict[str, Any]], post_ids: list[int], count: int) -> None:
    scheduled = read_json(STATE_DIR / "scheduled_posts.json", {}) or {}
    processed = read_json(STATE_DIR / "processed_pdfs.json", {}) or {}
    topics = read_json(STATE_DIR / "topic_history.json", {}) or {}
    scheduled_items = scheduled.get("items", []) if isinstance(scheduled.get("items"), list) else []
    processed_items = processed.get("items", []) if isinstance(processed.get("items"), list) else []
    topic_items = topics.get("items", []) if isinstance(topics.get("items"), list) else []
    payload_topic_keys = [
        stable_key(row["source"].get("pdf_name"), row["source"].get("section_group"), row["source"].get("topic_title"))
        for row in payload_rows
    ]
    scheduled_topic_keys = {str(item.get("topic_key")) for item in scheduled_items if isinstance(item, dict)}
    scheduled_post_ids = {int(item.get("wordpress_post_id") or 0) for item in scheduled_items if isinstance(item, dict)}
    topic_history_keys = {str(item.get("topic_key")) for item in topic_items if isinstance(item, dict)}
    contract.add("state_scheduled_posts_cover_current_topics", all(key in scheduled_topic_keys for key in payload_topic_keys), expected=payload_topic_keys, actual=sorted(scheduled_topic_keys))
    if post_ids:
        contract.add("state_scheduled_posts_cover_current_post_ids", all(post_id in scheduled_post_ids for post_id in post_ids), expected=post_ids, actual=sorted(scheduled_post_ids))
    for row in payload_rows:
        index = int(row["item_index"])
        topic_key = stable_key(row["source"].get("pdf_name"), row["source"].get("section_group"), row["source"].get("topic_title"))
        matching_records = [
            item for item in scheduled_items
            if isinstance(item, dict) and str(item.get("topic_key") or "") == topic_key
        ]
        latest_record = sorted(matching_records, key=lambda item: str(item.get("created_at") or ""))[-1] if matching_records else {}
        image_plan = read_json(GENERATED_DIR / "images" / f"featured_image_plan_item_{index}.json", {}) or {}
        image_path = PROJECT_ROOT / str(image_plan.get("output_path") or "")
        image_sha256 = digest(image_path)
        contract.add(
            f"state_scheduled_post_{index}_featured_media_id_present",
            int(latest_record.get("featured_media_id") or 0) > 0,
            actual=latest_record.get("featured_media_id"),
        )
        contract.add(
            f"state_scheduled_post_{index}_featured_image_sha256_matches_output",
            bool(image_sha256) and latest_record.get("featured_image_sha256") == image_sha256,
            actual=latest_record.get("featured_image_sha256"),
            expected=image_sha256,
            image_path=rel(image_path),
        )
        contract.add(
            f"state_scheduled_post_{index}_post_payload_path_recorded",
            str(latest_record.get("post_payload_path") or "") == f"03_generated/wordpress-payloads/post_payload_item_{index}.json",
            actual=latest_record.get("post_payload_path"),
        )
        contract.add(
            f"state_scheduled_post_{index}_image_plan_path_recorded",
            str(latest_record.get("image_plan_path") or "") == f"03_generated/images/featured_image_plan_item_{index}.json",
            actual=latest_record.get("image_plan_path"),
        )
    contract.add("state_topic_history_cover_current_topics", all(key in topic_history_keys for key in payload_topic_keys), expected=payload_topic_keys, actual=sorted(topic_history_keys))
    pdf_names = {str(row["source"].get("pdf_name")) for row in payload_rows if row["source"].get("pdf_name")}
    for pdf_name in pdf_names:
        item = next((entry for entry in processed_items if isinstance(entry, dict) and entry.get("pdf_name") == pdf_name), {})
        contract.add(f"state_processed_pdf_completed_{pdf_name}", int(item.get("wordpress_post_count") or 0) >= count and item.get("status") == "draft_saved_for_review", actual=item)


def validate_notification(contract: Contract, allow_missing_notification: bool) -> None:
    if allow_missing_notification:
        contract.add("notification_allowed_missing_before_send", True)
        return
    latest_path = LOGS_DIR / "notifications" / "latest_notification.json"
    reference_paths = [
        GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json",
        LOGS_DIR / "wordpress_publish_latest.json",
        WORDPRESS_DIR / "wordpress_batch_verification_latest.json",
    ]
    count = expected_count(load_settings())
    review_paths = [GENERATED_DIR / "review-texts" / f"review_text_item_{index}.json" for index in range(1, count + 1)]
    reference_paths.extend(review_paths)
    latest_required_mtime = max((path.stat().st_mtime for path in reference_paths if path.exists()), default=0)
    notification = read_json(latest_path, {}) or {}
    contract.add("notification_latest_exists", latest_path.exists(), path=rel(latest_path))
    contract.add("notification_sent", notification.get("status") in {"sent", "already_sent"}, actual=notification)
    contract.add("notification_run_status_ok", notification.get("run_status") == "ok", actual=notification.get("run_status"))
    contract.add(
        "notification_manifest_digest_matches",
        payload_matches_manifest(notification),
        actual=payload_manifest_digest(notification),
        expected=current_manifest_digest(),
    )
    contract.add(
        "notification_after_final_artifacts",
        latest_path.exists() and latest_path.stat().st_mtime + 5 >= latest_required_mtime,
        notification_mtime=mtime_iso(latest_path),
        latest_artifact_mtime=datetime.fromtimestamp(latest_required_mtime).isoformat(timespec="seconds") if latest_required_mtime else None,
    )


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings()
    count = expected_count(settings)
    contract = Contract()
    payload_rows = validate_payloads(contract, settings, count)
    validate_article_quality(contract, count)
    validate_text_outputs(contract, payload_rows)
    validate_images(contract, count)
    post_ids = validate_wordpress(contract, payload_rows, count)
    validate_drive(contract, payload_rows, count)
    validate_state(contract, payload_rows, post_ids, count)
    validate_notification(contract, args.allow_missing_notification)
    failed = [check for check in contract.checks if check.get("passed") is not True]
    return {
        "status": "ok" if not failed else "partial",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_path": "03_generated/wordpress-payloads/post_payloads_latest.json",
        "manifest_sha256": current_manifest_digest(),
        "expected_article_count": count,
        "failed_count": len(failed),
        "checks": contract.checks,
        "failed_checks": failed,
        "outputs": {
            "json": "07_logs/final_run_contract_latest.json",
            "markdown": "07_logs/final_run_contract_latest.md",
        },
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# 最終契約テスト",
        "",
        f"- ステータス: {payload.get('status')}",
        f"- 検証日時: {payload.get('generated_at')}",
        f"- 期待記事数: {payload.get('expected_article_count')}",
        f"- NG件数: {payload.get('failed_count')}",
        "",
    ]
    failed = payload.get("failed_checks", []) if isinstance(payload.get("failed_checks"), list) else []
    if failed:
        lines.extend(["## NG", ""])
        for item in failed:
            if isinstance(item, dict):
                lines.append(f"- {item.get('name')}: {json.dumps({k: v for k, v in item.items() if k not in {'name', 'passed'}}, ensure_ascii=False)}")
    else:
        lines.append("全チェックOKです。")
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "final_run_contract_latest.json", payload)
    write_json(LOGS_DIR / f"final-run-contract-{timestamp}.json", payload)
    write_markdown(LOGS_DIR / "final_run_contract_latest.md", render_report(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the final run contract before or after notification.")
    parser.add_argument("--allow-missing-notification", action="store_true")
    args = parser.parse_args()
    payload = build_payload(args)
    write_logs(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
