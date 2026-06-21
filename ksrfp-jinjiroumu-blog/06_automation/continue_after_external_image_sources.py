#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json  # noqa: E402
from ksrfp_jinjiroumu_blog.notification import send_run_notification  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import CONFIG_DIR, LOGS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.external_preflight import run_external_preflight  # noqa: E402


def main() -> int:
    started_at = datetime.now().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": started_at,
        "finished_at": None,
        "steps": [],
    }
    try:
        rebuild = run_step("rebuild_after_external_image_sources", ["06_automation/rebuild_after_external_image_sources.py"])
        payload["steps"].append(rebuild)
        if rebuild.get("returncode") != 0 or rebuild.get("payload_status") != "ok":
            return finish_with_notification(
                payload,
                "blocked_after_external_image_rebuild",
                "外部画像ソース後の再構築がOKではありません。",
                return_code=1,
            )

        preflight_started_at = datetime.now().isoformat(timespec="seconds")
        try:
            preflight_result = run_external_preflight(check_drive=True, check_smtp_login=True)
        except Exception as exc:
            preflight_result = {
                "status": "error",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }
        preflight = {
            "name": "external_preflight_before_wordpress",
            "started_at": preflight_started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "payload_status": preflight_result.get("status"),
            "payload": preflight_result,
            "returncode": 0 if preflight_result.get("status") == "ok" else 1,
        }
        payload["steps"].append(preflight)
        if preflight_result.get("status") != "ok":
            return finish_with_notification(
                payload,
                "blocked_preflight_failed",
                "Codex画像生成ツール後のWordPress保存前プリフライトがOKではありません。",
                return_code=1,
            )

        publish = run_step_with_retries(
            "wordpress_publish",
            ["06_automation/run_wordpress_publish.py", "--all", "--execute"],
            success_payload_statuses={"created", "already_created"},
            terminal_payload_statuses={"state_payload_mismatch", "payload_count_mismatch", "no_payloads"},
            extra_env={"KSRFP_ALLOW_WORDPRESS_WRITE": "1"},
        )
        payload["steps"].append(publish)
        if publish.get("returncode") != 0 or publish.get("payload_status") not in {"created", "already_created"}:
            return finish_with_notification(
                payload,
                "partial",
                "WordPress下書き保存に失敗または未完了です。",
                return_code=1,
            )

        reconcile = run_step_with_retries(
            "wordpress_state_reconcile",
            ["06_automation/reconcile_wordpress_state_from_publish_log.py"],
            success_payload_statuses={"ok"},
            terminal_payload_statuses={"stale_publish_log", "publish_not_successful"},
        )
        payload["steps"].append(reconcile)
        if reconcile.get("returncode") != 0 or reconcile.get("payload_status") != "ok":
            return finish_with_notification(
                payload,
                "partial",
                "WordPress下書き保存後の状態履歴補修がOKではありません。",
                return_code=1,
            )

        verify = run_step_with_retries(
            "wordpress_verify_batch",
            ["06_automation/run_wordpress_verify_batch.py"],
            success_payload_statuses={"ok"},
        )
        payload["steps"].append(verify)
        if verify.get("returncode") != 0 or verify.get("payload_status") != "ok":
            return finish_with_notification(
                payload,
                "partial",
                "WordPress読み返し検証がOKではありません。",
                return_code=1,
            )

        drive = run_step_with_retries(
            "review_text_drive_upload",
            ["06_automation/run_review_text_batch_upload.py"],
            success_payload_statuses={"ok"},
            terminal_payload_statuses={"blocked_wordpress_not_verified", "blocked_wordpress_verification_stale"},
            terminal_predicate=drive_requires_plugin_upload,
        )
        payload["steps"].append(drive)
        if drive_requires_plugin_upload(drive):
            payload["status"] = "needs_drive_upload_plugin"
            payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
            payload["notification"] = {
                "status": "deferred",
                "reason": "最終通知はDrive保存と最終検証の後に送信する。",
            }
            payload["next_action"] = (
                "Codex Google Driveプラグインで確認用テキスト3件を保存し、"
                "06_automation/record_drive_plugin_uploads.py でDrive URLを記録してから、"
                "06_automation/send_manual_full_test_notification.py を1回だけ実行してください。"
            )
            write_logs(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2
        if drive.get("returncode") != 0 or drive.get("payload_status") != "ok":
            return finish_with_notification(
                payload,
                "partial",
                "Google Drive確認用テキスト保存がOKではありません。",
                return_code=1,
            )

        notification = run_step_with_retries(
            "final_notification",
            ["06_automation/send_manual_full_test_notification.py"],
            success_payload_statuses={"ok", "blocked_all_newsletter_issues_completed"},
            terminal_payload_statuses={"partial"},
        )
        payload["steps"].append(notification)
        final = notification.get("payload") if isinstance(notification.get("payload"), dict) else {}
        if final:
            final["external_image_continuation"] = payload
            write_logs(final)
            print(json.dumps(final, ensure_ascii=False, indent=2))
            return 0 if final.get("status") == "ok" else 1
        return finish_with_notification(
            payload,
            "partial",
            "最終通知メール送信結果を取得できませんでした。",
            return_code=1,
        )
    except Exception as exc:
        return finish_with_notification(payload, "error", f"{type(exc).__name__}: {exc}", return_code=1)


def run_step(name: str, args: list[str], extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=900,
        check=False,
    )
    parsed = parse_json_stdout(completed.stdout)
    return {
        "name": name,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "command": " ".join(args),
        "returncode": completed.returncode,
        "payload_status": parsed.get("status") if isinstance(parsed, dict) else None,
        "payload": parsed,
        "stdout_tail": completed.stdout[-3000:],
        "stderr_tail": completed.stderr[-3000:],
    }


def run_step_with_retries(
    name: str,
    args: list[str],
    success_payload_statuses: set[str],
    extra_env: dict[str, str] | None = None,
    terminal_payload_statuses: set[str] | None = None,
    terminal_predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    retry_policy = load_completion_retry_policy()
    try:
        max_attempts = max(1, int(retry_policy.get("max_attempts") or 3))
    except (TypeError, ValueError):
        max_attempts = 3
    try:
        retry_delay = max(0, int(retry_policy.get("retry_delay_seconds") or 30))
    except (TypeError, ValueError):
        retry_delay = 30
    terminal_payload_statuses = terminal_payload_statuses or set()
    attempts: list[dict[str, Any]] = []
    last_step: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        step = run_step(name, args, extra_env=extra_env)
        step["attempt"] = attempt
        attempts.append(step)
        last_step = step
        payload_status = str(step.get("payload_status") or "")
        terminal = payload_status in terminal_payload_statuses
        if terminal_predicate is not None:
            terminal = terminal or terminal_predicate(step)
        if step.get("returncode") == 0 and payload_status in success_payload_statuses:
            break
        if terminal or attempt >= max_attempts:
            break
        time.sleep(retry_delay)
    last_step = dict(last_step)
    last_step["attempt_count"] = len(attempts)
    last_step["attempts"] = attempts
    return last_step


def load_completion_retry_policy() -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    retry_policy = settings.get("completion_retry_policy")
    if isinstance(retry_policy, dict):
        return retry_policy
    base = settings.get("retry_policy")
    base = base if isinstance(base, dict) else {}
    return {
        "max_attempts": base.get("max_attempts", 3),
        "retry_delay_seconds": base.get("retry_delay_seconds", 30),
    }


def parse_json_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def drive_requires_plugin_upload(step: dict[str, Any]) -> bool:
    payload = step.get("payload")
    if not isinstance(payload, dict):
        return False
    result = payload.get("result")
    if not isinstance(result, dict):
        return False
    items = result.get("items")
    if not isinstance(items, list):
        return False
    return bool(items) and all(isinstance(item, dict) and item.get("status") == "auth_required" for item in items)


def finish_with_notification(payload: dict[str, Any], status: str, message: str, return_code: int) -> int:
    payload["status"] = status
    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    payload["error"] = message
    payload["outputs"] = {
        "continuation_log": "07_logs/continue_after_external_image_sources_latest.json",
        "notification": "07_logs/notifications/latest_notification.json",
    }
    try:
        payload["notification"] = send_run_notification(payload)
    except Exception as exc:
        payload["notification"] = {"status": "error", "message": str(exc)}
    write_logs(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return return_code


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "continue_after_external_image_sources_latest.json", payload)
    write_json(LOGS_DIR / f"continue-after-external-image-sources-{timestamp}.json", payload)
    latest = read_json(LOGS_DIR / "weekly_latest.json", {}) or {}
    if isinstance(latest, dict):
        latest["external_image_continuation"] = payload
        if payload.get("status") in {"ok", "partial", "error", "needs_drive_upload_plugin"}:
            latest["status"] = payload.get("status")
            latest["finished_at"] = payload.get("finished_at")
            latest["notification"] = payload.get("notification")
        write_json(LOGS_DIR / "weekly_latest.json", latest)


if __name__ == "__main__":
    raise SystemExit(main())
