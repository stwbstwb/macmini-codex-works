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

from ksrfp_jinjiroumu_blog.paths import LOGS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.review_text import build_review_text_file  # noqa: E402


def write_log(payload: dict[str, object]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (LOGS_DIR / "review_text_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (LOGS_DIR / f"review-text-{timestamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a review text file for non-WordPress reviewers.")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Deprecated. Drive upload is only allowed through run_review_text_batch_upload.py after WordPress verification.",
    )
    args = parser.parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    if args.upload:
        payload = {
            "status": "blocked_deprecated_upload_entrypoint",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": (
                "確認用テキストのGoogle Drive保存は、WordPress下書き保存と読み返し検証後に "
                "06_automation/run_review_text_batch_upload.py からのみ実行できます。"
            ),
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    try:
        result = build_review_text_file(upload=False)
        payload = {
            "status": result.get("status"),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "result": result,
            "outputs": {
                "review_text": result.get("output_path"),
                "review_text_report": "03_generated/review-texts/review_text_latest.md",
                "log": "07_logs/review_text_latest.json",
            },
        }
        write_log(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
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
