from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .paths import LOGS_DIR, NOTIFICATIONS_DIR, PROJECT_ROOT


def send_completion_notification(
    *,
    settings: dict[str, Any],
    article: dict[str, Any],
    drive_package: dict[str, Any],
    drive_upload: dict[str, Any],
) -> dict[str, Any]:
    notification = settings.get("notification", {}) if isinstance(settings.get("notification"), dict) else {}
    recipient = str(notification.get("recipient") or "").strip()
    enabled = bool(notification.get("email_enabled")) and bool(recipient)
    message = build_message(recipient=recipient, article=article, drive_package=drive_package, drive_upload=drive_upload)

    if notification.get("write_eml_backup", True):
        write_eml_backup(message)

    if not enabled:
        result = {
            "status": "skipped",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "message": "Notification is disabled or recipient is missing.",
            "recipient": recipient,
        }
        write_notification_result(result)
        return result

    smtp_secret = find_smtp_secret(notification)
    if not smtp_secret:
        result = {
            "status": "not_sent",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "message": "SMTP secret was not found.",
            "recipient": recipient,
        }
        write_notification_result(result)
        return result

    result = try_smtp(message, smtp_secret)
    result.update(
        {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "recipient": recipient,
            "subject": message["Subject"],
        }
    )
    write_notification_result(result)
    return result


def send_pipeline_status_notification(*, settings: dict[str, Any], pipeline_result: dict[str, Any]) -> dict[str, Any]:
    notification = settings.get("notification", {}) if isinstance(settings.get("notification"), dict) else {}
    recipient = str(notification.get("recipient") or "").strip()
    enabled = bool(notification.get("email_enabled")) and bool(recipient)
    message = build_pipeline_status_message(recipient=recipient, pipeline_result=pipeline_result)

    if notification.get("write_eml_backup", True):
        write_eml_backup(message)

    if not enabled:
        result = {
            "status": "skipped",
            "type": "pipeline_status",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "message": "Notification is disabled or recipient is missing.",
            "recipient": recipient,
            "pipeline_status": pipeline_result.get("status"),
        }
        write_notification_result(result)
        write_json(LOGS_DIR / "pipeline_status_notification_latest.json", result)
        return result

    smtp_secret = find_smtp_secret(notification)
    if not smtp_secret:
        result = {
            "status": "not_sent",
            "type": "pipeline_status",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "message": "SMTP secret was not found.",
            "recipient": recipient,
            "pipeline_status": pipeline_result.get("status"),
        }
        write_notification_result(result)
        write_json(LOGS_DIR / "pipeline_status_notification_latest.json", result)
        return result

    result = try_smtp(message, smtp_secret)
    result.update(
        {
            "type": "pipeline_status",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "recipient": recipient,
            "subject": message["Subject"],
            "pipeline_status": pipeline_result.get("status"),
        }
    )
    write_notification_result(result)
    write_json(LOGS_DIR / "pipeline_status_notification_latest.json", result)
    return result


def build_message(
    *,
    recipient: str,
    article: dict[str, Any],
    drive_package: dict[str, Any],
    drive_upload: dict[str, Any],
) -> EmailMessage:
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = "ksrfp-blog-rewrite@localhost"
    message["Subject"] = f"[ksrfp-blog-rewrite] リライト記事生成完了: {article.get('title')}"
    message.set_content(render_body(article=article, drive_package=drive_package, drive_upload=drive_upload))
    return message


def build_pipeline_status_message(*, recipient: str, pipeline_result: dict[str, Any]) -> EmailMessage:
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = "ksrfp-blog-rewrite@localhost"
    message["Subject"] = f"[ksrfp-blog-rewrite] 要対応: {pipeline_result.get('status')}"
    message.set_content(render_pipeline_status_body(pipeline_result))
    return message


