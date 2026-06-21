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

from ksrfp_jinjiroumu_blog.io_utils import read_json  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    apply_arkhe_css_editor,
    build_wordpress_post_verification,
    read_wordpress_credentials,
)


def write_log(payload: dict[str, object]) -> None:
    log_dir = PROJECT_ROOT / "07_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (log_dir / "wordpress_verify_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (log_dir / f"wordpress-verify-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a scheduled WordPress post via REST API.")
    parser.add_argument("--post-id", type=int, default=None, help="WordPress post ID. Defaults to latest publish result.")
    parser.add_argument("--apply-arkhe-css", action="store_true", help="Apply Arkhe CSS Editor meta before verification.")
    args = parser.parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        arkhe_apply_result = None
        if args.apply_arkhe_css:
            if not args.post_id:
                raise RuntimeError("--post-id is required when applying Arkhe CSS.")
            settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
            credentials = read_wordpress_credentials()
            if not credentials.get("ready"):
                raise RuntimeError("WordPress credentials are not ready.")
            arkhe_apply_result = apply_arkhe_css_editor(
                settings,
                credentials["username"],
                credentials["application_password"],
                args.post_id,
                str(settings.get("arkhe_css_editor", "") or ""),
            )
        result = build_wordpress_post_verification(post_id=args.post_id)
        if arkhe_apply_result:
            result["arkhe_apply_result"] = arkhe_apply_result
        payload = {
            "status": result.get("status"),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "result": result,
            "outputs": {
                "verification": "04_wordpress/wordpress_post_verification_latest.md",
                "verification_log": "07_logs/wordpress_verify_latest.json",
            },
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 1
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
