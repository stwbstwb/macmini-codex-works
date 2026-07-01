#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
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


def drive_id_from_url(url: str) -> str:
    if "/d/" in url:
        return url.split("/d/", 1)[1].split("/", 1)[0]
    if "id=" in url:
        return url.split("id=", 1)[1].split("&", 1)[0]
    return ""


def wordpress_verification_ready() -> dict[str, Any]:
    verification_path = PROJECT_ROOT / "04_wordpress" / "wordpress_batch_verification_latest.json"
    manifest_path = PROJECT_ROOT / "03_generated" / "wordpress-payloads" / "post_payloads_latest.json"
    verification = read_json(verification_path, {}) or {}
    current = (
        verification_path.exists()
        and manifest_path.exists()
        and verification_path.stat().st_mtime + 120 >= manifest_path.stat().st_mtime
        and payload_matches_current_manifest(verification)
    )
    return {
        "ready": verification.get("status") == "ok" and current,
        "status": verification.get("status"),
        "current": current,
        "path": relative(verification_path),
    }


def parse_mapping(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"Invalid mapping: {value}")
    file_name, url = value.split("=", 1)
    file_name = file_name.strip()
    url = url.strip()
    if not file_name or not url:
        raise ValueError(f"Invalid mapping: {value}")
    return file_name, url


def record_uploads(values: list[str]) -> dict[str, Any]:
    verification = wordpress_verification_ready()
    if not verification.get("ready"):
        return {
            "status": "blocked_wordpress_not_verified",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            **manifest_fingerprint(),
            "wordpress_verification": verification,
            "items": [],
            "unmatched_mappings": [],
            "reason": "WordPress読み返し検証が現在の投稿ペイロードに対してOKではないため、Drive URLを記録しません。",
        }
    mappings = dict(parse_mapping(value) for value in values)
    items: list[dict[str, Any]] = []
    for path in current_review_text_paths():
        payload = read_json(path, {}) or {}
        file_name = str(payload.get("file_name") or "")
        policy_errors = review_text_policy_errors(payload)
        if policy_errors:
            items.append(
                {
                    "item_index": item_index_from_path(path),
                    "status": "blocked_review_text_policy_mismatch",
                    "file_name": file_name,
                    "metadata_path": relative(path),
                    "reason": " / ".join(policy_errors),
                }
            )
            continue
        if file_name not in mappings:
            items.append(
                {
                    "item_index": item_index_from_path(path),
                    "status": "not_updated",
                    "file_name": file_name,
                    "metadata_path": relative(path),
                    "reason": "mapping not provided",
                }
            )
            continue
        url = mappings[file_name]
        file_id = drive_id_from_url(url)
        if not file_id:
            items.append(
                {
                    "item_index": item_index_from_path(path),
                    "status": "blocked",
                    "file_name": file_name,
                    "metadata_path": relative(path),
                    "webViewLink": url,
                    "reason": "Drive URLからファイルIDを取得できません。",
                }
            )
            continue
        upload = {
            "status": "uploaded",
            "method": "google_drive_plugin",
            "file_id": file_id,
            "name": file_name,
            "webViewLink": url,
        }
        payload.update(manifest_fingerprint())
        payload["upload"] = upload
        payload["uploaded_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(path, payload)
        items.append(
            {
                "item_index": item_index_from_path(path),
                "status": "uploaded",
                "file_name": file_name,
                "metadata_path": relative(path),
                "file_id": upload["file_id"],
                "webViewLink": url,
            }
        )

    missing = sorted(set(mappings) - {str(item.get("file_name") or "") for item in items})
    status = "ok" if items and all(item.get("status") == "uploaded" for item in items) and not missing else "partial"
    return {
        "status": status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **manifest_fingerprint(),
        "wordpress_verification": verification,
        "items": items,
        "unmatched_mappings": missing,
    }


def review_text_policy_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("file_date_source_type") != "created_at":
        errors.append(f"file_date_source_type_not_created_at:{payload.get('file_date_source_type')}")
    title = str(payload.get("title") or "")
    date_source = payload.get("file_date_source") or payload.get("generated_at")
    try:
        parsed = datetime.fromisoformat(str(date_source).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        errors.append(f"file_date_source_invalid:{date_source}")
        return errors
    expected_file_name = build_review_file_name(title, now=parsed)
    if payload.get("file_name") != expected_file_name:
        errors.append(f"file_name_mismatch:actual={payload.get('file_name')} expected={expected_file_name}")
    output_path = str(payload.get("output_path") or "")
    if output_path and Path(output_path).name != expected_file_name:
        errors.append(f"output_path_name_mismatch:actual={Path(output_path).name} expected={expected_file_name}")
    return errors


def current_review_text_paths() -> list[Path]:
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


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "review_text_drive_plugin_latest.json", payload)
    write_json(LOGS_DIR / f"review-text-drive-plugin-{timestamp}.json", payload)
    write_markdown(GENERATED_DIR / "review-texts" / "review_text_drive_plugin_latest.md", render_report(payload))


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Google Driveプラグイン保存結果記録",
        "",
        f"- ステータス: {payload.get('status')}",
        f"- 生成日時: {payload.get('generated_at')}",
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
                f"- Drive URL: {item.get('webViewLink') or '未記録'}",
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
    parser = argparse.ArgumentParser(description="Record Google Drive plugin upload URLs into review_text_item metadata.")
    parser.add_argument(
        "--drive-upload",
        action="append",
        required=True,
        help="Mapping in the form 'file_name=url'. Repeat for each uploaded review text.",
    )
    args = parser.parse_args()
    payload = record_uploads(args.drive_upload)
    write_logs(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
