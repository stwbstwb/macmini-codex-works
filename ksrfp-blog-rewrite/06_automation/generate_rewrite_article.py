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

from ksrfp_blog_rewrite.article_generator import generate_rewrite_article  # noqa: E402
from ksrfp_blog_rewrite.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_blog_rewrite.paths import ARTICLES_DIR, LOGS_DIR, OUTLINES_DIR, REWRITE_BRIEF_DIR, ensure_output_dirs  # noqa: E402
from ksrfp_blog_rewrite.rewrite_history import record_article_generated, record_article_generation_failed  # noqa: E402
from ksrfp_blog_rewrite.wordpress_metrics_client import read_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a rewritten article from the latest rewrite brief.")
    parser.add_argument("--brief-json", default=str(REWRITE_BRIEF_DIR / "rewrite_brief_latest.json"))
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        settings = read_settings()
        brief = read_json(Path(args.brief_json), {}) or {}
        if not isinstance(brief, dict) or brief.get("status") != "ok":
            raise RuntimeError("Rewrite brief is missing or not ok. Run build_rewrite_brief.py first.")

        article = generate_rewrite_article(brief, settings)
        quality_gate_passed = bool(article.get("quality_gate", {}).get("passed"))
        if quality_gate_passed:
            history_updated = record_article_generated(article, brief)
        else:
            article["status"] = "quality_gate_failed"
            history_updated = record_article_generation_failed(article, brief)
        payload = {
            "status": "ok" if quality_gate_passed else "quality_gate_failed",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "article": scrub_large_fields(article),
            "rewrite_history": {
                "updated": bool(history_updated),
            },
            "outputs": {
                "article_json": "03_generated/articles/rewrite_article_latest.json",
                "article_markdown": "03_generated/articles/rewrite_article_latest.md",
                "article_text": "03_generated/articles/rewrite_article_latest.txt",
                "outline_json": "03_generated/outlines/rewrite_outline_latest.json",
                "outline_markdown": "03_generated/outlines/rewrite_outline_latest.md",
                "run_log": "07_logs/rewrite_article_latest.json",
            },
        }
        write_outputs(payload, article)
        print(summarize_for_console(payload))
        return 0 if quality_gate_passed else 1
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(LOGS_DIR / "rewrite_article_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


def write_outputs(payload: dict[str, object], article: dict[str, object]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(ARTICLES_DIR / "rewrite_article_latest.json", article)
    write_markdown(ARTICLES_DIR / "rewrite_article_latest.md", str(article["body_markdown"]))
    write_markdown(ARTICLES_DIR / "rewrite_article_latest.txt", str(article["body_text"]))
    write_json(OUTLINES_DIR / "rewrite_outline_latest.json", {"status": "ok", "outline": article["outline"]})
    write_markdown(OUTLINES_DIR / "rewrite_outline_latest.md", render_outline_markdown(article))
    write_json(LOGS_DIR / "rewrite_article_latest.json", payload)
    write_json(LOGS_DIR / f"rewrite-article-{timestamp}.json", payload)


def render_outline_markdown(article: dict[str, object]) -> str:
    lines = [
        "# リライト記事構成",
        "",
        f"- title: {article.get('title')}",
        f"- target_seo_keyword: {article.get('target_seo_keyword')}",
        f"- topic_type: {article.get('topic_type')}",
        "",
    ]
    for section in article.get("outline", []):
        if not isinstance(section, dict):
            continue
        lines.append(f"## {section.get('h2')}")
        for h3 in section.get("h3", []):
            lines.append(f"- {h3}")
        lines.append("")
    return "\n".join(lines)


def scrub_large_fields(article: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in article.items()
        if key not in {"body_markdown", "body_text"}
    }


def summarize_for_console(payload: dict[str, object]) -> str:
    article = payload.get("article", {}) if isinstance(payload.get("article"), dict) else {}
    summary = {
        "status": payload.get("status"),
        "title": article.get("title"),
        "target_seo_keyword": article.get("target_seo_keyword"),
        "topic_type": article.get("topic_type"),
        "quality": article.get("quality"),
        "quality_gate": article.get("quality_gate"),
        "outputs": payload.get("outputs"),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
