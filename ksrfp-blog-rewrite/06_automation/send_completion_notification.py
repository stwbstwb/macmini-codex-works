#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_blog_rewrite.io_utils import read_json, write_json  # noqa: E402
from ksrfp_blog_rewrite.notification import send_completion_notification  # noqa: E402
from ksrfp_blog_rewrite.paths import ARTICLES_DIR, DRIVE_READY_DIR, LOGS_DIR, ensure_output_dirs  # noqa: E402
from ksrfp_blog_rewrite.wordpress_metrics_client import read_settings  # noqa: E402


def validate_drive_upload_destination(settings: dict[str, object], drive_upload: dict[str, object]) -> None:
    google_drive = settings.get("google_drive") if isinstance(settings.get("google_drive"), dict) else {}
    folder = google_drive.get("rewrite_output_folder") if isinstance(google_drive.get("rewrite_output_folder"), dict) else {}
    expected_id = str(folder.get("id") or "").strip()
    actual_folder = drive_upload.get("folder") if isinstance(drive_upload.get("folder"), dict) else {}
    actual_id = str(actual_folder.get("id") or drive_upload.get("folder_id") or "").strip()
    if expected_id and actual_id != expected_id:
        raise RuntimeError(
            f"Drive upload folder mismatch. expected={expected_id}, actual={actual_id or 'missing'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send completion notification for the rewrite run.")
    parser.add_argument("--article-json", default=str(ARTICLES_DIR / "rewrite_article_latest.json"))
    parser.add_argument("--drive-package-json", default=str(DRIVE_READY_DIR / "drive_package_latest.json"))
    parser.add_argument("--drive-upload-json", default=str(DRIVE_READY_DIR / "drive_upload_latest.json"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        settings = read_settings()
        article = read_json(Path(args.article_json), {}) or {}
        drive_package = read_json(Path(args.drive_package_json), {}) or {}
        drive_upload = read_json(Path(args.drive_upload_json), {}) or {}
        if not isinstance(article, dict) or article.get("status") != "ok":
            raise RuntimeError("Rewrite article is missing or not ok.")
        if not isinstance(drive_package, dict) or drive_package.get("status") != "ok":
            raise RuntimeError("Drive package is missing or not ok.")
        if not isinstance(drive_upload, dict) or drive_upload.get("status") != "ok":
            raise RuntimeError("Drive upload log is missing or not ok.")
        validate_drive_upload_destination(settings, drive_upload)

        notification = send_completion_notification(
            settings=settings,
            article=article,
            drive_package=drive_package,
            drive_upload=drive_upload,
        )
        payload = {
            "status": "ok" if notification.get("status") == "sent" else "partial",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "notification": notification,
        }
        write_json(LOGS_DIR / "send_completion_notification_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if notification.get("status") == "sent" else 1
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(LOGS_DIR / "send_completion_notification_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
