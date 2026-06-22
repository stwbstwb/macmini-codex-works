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

from ksrfp_blog_rewrite.candidate_selector import render_candidate_report, select_rewrite_candidate  # noqa: E402
from ksrfp_blog_rewrite.io_utils import write_json, write_markdown  # noqa: E402
from ksrfp_blog_rewrite.paths import LOGS_DIR, REWRITE_CANDIDATE_DIR, ensure_output_dirs  # noqa: E402
from ksrfp_blog_rewrite.rewrite_history import (  # noqa: E402
    load_rewrite_history,
    record_selected_candidate,
    rewritten_post_ids,
)
from ksrfp_blog_rewrite.wordpress_metrics_client import (  # noqa: E402
    WordPressMetricsClient,
    read_settings,
    read_wordpress_credentials,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Select one rewrite candidate from WordPress metrics.")
    parser.add_argument("--include-content", action="store_true", help="Fetch raw post content from the metrics endpoint.")
    parser.add_argument("--ignore-history", action="store_true", help="Allow selecting posts that are already in rewrite history.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write the selected candidate to rewrite history.")
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()

    try:
        settings = read_settings()
        selection_settings = settings.get("candidate_selection", {})
        credentials = read_wordpress_credentials(settings)
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")

        endpoint = str(settings.get("wordpress_metrics_endpoint") or "").strip()
        if not endpoint:
            raise RuntimeError("wordpress_metrics_endpoint is not configured.")

        client = WordPressMetricsClient(
            endpoint,
            str(credentials["username"]),
            str(credentials["application_password"]),
        )
        metrics = client.fetch_all_posts(
            post_type=str(selection_settings.get("post_type") or "post"),
            status=str(selection_settings.get("status") or "publish"),
            per_page=int(selection_settings.get("per_page") or 100),
            days=int(selection_settings.get("recent_views_days") or 30),
            include_content=args.include_content,
        )
        history = load_rewrite_history()
        history_post_ids = rewritten_post_ids(history)
        selection = select_rewrite_candidate(
            metrics["items"],
            settings,
            rewrite_history_post_ids=history_post_ids,
            ignore_history=args.ignore_history,
        )
        history_updated = None
        if selection["status"] == "ok" and not args.ignore_history and not args.dry_run:
            history_updated = record_selected_candidate(selection)
        outputs = build_outputs(args.dry_run)
        payload = {
            "status": selection["status"],
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "metrics_source": metrics.get("source", {}),
            "metrics_pagination": metrics.get("pagination", {}),
            "selection": selection,
            "rewrite_history": {
                "enabled": not args.ignore_history,
                "dry_run": bool(args.dry_run),
                "known_post_ids": sorted(history_post_ids),
                "updated": bool(history_updated),
            },
            "outputs": outputs,
        }
        write_outputs(payload, dry_run=args.dry_run)
        print(summarize_for_console(payload))
        return 0 if selection["status"] == "ok" else 1
    except Exception as exc:
        payload = {
            "status": "error",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json(LOGS_DIR / "rewrite_candidate_select_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1


def build_outputs(dry_run: bool) -> dict[str, str]:
    if dry_run:
        return {
            "dry_run_log": "07_logs/rewrite_candidate_select_dry_run_latest.json",
        }
    return {
        "candidate_json": "02_analysis/rewrite-candidates/rewrite_candidate_latest.json",
        "candidate_report": "02_analysis/rewrite-candidates/rewrite_candidate_latest.md",
        "run_log": "07_logs/rewrite_candidate_select_latest.json",
    }


def write_outputs(payload: dict[str, object], *, dry_run: bool = False) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if dry_run:
        write_json(LOGS_DIR / "rewrite_candidate_select_dry_run_latest.json", payload)
        write_json(LOGS_DIR / f"rewrite-candidate-select-dry-run-{timestamp}.json", payload)
        return

    selection = payload.get("selection", {}) if isinstance(payload.get("selection"), dict) else {}

    write_json(REWRITE_CANDIDATE_DIR / "rewrite_candidate_latest.json", selection)
    write_markdown(REWRITE_CANDIDATE_DIR / "rewrite_candidate_latest.md", render_candidate_report(selection))
    write_json(LOGS_DIR / "rewrite_candidate_select_latest.json", payload)
    write_json(LOGS_DIR / f"rewrite-candidate-select-{timestamp}.json", payload)


def summarize_for_console(payload: dict[str, object]) -> str:
    selection = payload.get("selection", {}) if isinstance(payload.get("selection"), dict) else {}
    selected = selection.get("selected", {}) if isinstance(selection.get("selected"), dict) else {}
    summary = {
        "status": payload.get("status"),
        "fetched_items": (payload.get("metrics_pagination") or {}).get("fetched_items")
        if isinstance(payload.get("metrics_pagination"), dict)
        else None,
        "eligible_items": (selection.get("counts") or {}).get("eligible_items") if isinstance(selection.get("counts"), dict) else None,
        "excluded_items": (selection.get("counts") or {}).get("excluded_items") if isinstance(selection.get("counts"), dict) else None,
        "rewrite_history_excluded_post_count": (selection.get("settings") or {}).get("rewrite_history_excluded_post_count")
        if isinstance(selection.get("settings"), dict)
        else None,
        "selected": {
            "post_id": selected.get("post_id"),
            "title": selected.get("title"),
            "score": selected.get("score"),
            "views_total": selected.get("views_total"),
            "views_recent": selected.get("views_recent"),
            "computed_character_count": selected.get("computed_character_count"),
            "h2_count": selected.get("h2_count"),
            "h3_count": selected.get("h3_count"),
        },
        "outputs": payload.get("outputs"),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
