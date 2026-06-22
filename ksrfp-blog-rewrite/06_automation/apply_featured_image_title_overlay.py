#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_blog_rewrite.image_title_overlay import apply_title_overlay  # noqa: E402
from ksrfp_blog_rewrite.io_utils import read_json, write_json  # noqa: E402
from ksrfp_blog_rewrite.paths import ARTICLES_DIR, IMAGES_DIR, LOGS_DIR, ensure_output_dirs  # noqa: E402
from ksrfp_blog_rewrite.wordpress_metrics_client import read_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the article title overlay to the generated featured image.")
    parser.add_argument("--article-json", default=str(ARTICLES_DIR / "rewrite_article_latest.json"))
    parser.add_argument("--image-plan-json", default=str(IMAGES_DIR / "featured_image_plan_latest.json"))
    parser.add_argument("--image-path", default=str(IMAGES_DIR / "rewrite_featured_image_latest.png"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        settings = read_settings()
        article = read_json(Path(args.article_json), {}) or {}
        image_plan = read_json(Path(args.image_plan_json), {}) or {}
        previous_overlay = read_json(IMAGES_DIR / "featured_image_overlay_latest.json", {}) or {}
        if not isinstance(article, dict) or article.get("status") != "ok":
            raise RuntimeError("Rewrite article is missing or not ok.")
        if not isinstance(image_plan, dict) or image_plan.get("status") != "ok":
            raise RuntimeError("Featured image plan is missing or not ok.")

        featured_settings = settings.get("featured_image") if isinstance(settings.get("featured_image"), dict) else {}
        overlay_settings = featured_settings.get("title_overlay") if isinstance(featured_settings.get("title_overlay"), dict) else {}
        width = int(featured_settings.get("width") or 1200)
        height = int(featured_settings.get("height") or 630)
        image_path = Path(args.image_path)
        result = apply_title_overlay(
            image_path=image_path,
            title=str(article.get("title") or image_plan.get("title") or ""),
            overlay_settings=overlay_settings,
            width=width,
            height=height,
            background_path=IMAGES_DIR / "rewrite_featured_image_background_latest.png",
            previous_overlay=previous_overlay if isinstance(previous_overlay, dict) else {},
        )
        if result.get("status") != "ok":
            raise RuntimeError(str(result.get("reason") or "Failed to apply title overlay."))

        file_base = str(image_plan.get("file_base") or article.get("title") or "rewrite_article")
        named_image_path = IMAGES_DIR / f"{file_base}.png"
        shutil.copy2(image_path, named_image_path)
        result["named_image_path"] = str(named_image_path)

        payload = {
            "status": "ok",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "overlay": result,
            "outputs": {
                "image_path": str(image_path.relative_to(PROJECT_ROOT)),
                "named_image_path": str(named_image_path.relative_to(PROJECT_ROOT)),
                "overlay_json": "03_generated/images/featured_image_overlay_latest.json",
                "run_log": "07_logs/featured_image_overlay_latest.json",
            },
        }
        write_json(IMAGES_DIR / "featured_image_overlay_latest.json", result)
        write_json(LOGS_DIR / "featured_image_overlay_latest.json", payload)
        write_json(LOGS_DIR / f"featured-image-overlay-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json", payload)
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
        write_json(LOGS_DIR / "featured_image_overlay_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
