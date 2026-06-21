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

from ksrfp_jinjiroumu_blog.external_preflight import run_external_preflight  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import LOGS_DIR  # noqa: E402


def write_log(payload: dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (LOGS_DIR / "external_preflight_command_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (LOGS_DIR / f"external-preflight-command-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production-grade external integration preflight.")
    parser.add_argument("--skip-drive", action="store_true", help="Do not check Google Drive PDF listing/download.")
    parser.add_argument("--skip-smtp-login", action="store_true", help="Do not log in to SMTP during preflight.")
    args = parser.parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        result = run_external_preflight(
            check_drive=not args.skip_drive,
            check_smtp_login=not args.skip_smtp_login,
        )
        payload = {
            "status": result.get("status"),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "result": result,
            "outputs": {
                "preflight_log": "07_logs/external_preflight_latest.json",
                "preflight_report": "04_wordpress/external_preflight_latest.md",
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
