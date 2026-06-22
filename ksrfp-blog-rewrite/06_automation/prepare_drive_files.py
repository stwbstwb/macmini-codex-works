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

from ksrfp_blog_rewrite.drive_package import prepare_drive_files  # noqa: E402
from ksrfp_blog_rewrite.io_utils import read_json, write_json  # noqa: E402
from ksrfp_blog_rewrite.paths import (  # noqa: E402
    ARTICLES_DIR,
    DRIVE_READY_DIR,
    IMAGES_DIR,
    LOGS_DIR,
    REWRITE_BRIEF_DIR,
    ensure_output_dirs,
)
from ksrfp_blog_rewrite.rewrite_history import record_drive_package_ready  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare same-name text and image files for Google Drive upload.")
    parser.add_argument("--article-json", default=str(ARTICLES_DIR / "rewrite_article_latest.json"))
    parser.add_argument("--brief-json", default=str(REWRITE_BRIEF_DIR / "rewrite_brief_latest.json"))
    parser.add_argument("--image-plan-json", default=str(IMAGES_DIR / "featured_image_plan_latest.json"))
    parser.add_argument("--image-path", default=str(IMAGES_DIR / "rewrite_featured_image_latest.png"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        article = read_json(Path(args.article_json), {}) or {}
        brief = read_json(Path(args.brief_json), {}) or {}
        image_plan = read_json(Path(args.image_plan_json), {}) or {}
        image_path = Path(args.image_path)
        if not isinstance(article, dict) or article.get("status") != "ok":
            raise RuntimeError("Rewrite article is missing or not ok. Run generate_rewrite_article.py first.")
        if not isinstance(brief, dict) or brief.get("status") != "ok":
            raise RuntimeError("Rewrite brief is missing or not ok. Run build_rewrite_brief.py first.")
        if not isinstance(image_plan, dict) or image_plan.get("status") != "ok":
            raise RuntimeError("Featured image plan is missing or not ok. Run prepare_featured_image_plan.py first.")
        if not image_path.exists():
            raise RuntimeError(f"Featured image file is missing: {image_path}")

        package = prepare_drive_files(
            article=article,
            brief=brief,
            image_plan=image_plan,
            source_image_path=image_path,
            output_dir=DRIVE_READY_DIR,
        )
        history_updated = record_drive_package_ready(package)
        payload = {
            "status": package["status"],
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "package": package,
            "rewrite_history": {
                "updated": bool(history_updated),
            },
            "outputs": {
                "drive_package_json": "03_generated/drive-ready/drive_package_latest.json",
                "run_log": "07_logs/drive_package_latest.json",
            },
        }
        write_json(DRIVE_READY_DIR / "drive_package_latest.json", package)
        write_json(LOGS_DIR / "drive_package_latest.json", payload)
        write_json(LOGS_DIR / f"drive-package-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if package.get("same_file_base") else 1
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(LOGS_DIR / "drive_package_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