def render_body(*, article: dict[str, Any], drive_package: dict[str, Any], drive_upload: dict[str, Any]) -> str:
    text_file = drive_package.get("text_file", {}) if isinstance(drive_package.get("text_file"), dict) else {}
    image_file = drive_package.get("image_file", {}) if isinstance(drive_package.get("image_file"), dict) else {}
    text_upload = drive_upload.get("text_file", {}) if isinstance(drive_upload.get("text_file"), dict) else {}
    image_upload = drive_upload.get("image_file", {}) if isinstance(drive_upload.get("image_file"), dict) else {}
    quality = article.get("quality", {}) if isinstance(article.get("quality"), dict) else {}
    gate = article.get("quality_gate", {}) if isinstance(article.get("quality_gate"), dict) else {}

    return "\n".join(
        [
            "過去記事リライト自動化の生成結果です。",
            "",
            f"ステータス: ok",
            f"記事タイトル: {article.get('title')}",
            f"ターゲットSEOキーワード: {article.get('target_seo_keyword')}",
            f"本文文字数: {quality.get('character_count')}",
            f"H2数: {quality.get('h2_count')}",
            f"H3数: {quality.get('h3_count')}",
            f"品質ゲート: {'通過' if gate.get('passed') else '未通過'}",
            "",
            "Google Drive保存:",
            f"- テキスト: {text_file.get('name')}",
            f"- テキストURL: {text_upload.get('url')}",
            f"- 画像: {image_file.get('name')}",
            f"- 画像URL: {image_upload.get('url')}",
            "",
            "WordPressへの下書き保存・投稿反映は行っていません。",
        ]
    )


def render_pipeline_status_body(pipeline_result: dict[str, Any]) -> str:
    steps = pipeline_result.get("steps", []) if isinstance(pipeline_result.get("steps"), list) else []
    last_step = steps[-1] if steps and isinstance(steps[-1], dict) else {}
    validation = last_step.get("validation", {}) if isinstance(last_step.get("validation"), dict) else {}

    lines = [
        "過去記事リライト自動化で要対応の状態になりました。",
        "",
        f"ステータス: {pipeline_result.get('status')}",
        f"メッセージ: {pipeline_result.get('message')}",
        f"開始: {pipeline_result.get('started_at')}",
        f"終了: {pipeline_result.get('finished_at')}",
        "",
        "停止位置:",
        f"- step: {last_step.get('name')}",
        f"- reason: {validation.get('reason') or last_step.get('message')}",
    ]
    if last_step.get("expected_path"):
        lines.append(f"- expected_path: {last_step.get('expected_path')}")
    if last_step.get("expected_log"):
        lines.append(f"- expected_log: {last_step.get('expected_log')}")

    lines.extend(
        [
            "",
            "確認ログ:",
            "- 07_logs/rewrite_pipeline_latest.json",
            "",
            "WordPressへの下書き保存・投稿反映は行っていません。",
        ]
    )
    return "\n".join(str(line) for line in lines)


def find_smtp_secret(notification: dict[str, Any]) -> Path | None:
    paths = notification.get("smtp_secret_search_paths", [])
    if not isinstance(paths, list):
        return None
    for value in paths:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        if path.exists():
            return path
    return None


def try_smtp(message: EmailMessage, secret_path: Path) -> dict[str, Any]:
    try:
        secret = read_json(secret_path, {}) or {}
        host = secret["host"]
        port = int(secret.get("port") or 587)
        username = secret.get("username")
        password = secret.get("password")
        from_email = secret.get("from_email") or username
        use_tls = bool(secret.get("use_tls", True))
        if from_email:
            message.replace_header("From", str(from_email))
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return {"status": "sent", "method": "smtp", "message": "Notification sent via SMTP."}
    except Exception as exc:
        return {"status": "not_sent", "method": "smtp", "message": str(exc)}


def write_eml_backup(message: EmailMessage) -> None:
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (NOTIFICATIONS_DIR / "latest_notification.eml").write_bytes(message.as_bytes())
    (NOTIFICATIONS_DIR / f"notification-{timestamp}.eml").write_bytes(message.as_bytes())


def write_notification_result(result: dict[str, Any]) -> None:
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(NOTIFICATIONS_DIR / "latest_notification.json", result)
    write_json(NOTIFICATIONS_DIR / f"notification-{timestamp}.json", result)
    write_json(LOGS_DIR / "notification_latest.json", result)
