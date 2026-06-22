#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_blog_rewrite.io_utils import read_json, write_json  # noqa: E402
from ksrfp_blog_rewrite.notification import send_pipeline_status_notification  # noqa: E402
from ksrfp_blog_rewrite.paths import DRIVE_READY_DIR, IMAGES_DIR, LOGS_DIR, ensure_output_dirs  # noqa: E402
from ksrfp_blog_rewrite.wordpress_metrics_client import read_settings  # noqa: E402


SCRIPTABLE_STEPS = [
    ("select_candidate", "06_automation/select_rewrite_candidate.py"),
    ("build_brief", "06_automation/build_rewrite_brief.py"),
    ("generate_article", "06_automation/generate_rewrite_article.py"),
    ("prepare_image_plan", "06_automation/prepare_featured_image_plan.py"),
]

DRIVE_PACKAGE_STEP = ("prepare_drive_files", "06_automation/prepare_drive_files.py")
NOTIFICATION_STEP = ("send_completion_notification", "06_automation/send_completion_notification.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the scriptable ksrfp blog rewrite pipeline.")
    parser.add_argument(
        "--send-notification",
        action="store_true",
        help="Send the completion email after a successful Drive upload log is available.",
    )
    parser.add_argument(
        "--send-status-notification",
        action="store_true",
        help="Send an email when the pipeline stops with a needs-action or error status.",
    )
    args = parser.parse_args()

    started_at = datetime.now().isoformat(timespec="seconds")
    ensure_output_dirs()
    steps: list[dict[str, Any]] = []

    try:
        for step_name, script in SCRIPTABLE_STEPS:
            step = run_step(step_name, script)
            steps.append(step)
            if step["status"] != "ok":
                return finish(
                    status="error",
                    started_at=started_at,
                    steps=steps,
                    message=f"Step failed: {step_name}",
                    return_code=1,
                    send_status_notification=args.send_status_notification,
                )

        image_path = IMAGES_DIR / "rewrite_featured_image_latest.png"
        image_plan_path = IMAGES_DIR / "featured_image_plan_latest.json"
        image_plan = read_json(image_plan_path, {}) or {}
        image_validation = validate_featured_image(image_path, image_plan)
        if image_validation["status"] != "ok":
            steps.append(
                {
                    "name": "check_featured_image",
                    "status": image_validation["status"],
                    "message": "Generate the featured image from 03_generated/images/featured_image_prompt_latest.md, then save it as 03_generated/images/rewrite_featured_image_latest.png.",
                    "expected_path": str(image_path.relative_to(PROJECT_ROOT)),
                    "validation": image_validation,
                }
            )
            return finish(
                status="needs_image_generation",
                started_at=started_at,
                steps=steps,
                message="The scriptable pipeline needs the Codex image generation tool for the next action.",
                return_code=2,
                send_status_notification=args.send_status_notification,
            )

        steps.append(
            {
                "name": "check_featured_image",
                "status": "ok",
                "path": str(image_path.relative_to(PROJECT_ROOT)),
                "size_bytes": image_path.stat().st_size,
                "validation": image_validation,
            }
        )

        drive_step = run_step(*DRIVE_PACKAGE_STEP)
        steps.append(drive_step)
        if drive_step["status"] != "ok":
            return finish(
                status="error",
                started_at=started_at,
                steps=steps,
                message="Drive-ready file preparation failed.",
                return_code=1,
                send_status_notification=args.send_status_notification,
            )

        drive_upload_path = DRIVE_READY_DIR / "drive_upload_latest.json"
        drive_package_path = DRIVE_READY_DIR / "drive_package_latest.json"
        drive_upload = read_json(drive_upload_path, {}) or {}
        drive_package = read_json(drive_package_path, {}) or {}
        upload_validation = validate_drive_upload(drive_upload, drive_package, read_settings())
        if upload_validation["status"] != "ok":
            steps.append(
                {
                    "name": "check_drive_upload",
                    "status": upload_validation["status"],
                    "message": "Upload the same-name text and image files in 03_generated/drive-ready/ to the configured Google Drive folder, then write/update 03_generated/drive-ready/drive_upload_latest.json.",
                    "expected_log": str(drive_upload_path.relative_to(PROJECT_ROOT)),
                    "validation": upload_validation,
                }
            )
            return finish(
                status="needs_drive_upload",
                started_at=started_at,
                steps=steps,
                message="The scriptable pipeline needs the Codex Google Drive plugin for the next action.",
                return_code=3,
                send_status_notification=args.send_status_notification,
            )

        steps.append(
            {
                "name": "check_drive_upload",
                "status": "ok",
                "path": str(drive_upload_path.relative_to(PROJECT_ROOT)),
                "folder_url": (drive_upload.get("folder") or {}).get("url")
                if isinstance(drive_upload.get("folder"), dict)
                else drive_upload.get("folder_url"),
                "validation": upload_validation,
            }
        )

        if args.send_notification:
            notification_step = run_step(*NOTIFICATION_STEP)
            steps.append(notification_step)
            if notification_step["status"] != "ok":
                return finish(
                    status="partial",
                    started_at=started_at,
                    steps=steps,
                    message="Pipeline completed, but the notification email failed.",
                    return_code=4,
                    send_status_notification=args.send_status_notification,
                )
        else:
            steps.append(
                {
                    "name": "send_completion_notification",
                    "status": "skipped",
                    "message": "Pass --send-notification to send the completion email.",
                }
            )

        return finish(
            status="ok",
            started_at=started_at,
            steps=steps,
            message="Pipeline completed.",
            return_code=0,
            send_status_notification=args.send_status_notification,
        )
    except Exception as exc:
        return finish(
            status="error",
            started_at=started_at,
            steps=steps,
            message=str(exc),
            return_code=1,
            extra={"traceback": traceback.format_exc()},
            send_status_notification=args.send_status_notification,
        )


