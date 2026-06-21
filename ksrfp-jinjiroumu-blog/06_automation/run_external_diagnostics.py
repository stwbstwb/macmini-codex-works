#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.drive_client import build_drive_status  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import build_wordpress_readonly_check  # noqa: E402


def write_log(payload: dict[str, object]) -> None:
    log_dir = PROJECT_ROOT / "07_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (log_dir / "external_diagnostics_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (log_dir / f"external-diagnostics-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        drive = build_drive_status()
        wordpress = build_wordpress_readonly_check()
        payload = {
            "status": "ok" if drive.get("status") == "ok" and wordpress.get("status") == "ok" else "partial",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "drive_status": drive.get("status"),
            "drive_pdf_count": drive.get("drive_pdf_count"),
            "latest_drive_pdf": (drive.get("latest_drive_pdf") or {}).get("name"),
            "downloaded_pdf_status": (drive.get("downloaded_pdf") or {}).get("status"),
            "wordpress_status": wordpress.get("status"),
            "wordpress_connection_ok": (wordpress.get("connection") or {}).get("ok"),
            "wordpress_category_count": len(wordpress.get("categories", [])),
            "wordpress_tags_checked": wordpress.get("tags_checked"),
            "wordpress_future_posts_count": wordpress.get("future_posts_count"),
            "outputs": {
                "drive_status": "05_drive/drive_status_latest.md",
                "wordpress_readonly_check": "04_wordpress/wordpress_readonly_check_latest.md",
                "external_diagnostics_log": "07_logs/external_diagnostics_latest.json",
            },
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "ok" else 1
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
