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

from ksrfp_blog_rewrite.featured_image_plan import build_featured_image_plan  # noqa: E402
from ksrfp_blog_rewrite.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_blog_rewrite.paths import ARTICLES_DIR, IMAGES_DIR, LOGS_DIR, REWRITE_BRIEF_DIR, ensure_output_dirs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the featured image generation prompt for the rewrite article.")
    parser.add_argument("--article-json", default=str(ARTICLES_DIR / "rewrite_article_latest.json"))
    parser.add_argument("--brief-json", default=str(REWRITE_BRIEF_DIR / "rewrite_brief_latest.json"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        article = read_json(Path(args.article_json), {}) or {}
        brief = read_json(Path(args.brief_json), {}) or {}
        if not isinstance(article, dict) or article.get("status") != "ok":
            raise RuntimeError("Rewrite article is missing or not ok. Run generate_rewrite_article.py first.")
        if not isinstance(brief, dict) or brief.get("status") != "ok":
            raise RuntimeError("Rewrite brief is missing or not ok. Run build_rewrite_brief.py first.")

        plan = build_featured_image_plan(article, brief)
        payload = {
            "status": plan["status"],
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "plan": plan,
            "outputs": {
                "image_plan_json": "03_generated/images/featured_image_plan_latest.json",
                "image_prompt": "03_generated/images/featured_image_prompt_latest.md",
                "run_log": "07_logs/featured_image_plan_latest.json",
            },
        }
        write_outputs(payload, plan)
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
        write_json(LOGS_DIR / "featured_image_plan_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


def write_outputs(payload: dict[str, object], plan: dict[str, object]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(IMAGES_DIR / "featured_image_plan_latest.json", plan)
    write_markdown(IMAGES_DIR / "featured_image_prompt_latest.md", str(plan["prompt"]))
    write_json(LOGS_DIR / "featured_image_plan_latest.json", payload)
    write_json(LOGS_DIR / f"featured-image-plan-{timestamp}.json", payload)


if __name__ == "__main__":
    raise SystemExit(main())
