#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.artifact_fingerprint import (  # noqa: E402
    manifest_fingerprint,
    payload_matches_current_manifest,
)
from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.review_text import build_review_file_name  # noqa: E402
from ksrfp_jinjiroumu_blog.review_text import upload_review_text  # noqa: E402


def load_settings() -> dict[str, Any]:
    return read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}


def load_wordpress_verification() -> dict[str, Any]:
    return read_json(PROJECT_ROOT / "04_wordpress" / "wordpress_batch_verification_latest.json", {}) or {}


def wordpress_verification_is_current() -> bool:
    verification_path = PROJECT_ROOT / "04_wordpress" / "wordpress_batch_verification_latest.json"
    manifest_path = PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json"
    if not verification_path.exists() or not manifest_path.exists():
        return False
    verification = read_json(verification_path, {}) or {}
    return (
        verification_path.stat().st_mtime + 120 >= manifest_path.stat().st_mtime
        and payload_matches_current_manifest(verification)
    )


def review_text_paths() -> list[Path]:
    manifest = read_json(PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json", {}) or {}
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    if items:
        return [GENERATED_DIR / "review-texts" / f"review_text_item_{index}.json" for index in range(1, len(items) + 1)]
    return sorted((GENERATED_DIR / "review-texts").glob("review_text_item_*.json"), key=item_index_from_path)


def item_index_from_path(path: Path) -> int:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def upload_batch() -> dict[str, Any]:
    settings = load_settings()
    folder_id = str(settings.get("review_text_drive_folder_id") or "")
    verification = load_wordpress_verification()
    verification_current = wordpress_verification_is_current()
    if verification.get("status") != "ok":
        return {
            "status": "blocked_wordpress_not_verified",
            "wordpress_verification_status": verification.get("status"),
            "items": [],
            "reason": "WordPress読み返し検証がOKではないため、Google Drive確認用テキスト保存へ進みません。",
        }
    if not verification_current:
        return {
            "status": "blocked_wordpress_verification_stale",
            "wordpress_verification_status": verification.get("status"),
            "wordpress_verification_current": False,
            "items": [],
            "reason": "WordPress読み返し検証ログが現在の投稿ペイロードより古いため、Google Drive確認用テキスト保存へ進みません。",
        }

    items: list[dict[str, Any]] = []
    for metadata_path in review_text_paths():
        metadata = read_json(metadata_path, {}) or {}
        output_path_text = metadata.get("output_path")
        if not output_path_text:
            items.append(
                {
                    "item_index": item_index_from_path(metadata_path),
                    "status": "blocked",
                    "metadata_path": relative(metadata_path),
                    "reason": "review_text metadata does not include output_path",
                }
            )
            continue
        policy_errors = review_text_policy_errors(metadata)
        if policy_errors:
            items.append(
                {
                    "item_index": item_index_from_path(metadata_path),
                    "status": "blocked_review_text_policy_mismatch",
                    "metadata_path": relative(metadata_path),
                    "file_name": metadata.get("file_name"),
                    "path": output_path_text,
                    "reason": " / ".join(policy_errors),
                }
            )
            continue
        text_path = PROJECT_ROOT / str(output_path_text)
        if not text_path.exists():
            items.append(
                {
                    "item_index": item_index_from_path(metadata_path),
                    "status": "blocked",
                    "metadata_path": relative(metadata_path),
                    "file_name": metadata.get("file_name"),
                    "path": relative(text_path),
                    "reason": "review text file does not exist",
                }
            )
            continue
        upload = upload_review_text(text_path, folder_id)
        metadata.update(manifest_fingerprint())
        metadata["upload"] = upload
        metadata["uploaded_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(metadata_path, metadata)
        item_index = item_index_from_path(metadata_path)
        latest_json = GENERATED_DIR / "review-texts" / f"review_text_item_{item_index}.json"
        if latest_json != metadata_path:
            write_json(latest_json, metadata)
        items.append(
            {
                "item_index": item_index,
                "status": upload.get("status"),
                "metadata_path": relative(metadata_path),
                "file_name": metadata.get("file_name"),
                "path": relative(text_path),
                "file_id": upload.get("file_id"),
                "webViewLink": upload.get("webViewLink"),
                "method": upload.get("method") or ("created_or_updated" if upload.get("status") == "uploaded" else None),
                "reason": upload.get("reason"),
            }
        )

    if items and all(item.get("status") == "uploaded" for item in items):
        status = "ok"
    elif any(item.get("status") == "uploaded" for item in items):
        status = "partial"
    else:
        status = "error" if items else "no_review_texts"
    return {
        "status": status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "drive_folder_id": folder_id,
        "drive_folder_url": f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else "",
        "wordpress_verification_status": verification.get("status"),
        "wordpress_verification_current": verification_current,
        "items": items,
    }


def review_text_policy_errors(metadata: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if metadata.get("file_date_source_type") != "created_at":
        errors.append(f"file_date_source_type_not_created_at:{metadata.get('file_date_source_type')}")
    title = str(metadata.get("title") or "")
    date_source = metadata.get("file_date_source") or metadata.get("generated_at")
    try:
        parsed = datetime.fromisoformat(str(date_source).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        errors.append(f"file_date_source_invalid:{date_source}")
        return errors
    expected_file_name = build_review_file_name(title, now=parsed)
    if metadata.get("file_name") != expected_file_name:
        errors.append(f"file_name_mismatch:actual={metadata.get('file_name')} expected={expected_file_name}")
    output_path = str(metadata.get("output_path") or "")
    if output_path and Path(output_path).name != expected_file_name:
        errors.append(f"output_path_name_mismatch:actual={Path(output_path).name} expected={expected_file_name}")
    return errors


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "review_text_drive_batch_latest.json", payload)
    write_json(LOGS_DIR / f"review-text-drive-batch-{timestamp}.json", payload)
    write_markdown(GENERATED_DIR / "review-texts" / "review_text_drive_batch_latest.md", render_report(payload))


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Google Drive確認用テキスト一括保存",
        "",
        f"- ステータス: {payload.get('status')}",
        f"- WordPress検証: {payload.get('wordpress_verification_status')}",
        f"- Driveフォルダ: {payload.get('drive_folder_url') or '未設定'}",
        "",
    ]
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"## {item.get('item_index')}件目",
                "",
                f"- ステータス: {item.get('status')}",
                f"- ファイル名: {item.get('file_name')}",
                f"- DriveファイルID: {item.get('file_id') or '未取得'}",
                f"- Drive URL: {item.get('webViewLink') or '未取得'}",
                f"- 理由: {item.get('reason') or ''}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload all review text files after WordPress batch verification.")
    parser.parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        result = upload_batch()
        payload = {
            "status": result.get("status"),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            **manifest_fingerprint(),
            "result": result,
            "outputs": {
                "drive_batch_log": "07_logs/review_text_drive_batch_latest.json",
                "drive_batch_report": "03_generated/review-texts/review_text_drive_batch_latest.md",
            },
        }
        write_logs(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 1
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            **manifest_fingerprint(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_logs(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
