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

from ksrfp_blog_rewrite.io_utils import read_json, to_int, write_json  # noqa: E402
from ksrfp_blog_rewrite.paths import DRIVE_READY_DIR, LOGS_DIR, ensure_output_dirs  # noqa: E402
from ksrfp_blog_rewrite.wordpress_metrics_client import read_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Record Google Drive plugin upload results for the rewrite pipeline.")
    parser.add_argument("--text-file-id", required=True)
    parser.add_argument("--text-url", required=True)
    parser.add_argument("--image-file-id", required=True)
    parser.add_argument("--image-url", required=True)
    parser.add_argument("--folder-id")
    parser.add_argument("--folder-name")
    parser.add_argument("--folder-url")
    parser.add_argument("--text-size-bytes")
    parser.add_argument("--image-size-bytes")
    parser.add_argument("--text-modified-time")
    parser.add_argument("--image-modified-time")
    parser.add_argument("--drive-package-json", default=str(DRIVE_READY_DIR / "drive_package_latest.json"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        settings = read_settings()
        drive_package = read_json(Path(args.drive_package_json), {}) or {}
        if not isinstance(drive_package, dict) or drive_package.get("status") != "ok":
            raise RuntimeError("Drive package is missing or not ok.")

        configured_folder = get_configured_folder(settings)
        folder_id = str(args.folder_id or configured_folder.get("id") or "").strip()
        if configured_folder.get("id") and folder_id != configured_folder.get("id"):
            raise RuntimeError(
                f"Drive upload folder mismatch. expected={configured_folder.get('id')}, actual={folder_id or 'missing'}"
            )

        text_file = drive_package.get("text_file", {}) if isinstance(drive_package.get("text_file"), dict) else {}
        image_file = drive_package.get("image_file", {}) if isinstance(drive_package.get("image_file"), dict) else {}

        payload = {
            "status": "ok",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "method": "google_drive_plugin",
            "folder": {
                "id": folder_id,
                "name": args.folder_name or configured_folder.get("name"),
                "url": args.folder_url or configured_folder.get("url"),
            },
            "source": drive_package.get("source") if isinstance(drive_package.get("source"), dict) else {},
            "text_file": {
                "id": args.text_file_id,
                "name": text_file.get("name"),
                "url": args.text_url,
                "mime_type": "text/plain",
                "size_bytes": choose_size(args.text_size_bytes, text_file.get("size_bytes")),
                "modified_time": args.text_modified_time,
            },
            "image_file": {
                "id": args.image_file_id,
                "name": image_file.get("name"),
                "url": args.image_url,
                "mime_type": "image/png",
                "size_bytes": choose_size(args.image_size_bytes, image_file.get("size_bytes")),
                "modified_time": args.image_modified_time,
            },
            "drive_package_generated_at": drive_package.get("generated_at"),
        }

        write_json(DRIVE_READY_DIR / "drive_upload_latest.json", payload)
        write_json(LOGS_DIR / "drive_upload_latest.json", payload)
        write_json(LOGS_DIR / f"drive-upload-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json", payload)

        result = {
            "status": "ok",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "drive_upload": payload,
            "outputs": {
                "drive_upload_json": str((DRIVE_READY_DIR / "drive_upload_latest.json").relative_to(PROJECT_ROOT)),
                "run_log": str((LOGS_DIR / "drive_upload_latest.json").relative_to(PROJECT_ROOT)),
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(LOGS_DIR / "drive_upload_latest.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


def get_configured_folder(settings: dict[str, Any]) -> dict[str, Any]:
    google_drive = settings.get("google_drive") if isinstance(settings.get("google_drive"), dict) else {}
    folder = google_drive.get("rewrite_output_folder") if isinstance(google_drive.get("rewrite_output_folder"), dict) else {}
    return {
        "id": str(folder.get("id") or "").strip(),
        "name": str(folder.get("name") or "").strip(),
        "url": str(folder.get("url") or "").strip(),
    }


def choose_size(cli_value: Any, package_value: Any) -> int:
    explicit = to_int(cli_value)
    return explicit if explicit else to_int(package_value)


if __name__ == "__main__":
    raise SystemExit(main())