def run_step(name: str, script: str) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    process = subprocess.run(
        [sys.executable, script],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    step: dict[str, Any] = {
        "name": name,
        "script": script,
        "status": "ok" if process.returncode == 0 else "error",
        "return_code": process.returncode,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    if process.stdout.strip():
        step["stdout"] = parse_json_or_text(process.stdout)
    if process.stderr.strip():
        step["stderr"] = process.stderr.strip()
    return step


def parse_json_or_text(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return stripped


def validate_featured_image(image_path: Path, image_plan: Any) -> dict[str, Any]:
    if not image_path.exists():
        return {"status": "needs_image_generation", "reason": "Featured image file is missing."}
    if not isinstance(image_plan, dict) or image_plan.get("status") != "ok":
        return {"status": "needs_image_generation", "reason": "featured_image_plan_latest.json is missing or not ok."}

    plan_timestamp = parse_iso_timestamp(image_plan.get("generated_at"))
    if plan_timestamp is not None and image_path.stat().st_mtime < plan_timestamp:
        return {
            "status": "needs_image_generation",
            "reason": "Featured image is older than the latest image plan.",
            "image_mtime": image_path.stat().st_mtime,
            "plan_timestamp": plan_timestamp,
        }

    return {
        "status": "ok",
        "image_file": image_path.name,
        "image_mtime": image_path.stat().st_mtime,
        "plan_generated_at": image_plan.get("generated_at"),
    }


def validate_drive_upload(drive_upload: Any, drive_package: Any, settings: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(drive_upload, dict) or drive_upload.get("status") != "ok":
        return {"status": "needs_drive_upload", "reason": "drive_upload_latest.json is missing or not ok."}
    if not isinstance(drive_package, dict) or drive_package.get("status") != "ok":
        return {"status": "needs_drive_upload", "reason": "drive_package_latest.json is missing or not ok."}

    expected_text = nested_value(drive_package, "text_file", "name")
    expected_image = nested_value(drive_package, "image_file", "name")
    uploaded_text = nested_value(drive_upload, "text_file", "name")
    uploaded_image = nested_value(drive_upload, "image_file", "name")
    expected_source_post_id = nested_value(drive_package, "source", "post_id")
    uploaded_source_post_id = nested_value(drive_upload, "source", "post_id") or drive_upload.get("source_post_id")
    expected_folder = nested_value(settings, "google_drive", "rewrite_output_folder")
    expected_folder_id = expected_folder.get("id") if isinstance(expected_folder, dict) else None
    actual_folder_id = nested_value(drive_upload, "folder", "id") or drive_upload.get("folder_id")

    if expected_folder_id and actual_folder_id != expected_folder_id:
        return {
            "status": "needs_drive_upload",
            "reason": "Drive upload log folder does not match the configured rewrite output folder.",
            "expected_folder": expected_folder,
            "actual_folder_id": actual_folder_id,
            "actual_folder_name": nested_value(drive_upload, "folder", "name"),
        }

    mismatches = []
    if expected_text != uploaded_text:
        mismatches.append({"field": "text_file.name", "expected": expected_text, "actual": uploaded_text})
    if expected_image != uploaded_image:
        mismatches.append({"field": "image_file.name", "expected": expected_image, "actual": uploaded_image})
    if expected_source_post_id and str(expected_source_post_id) != str(uploaded_source_post_id or ""):
        mismatches.append(
            {
                "field": "source.post_id",
                "expected": expected_source_post_id,
                "actual": uploaded_source_post_id,
            }
        )
    size_mismatches = compare_uploaded_sizes(drive_upload, drive_package)
    mismatches.extend(size_mismatches)
    if mismatches:
        return {
            "status": "needs_drive_upload",
            "reason": "Drive upload log does not match the current drive-ready package.",
            "mismatches": mismatches,
        }

    warnings = []
    package_timestamp = parse_iso_timestamp(drive_package.get("generated_at"))
    upload_timestamp = parse_iso_timestamp(drive_upload.get("generated_at"))
    if package_timestamp is not None and upload_timestamp is not None and upload_timestamp < package_timestamp:
        warnings.append(
            {
                "reason": "Drive upload log is older than the latest drive-ready package timestamp, but names, source post, folder, and sizes match.",
                "package_generated_at": drive_package.get("generated_at"),
                "upload_generated_at": drive_upload.get("generated_at"),
            }
        )

    result = {
        "status": "ok",
        "text_file": uploaded_text,
        "image_file": uploaded_image,
        "folder_id": actual_folder_id,
        "source_post_id": uploaded_source_post_id,
        "package_generated_at": drive_package.get("generated_at"),
        "upload_generated_at": drive_upload.get("generated_at"),
    }
    if warnings:
        result["warnings"] = warnings
    return result


def compare_uploaded_sizes(drive_upload: dict[str, Any], drive_package: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches = []
    pairs = [
        ("text_file.size_bytes", nested_value(drive_package, "text_file", "size_bytes"), nested_value(drive_upload, "text_file", "size_bytes")),
        ("image_file.size_bytes", nested_value(drive_package, "image_file", "size_bytes"), nested_value(drive_upload, "image_file", "size_bytes")),
    ]
    for field, expected, actual in pairs:
        expected_int = to_optional_int(expected)
        actual_int = to_optional_int(actual)
        if expected_int is not None and actual_int is not None and expected_int != actual_int:
            mismatches.append({"field": field, "expected": expected_int, "actual": actual_int})
    return mismatches


def nested_value(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_iso_timestamp(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def finish(
    *,
    status: str,
    started_at: str,
    steps: list[dict[str, Any]],
    message: str,
    return_code: int,
    extra: dict[str, Any] | None = None,
    send_status_notification: bool = False,
) -> int:
    payload: dict[str, Any] = {
        "status": status,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "message": message,
        "steps": steps,
    }
    if extra:
        payload.update(extra)
    if send_status_notification and status != "ok":
        try:
            payload["status_notification"] = send_pipeline_status_notification(
                settings=read_settings(),
                pipeline_result=payload,
            )
        except Exception as exc:
            payload["status_notification"] = {
                "status": "not_sent",
                "message": str(exc),
            }
    write_json(LOGS_DIR / "rewrite_pipeline_latest.json", payload)
    write_json(LOGS_DIR / f"rewrite-pipeline-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json", payload)
    print(json.dumps(scrub_for_console(payload), ensure_ascii=False, indent=2))
    return return_code


def scrub_for_console(payload: dict[str, Any]) -> dict[str, Any]:
    compact_steps = []
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        compact = {key: value for key, value in step.items() if key not in {"stdout", "stderr"}}
        stdout = step.get("stdout")
        if isinstance(stdout, dict):
            compact["stdout_summary"] = {
                key: stdout.get(key)
                for key in ("status", "title", "target_seo_keyword", "source", "selected", "outputs")
                if key in stdout
            }
        elif isinstance(stdout, str):
            compact["stdout_summary"] = stdout[:500]
        if step.get("stderr"):
            compact["stderr_present"] = True
        compact_steps.append(compact)
    return {
        "status": payload.get("status"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "message": payload.get("message"),
        "steps": compact_steps,
    }


if __name__ == "__main__":
    raise SystemExit(main())
