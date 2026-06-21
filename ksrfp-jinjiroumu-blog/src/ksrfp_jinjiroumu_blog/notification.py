from __future__ import annotations

import hashlib
import smtplib
import subprocess
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from shutil import which
from typing import Any

from .io_utils import read_json, write_json
from .paths import CONFIG_DIR, LOGS_DIR


def send_run_notification(run_payload: dict[str, Any]) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    notification = settings.get("notification", {})
    recipient = notification.get("recipient")
    status = str(run_payload.get("status", "unknown"))
    should_send = bool(notification.get("email_enabled")) and bool(recipient)
    should_send = should_send and (
        (status == "ok" and notification.get("send_on_success", True))
        or (status != "ok" and notification.get("send_on_failure", True))
    )

    result: dict[str, Any] = {
        "status": "skipped",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recipient": recipient,
        "run_status": status,
        "method": None,
        "message": None,
    }

    if not should_send:
        result["message"] = "Notification disabled or not required for this status."
        write_notification_result(result)
        return result

    marker = notification_marker_path(run_payload) if notification.get("send_once_per_run", True) else None
    if marker and marker.exists():
        marker_payload = read_json(marker, {}) or {}
        result.update(
            {
                "status": "already_sent",
                "method": "marker",
                "message": "Notification was already sent for this run.",
                "marker": str(marker),
                "manifest_sha256": marker_payload.get("manifest_sha256"),
                "manifest_path": marker_payload.get("manifest_path"),
            }
        )
        write_notification_result(result)
        return result

    message = build_message(run_payload, str(recipient))
    if notification.get("write_eml_backup", True):
        write_eml_backup(message)

    max_attempts = notification_delivery_attempts(notification)
    retry_delay = notification_retry_delay(notification)
    delivery_attempts: list[dict[str, Any]] = []
    smtp_result: dict[str, Any] = {"status": "not_attempted", "method": "smtp"}
    sendmail_result: dict[str, Any] = {"status": "not_attempted", "method": "sendmail"}
    for attempt in range(1, max_attempts + 1):
        smtp_result = try_smtp(message, notification)
        sendmail_result = {"status": "not_attempted", "method": "sendmail"}
        if smtp_result["status"] == "sent":
            delivery_result = enrich_delivery_result(
                {**smtp_result, "attempt": attempt, "attempts": delivery_attempts},
                run_payload,
                str(recipient),
                str(message["Subject"]),
                marker,
            )
            write_notification_marker(marker, message["Subject"], delivery_result)
            write_notification_result(delivery_result)
            return delivery_result

        sendmail_result = try_sendmail(message)
        delivery_attempts.append(
            {
                "attempt": attempt,
                "smtp_status": smtp_result.get("status"),
                "smtp_message": smtp_result.get("message"),
                "sendmail_status": sendmail_result.get("status"),
                "sendmail_message": sendmail_result.get("message"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        if sendmail_result["status"] == "sent":
            delivery_result = enrich_delivery_result(
                {**sendmail_result, "attempt": attempt, "attempts": delivery_attempts},
                run_payload,
                str(recipient),
                str(message["Subject"]),
                marker,
            )
            write_notification_marker(marker, message["Subject"], delivery_result)
            write_notification_result(delivery_result)
            return delivery_result
        if attempt < max_attempts:
            time.sleep(retry_delay)

    result.update(
        {
            "status": "not_sent",
            "method": "none_available",
            "message": "No SMTP secret or local sendmail delivery succeeded.",
            "smtp_error": smtp_result.get("message"),
            "sendmail_error": sendmail_result.get("message"),
            "attempt_count": max_attempts,
            "attempts": delivery_attempts,
        }
    )
    write_notification_result(result)
    return result


def notification_delivery_attempts(notification: dict[str, Any]) -> int:
    try:
        return max(1, int(notification.get("delivery_max_attempts") or 3))
    except (TypeError, ValueError):
        return 3


def notification_retry_delay(notification: dict[str, Any]) -> int:
    try:
        return max(0, int(notification.get("delivery_retry_delay_seconds") or 10))
    except (TypeError, ValueError):
        return 10


def enrich_delivery_result(
    delivery_result: dict[str, Any],
    run_payload: dict[str, Any],
    recipient: str,
    subject: str,
    marker: Path | None,
) -> dict[str, Any]:
    enriched = dict(delivery_result)
    enriched.update(
        {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "recipient": recipient,
            "run_status": str(run_payload.get("status", "unknown")),
            "run_key": run_payload.get("run_key"),
            "started_at": run_payload.get("started_at"),
            "subject": subject,
            "marker": str(marker) if marker else None,
            "manifest_sha256": run_payload_manifest_sha256(run_payload),
            "manifest_path": run_payload.get("manifest_path"),
        }
    )
    return enriched


def run_payload_manifest_sha256(run_payload: dict[str, Any]) -> str | None:
    value = run_payload.get("manifest_sha256")
    if isinstance(value, str) and value:
        return value
    fingerprint = run_payload.get("manifest_fingerprint")
    if isinstance(fingerprint, dict) and isinstance(fingerprint.get("manifest_sha256"), str):
        return str(fingerprint.get("manifest_sha256") or "")
    return None


def build_message(run_payload: dict[str, Any], recipient: str) -> EmailMessage:
    status = str(run_payload.get("status", "unknown"))
    subject_status = subject_label_for_status(status)
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = "ksrfp-jinjiroumu-blog@localhost"
    message["Subject"] = f"[ksrfp-jinjiroumu-blog] 自動実行{subject_status}: {status}"
    message.set_content(render_body(run_payload))
    return message


def subject_label_for_status(status: str) -> str:
    if status == "ok":
        return "成功"
    if status in {
        "generation_ready_for_wordpress",
        "needs_image_generation_tool",
        "needs_drive_upload",
        "needs_drive_upload_plugin",
        "blocked_before_wordpress",
        "blocked_batch_quality",
        "blocked_until_verified",
        "blocked_insufficient_articles",
        "blocked_no_articles",
        "blocked_concurrent_run",
        "blocked_partial_draft_issue",
        "partial",
    }:
        return "要確認"
    return "失敗"


def render_body(run_payload: dict[str, Any]) -> str:
    outputs = run_payload.get("outputs", {}) if isinstance(run_payload.get("outputs"), dict) else {}
    lines = [
        "ksrfp-jinjiroumu-blog の自動実行結果です。",
        "",
        f"ステータス: {run_payload.get('status')}",
        f"開始: {run_payload.get('started_at')}",
        f"終了: {run_payload.get('finished_at')}",
        f"試行回数: {run_payload.get('attempts')}",
        f"未確認ファクト: {run_payload.get('fact_check_unverified')}",
        f"公開ゲート: {run_payload.get('publication_gate')}",
        f"3記事品質ゲート: {run_payload.get('article_batch_quality_passed')}",
        f"WordPress送信可能: {run_payload.get('wordpress_payload_ready_to_send')}",
        f"投稿ステータス: {run_payload.get('wordpress_payload_status')}",
        f"予約日時: {run_payload.get('wordpress_scheduled_date')}",
        f"カテゴリ: {run_payload.get('wordpress_category')} / ID {run_payload.get('wordpress_category_id')}",
    ]
    batch_quality_lines = render_batch_quality_lines(run_payload)
    if batch_quality_lines:
        lines.extend(batch_quality_lines)
    final_contract_lines = render_final_contract_lines(run_payload)
    if final_contract_lines:
        lines.extend(final_contract_lines)
    partial_draft_lines = render_partial_draft_issue_lines(run_payload)
    if partial_draft_lines:
        lines.extend(partial_draft_lines)
    if run_payload.get("status") != "ok":
        lines.extend(
            [
                "",
                "注意: この通知は最終完了の成功通知ではありません。",
                "Drive保存、WordPress下書き保存、検証のいずれかが未完了または要確認です。",
            ]
        )
    issue_lines = render_issue_selection_lines(run_payload)
    if issue_lines:
        lines.extend(issue_lines)
    article_lines = render_article_lines(run_payload)
    if article_lines:
        lines.extend(article_lines)
    else:
        lines.extend(render_source_lines(run_payload))
    lines.extend(["", "主な出力:"])
    for key, value in outputs.items():
        lines.append(f"- {key}: {value}")
    if run_payload.get("error"):
        lines.extend(["", "エラー:", str(run_payload.get("error"))])
    if run_payload.get("attempt_logs"):
        lines.extend(["", "試行ログ:"])
        for item in run_payload["attempt_logs"]:
            lines.append(f"- attempt {item.get('attempt')}: {item.get('status')} {item.get('error') or ''}".rstrip())
    return "\n".join(lines)


def render_batch_quality_lines(run_payload: dict[str, Any]) -> list[str]:
    quality = run_payload.get("article_batch_quality")
    if not isinstance(quality, dict) or not quality:
        return []
    return [
        "",
        "3記事全体の品質チェック:",
        f"- はじめに最大類似度: {quality.get('max_intro_similarity')}",
        f"- まとめ最大類似度: {quality.get('max_summary_similarity')}",
        f"- H2構成最大類似度: {quality.get('max_h2_similarity')}",
        f"- タイトル重複なし: {quality.get('title_uniqueness_ok')}",
        f"- タイトル型の偏りなし: {quality.get('title_pattern_diversity_ok')}",
        f"- 構成型の偏りなし: {quality.get('structure_pattern_diversity_ok')}",
        f"- アイキャッチ背景重複なし: {quality.get('image_backgrounds_unique')}",
    ]


def render_final_contract_lines(run_payload: dict[str, Any]) -> list[str]:
    step = run_payload.get("final_contract")
    if not isinstance(step, dict):
        return []
    payload = step.get("payload")
    if not isinstance(payload, dict):
        return []
    failed = payload.get("failed_checks")
    failed = failed if isinstance(failed, list) else []
    lines = [
        "",
        "最終契約テスト:",
        f"- ステータス: {payload.get('status')}",
        f"- NG件数: {payload.get('failed_count')}",
    ]
    for item in failed[:10]:
        if isinstance(item, dict):
            lines.append(f"  - {item.get('name')}")
    return lines


def render_partial_draft_issue_lines(run_payload: dict[str, Any]) -> list[str]:
    issues = run_payload.get("partial_draft_issues")
    if not isinstance(issues, list) or not issues:
        return []
    lines = ["", "部分下書き状態:"]
    for issue in issues[:10]:
        if not isinstance(issue, dict):
            continue
        lines.append(
            "- "
            f"{issue.get('pdf_name') or 'PDF未記録'}"
            f"（{issue.get('period_key') or '年月未記録'} / "
            f"status={issue.get('status') or '未記録'} / "
            f"下書き数={issue.get('wordpress_post_count')}/{issue.get('required_article_count')} / "
            f"投稿ID={issue.get('wordpress_post_ids') or '未記録'}）"
        )
    return lines


def render_issue_selection_lines(run_payload: dict[str, Any]) -> list[str]:
    issue = run_payload.get("newsletter_issue_selection")
    if not isinstance(issue, dict) or not issue:
        return []
    skipped = issue.get("skipped_completed_issues")
    skipped = skipped if isinstance(skipped, list) else []
    lines = [
        "",
        "人事労務だより号の選定:",
        f"- 選定ステータス: {issue.get('status') or '未記録'}",
        f"- 今回対象号: {issue.get('selected_pdf_name') or 'なし'}",
        f"- 今回対象年月: {issue.get('selected_period_key') or 'なし'}",
        f"- 今回スキップした号: {len(skipped)}件",
    ]
    for item in skipped[:10]:
        if isinstance(item, dict):
            lines.append(f"  - {item.get('pdf_name')}（{item.get('period_key')} / {item.get('reason')}）")
    if issue.get("status") == "all_issues_completed":
        lines.append("- 判定: すべての号が記事作成済みのため、記事作成を停止しました。")
    return lines


def render_article_lines(run_payload: dict[str, Any]) -> list[str]:
    articles = run_payload.get("articles")
    if not isinstance(articles, list) or not articles:
        return []
    lines = ["", "今回作成した記事候補:"]
    for article in articles:
        if not isinstance(article, dict):
            continue
        index = article.get("item_index") or "?"
        lines.extend(
            [
                "",
                f"【{index}件目】",
                f"- 記事タイトル: {article.get('article_title') or '未記録'}",
                f"- 人事労務だより: {article.get('source_pdf_name') or '未記録'}",
                f"- 掲載箇所/分類: {article.get('source_section_group') or '未記録'}",
                f"- 元トピック: {article.get('source_topic_title') or '未記録'}",
                f"- テーマ管理キー: {article.get('source_topic_key') or '未記録'}",
                f"- ラベル: {article.get('source_labels') or '未記録'}",
                f"- 日付言及: {article.get('source_date_mentions') or '未記録'}",
                f"- 元記事抜粋: {article.get('source_excerpt') or '未記録'}",
                f"- WordPress日付: {article.get('wordpress_scheduled_date') or '未記録'}",
                f"- カテゴリ: {article.get('wordpress_category') or '未記録'} / ID {article.get('wordpress_category_id') or '未記録'}",
                f"- WordPress下書き: ID {article.get('wordpress_post_id') or '未記録'} / {article.get('wordpress_url') or '未記録'}",
                f"- 確認用テキスト: {article.get('review_text_file') or '未記録'}",
                f"- Drive保存: {article.get('review_text_upload_status') or '未記録'}",
                f"- Drive URL: {article.get('review_text_drive_url') or '未記録'}",
                f"- アイキャッチ: {article.get('featured_image_url') or '未記録'}",
                f"- アイキャッチ品質: {article.get('featured_image_quality_ready') if article.get('featured_image_quality_ready') is not None else '未記録'}",
                f"- アイキャッチ背景: {article.get('featured_image_base_status') or '未記録'}",
                f"- 写真背景ソース: {article.get('featured_image_photo_source_exists') if article.get('featured_image_photo_source_exists') is not None else '未記録'}",
                "- 重複確認:",
                f"  近い既存記事: {article.get('source_nearest_article_title') or '未記録'}",
                f"  URL: {article.get('source_nearest_article_url') or '未記録'}",
                f"  類似度: {article.get('source_nearest_similarity') or '未記録'}",
            ]
        )
    return lines


def render_source_lines(run_payload: dict[str, Any]) -> list[str]:
    fields = [
        run_payload.get("source_pdf_name"),
        run_payload.get("source_section_group"),
        run_payload.get("source_topic_title"),
        run_payload.get("source_labels"),
        run_payload.get("source_date_mentions"),
        run_payload.get("source_excerpt"),
        run_payload.get("source_nearest_article_title"),
    ]
    if not any(value not in (None, "") for value in fields):
        return []

    lines = [
        "",
        "今回のテーマ元:",
        f"- 人事労務だより: {run_payload.get('source_pdf_name') or '未記録'}",
        f"- 掲載箇所/分類: {run_payload.get('source_section_group') or '未記録'}",
        f"- 元トピック: {run_payload.get('source_topic_title') or '未記録'}",
    ]
    if run_payload.get("source_topic_key"):
        lines.append(f"- テーマ管理キー: {run_payload.get('source_topic_key')}")
    if run_payload.get("source_labels"):
        lines.append(f"- ラベル: {run_payload.get('source_labels')}")
    if run_payload.get("source_date_mentions"):
        lines.append(f"- 日付言及: {run_payload.get('source_date_mentions')}")
    if run_payload.get("source_excerpt"):
        lines.append(f"- 元記事抜粋: {run_payload.get('source_excerpt')}")
    if run_payload.get("source_nearest_article_title") or run_payload.get("source_nearest_article_url"):
        lines.extend(
            [
                "- 重複確認:",
                f"  近い既存記事: {run_payload.get('source_nearest_article_title') or '未記録'}",
                f"  URL: {run_payload.get('source_nearest_article_url') or '未記録'}",
                f"  類似度: {run_payload.get('source_nearest_similarity') or '未記録'}",
            ]
        )
    return lines


def try_smtp(message: EmailMessage, notification: dict[str, Any]) -> dict[str, Any]:
    secret_path = CONFIG_DIR.parent / str(notification.get("smtp_secret_path", "config/secrets/email_smtp.json"))
    if not secret_path.exists():
        return {"status": "skipped", "method": "smtp", "message": f"SMTP secret not found: {secret_path}"}
    try:
        secret = read_json(secret_path, {}) or {}
        host = secret["host"]
        port = int(secret.get("port") or 587)
        username = secret.get("username")
        password = secret.get("password")
        from_email = secret.get("from_email") or username
        use_tls = bool(secret.get("use_tls", True))
        if from_email:
            message.replace_header("From", from_email)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return {"status": "sent", "method": "smtp", "message": "Notification sent via SMTP."}
    except Exception as exc:
        return {"status": "failed", "method": "smtp", "message": str(exc)}


def notification_marker_path(run_payload: dict[str, Any]) -> Path:
    raw_key = "|".join(
        str(run_payload.get(key) or "")
        for key in ("run_key", "started_at", "status", "newsletter_issue_selection", "generated_article_count")
    )
    manifest_sha256 = run_payload_manifest_sha256(run_payload)
    if manifest_sha256:
        raw_key = f"{raw_key}|{manifest_sha256}"
    if not raw_key.strip("|"):
        raw_key = datetime.now().strftime("%Y%m%d")
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
    return LOGS_DIR / "notifications" / "markers" / f"{digest}.json"


def write_notification_marker(marker: Path | None, subject: str | None, result: dict[str, Any]) -> None:
    if marker is None:
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "subject": subject,
        "method": result.get("method"),
        "status": result.get("status"),
        "run_status": result.get("run_status"),
        "run_key": result.get("run_key"),
        "manifest_sha256": result.get("manifest_sha256"),
        "manifest_path": result.get("manifest_path"),
    }
    write_json(marker, payload)


def try_sendmail(message: EmailMessage) -> dict[str, Any]:
    sendmail_path = which("sendmail") or "/usr/sbin/sendmail"
    if not Path(sendmail_path).exists():
        return {"status": "skipped", "method": "sendmail", "message": "sendmail command not found."}
    try:
        completed = subprocess.run(
            [sendmail_path, "-t", "-oi"],
            input=message.as_bytes(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        if completed.returncode == 0:
            return {"status": "sent", "method": "sendmail", "message": "Notification handed to local sendmail."}
        return {
            "status": "failed",
            "method": "sendmail",
            "message": completed.stderr.decode("utf-8", errors="replace")[:1000],
        }
    except Exception as exc:
        return {"status": "failed", "method": "sendmail", "message": str(exc)}


def write_eml_backup(message: EmailMessage) -> None:
    directory = LOGS_DIR / "notifications"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (directory / "latest_notification.eml").write_bytes(message.as_bytes())
    (directory / f"notification-{timestamp}.eml").write_bytes(message.as_bytes())


def write_notification_result(result: dict[str, Any]) -> None:
    directory = LOGS_DIR / "notifications"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(directory / "latest_notification.json", result)
    write_json(directory / f"notification-{timestamp}.json", result)
