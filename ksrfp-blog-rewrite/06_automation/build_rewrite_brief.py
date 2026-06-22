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

from ksrfp_blog_rewrite.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_blog_rewrite.paths import (  # noqa: E402
    LOGS_DIR,
    OUTLINES_DIR,
    REWRITE_BRIEF_DIR,
    REWRITE_CANDIDATE_DIR,
    ensure_output_dirs,
)
from ksrfp_blog_rewrite.rewrite_brief import build_rewrite_brief, render_rewrite_brief  # noqa: E402
from ksrfp_blog_rewrite.wordpress_metrics_client import read_settings, read_wordpress_credentials  # noqa: E402
from ksrfp_blog_rewrite.wordpress_post_client import fetch_wordpress_post  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a rewrite brief from the selected past article.")
    parser.add_argument("--candidate-json", default=str(REWRITE_CANDIDATE_DIR / "rewrite_candidate_latest.json"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        settings = read_settings()
        credentials = read_wordpress_credentials(settings)
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")

        candidate_payload = read_json(Path(args.candidate_json), {}) or {}
        candidate = candidate_payload.get("selected") if isinstance(candidate_payload, dict) else None
        if not isinstance(candidate, dict) or not candidate.get("post_id"):
            raise RuntimeError("Selected rewrite candidate is missing. Run select_rewrite_candidate.py first.")

        api_base = str(settings.get("wordpress_api_base") or "").strip()
        if not api_base:
            raise RuntimeError("wordpress_api_base is not configured.")

        post = fetch_wordpress_post(
            api_base,
            str(credentials["username"]),
            str(credentials["application_password"]),
            int(candidate["post_id"]),
        )
        brief = build_rewrite_brief(candidate=candidate, post=post, settings=settings)
        payload = {
            "status": brief["status"],
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "brief": brief,
            "outputs": {
                "rewrite_brief_json": "03_generated/rewrite-briefs/rewrite_brief_latest.json",
                "rewrite_brief_report": "03_generated/rewrite-briefs/rewrite_brief_latest.md",
                "article_brief_compat_json": "03_generated/outlines/article_brief_latest.json",
                "article_brief_compat_md": "03_generated/outlines/article_brief_latest.md",
                "run_log": "07_logs/rewrite_brief_latest.json",
            },
        }
        write_outputs(payload)
        print(summarize_for_console(payload))
        return 0
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(LOGS_DIR / "rewrite_brief_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


def write_outputs(payload: dict[str, object]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    brief = payload.get("brief", {}) if isinstance(payload.get("brief"), dict) else {}
    report = render_rewrite_brief(brief)

    write_json(REWRITE_BRIEF_DIR / "rewrite_brief_latest.json", brief)
    write_markdown(REWRITE_BRIEF_DIR / "rewrite_brief_latest.md", report)
    write_json(OUTLINES_DIR / "article_brief_latest.json", brief)
    write_markdown(OUTLINES_DIR / "article_brief_latest.md", report)
    write_json(LOGS_DIR / "rewrite_brief_latest.json", payload)
    write_json(LOGS_DIR / f"rewrite-brief-{timestamp}.json", payload)


def summarize_for_console(payload: dict[str, object]) -> str:
    brief = payload.get("brief", {}) if isinstance(payload.get("brief"), dict) else {}
    source = brief.get("source", {}) if isinstance(brief.get("source"), dict) else {}
    extraction = brief.get("extraction", {}) if isinstance(brief.get("extraction"), dict) else {}
    summary = {
        "status": payload.get("status"),
        "source": {
            "post_id": source.get("post_id"),
            "title": source.get("title"),
            "url": source.get("url"),
        },
        "extraction": {
            "rewrite_theme": extraction.get("rewrite_theme"),
            "target_seo_keyword": extraction.get("target_seo_keyword"),
            "related_keywords": extraction.get("related_keywords"),
            "target_reader": extraction.get("target_reader"),
            "confidence": extraction.get("confidence"),
        },
        "outputs": payload.get("outputs"),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
