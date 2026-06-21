from __future__ import annotations

import json
import smtplib
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from .drive_client import build_drive_status
from .io_utils import read_json, write_json, write_markdown
from .network_probe import probe_host_port, probe_url
from .paths import CONFIG_DIR, LOGS_DIR, WORDPRESS_DIR
from .image_source_generator import image_generation_preflight
from .wordpress_client import (
    compare_configured_categories,
    fetch_wordpress_taxonomy,
    read_wordpress_credentials,
    check_wordpress_connection,
)


def run_external_preflight(check_drive: bool = True, check_smtp_login: bool = True) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    configured_categories = settings.get("wordpress_categories", [])
    configured_categories = configured_categories if isinstance(configured_categories, list) else []
    notification = settings.get("notification", {}) if isinstance(settings.get("notification"), dict) else {}
    smtp_secret_path = CONFIG_DIR.parent / str(notification.get("smtp_secret_path", "config/secrets/email_smtp.json"))

    wordpress_network = probe_url(api_base or "https://ksrfp.com/wp-json/wp/v2")
    wordpress_network["ok"] = bool(wordpress_network.get("dns_ok") and wordpress_network.get("tcp_ok"))

    result: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "not_checked",
        "checks": {
            "drive": {"ok": True, "checked": False},
            "wordpress_network": wordpress_network,
            "wordpress_credentials": {"ok": False},
            "wordpress_connection": {"ok": False},
            "wordpress_categories": {"ok": False},
            "smtp_settings": {"ok": False, "secret_path": str(smtp_secret_path), "secret_found": smtp_secret_path.exists()},
            "smtp_network": {"ok": False},
            "smtp_login": {"checked": False, "ok": True},
            "image_generation": {"checked": False, "ok": True},
        },
        "errors": [],
        "notes": [
            "Secrets are checked only for presence and are never printed.",
            "This preflight must run in the same automation environment before Drive review-text upload and WordPress writes.",
        ],
    }

    if check_drive:
        try:
            drive_status = build_drive_status()
            result["checks"]["drive"] = {
                "ok": drive_status.get("status") == "ok",
                "checked": True,
                "status": drive_status.get("status"),
                "drive_pdf_count": drive_status.get("drive_pdf_count"),
                "selected_drive_pdf": (drive_status.get("selected_drive_pdf") or {}).get("name")
                if isinstance(drive_status.get("selected_drive_pdf"), dict)
                else None,
                "all_drive_pdfs_completed": drive_status.get("all_drive_pdfs_completed"),
            }
        except Exception as exc:
            result["checks"]["drive"] = {
                "ok": False,
                "checked": True,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }

    credentials = read_wordpress_credentials()
    result["checks"]["wordpress_credentials"] = {
        "ok": bool(credentials.get("ready")),
        "secret_file_found": bool(credentials.get("file_found")),
        "username_found": bool(credentials.get("username_found")),
        "application_password_found": bool(credentials.get("application_password_found")),
    }
    if credentials.get("ready"):
        try:
            connection = check_wordpress_connection(
                api_base,
                str(credentials["username"]),
                str(credentials["application_password"]),
            )
            result["checks"]["wordpress_connection"] = {"ok": bool(connection.get("ok")), **connection}
        except Exception as exc:
            result["checks"]["wordpress_connection"] = {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }
        try:
            categories = fetch_wordpress_taxonomy(api_base, "categories")
            category_comparison = compare_configured_categories(configured_categories, categories)
            category_mismatches = [row for row in category_comparison if not row.get("matched")]
            result["checks"]["wordpress_categories"] = {
                "ok": bool(categories) and not category_mismatches,
                "count": len(categories),
                "configured_count": len(configured_categories),
                "comparison": category_comparison,
                "mismatches": category_mismatches,
            }
        except Exception as exc:
            result["checks"]["wordpress_categories"] = {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }

    smtp_secret = load_smtp_secret(smtp_secret_path)
    smtp_ok = bool(smtp_secret.get("host")) and bool(smtp_secret.get("username")) and bool(smtp_secret.get("password"))
    result["checks"]["smtp_settings"] = {
        "ok": smtp_ok,
        "secret_path": str(smtp_secret_path),
        "secret_found": smtp_secret_path.exists(),
        "host_found": bool(smtp_secret.get("host")),
        "username_found": bool(smtp_secret.get("username")),
        "password_found": bool(smtp_secret.get("password")),
        "from_email_found": bool(smtp_secret.get("from_email") or smtp_secret.get("username")),
    }
    if smtp_secret.get("host"):
        smtp_port = int(smtp_secret.get("port") or 587)
        smtp_network = probe_host_port(str(smtp_secret["host"]), smtp_port)
        smtp_network["ok"] = bool(smtp_network.get("dns_ok") and smtp_network.get("tcp_ok"))
        result["checks"]["smtp_network"] = smtp_network
        if check_smtp_login and smtp_ok:
            result["checks"]["smtp_login"] = _smtp_login_check(smtp_secret)

    image_check = image_generation_preflight()
    image_required = bool(settings.get("image_generation", {}).get("required_in_preflight", False)) if isinstance(settings.get("image_generation"), dict) else False
    if not image_required and not image_check.get("ok"):
        image_check["ok"] = True
        image_check["warning"] = "画像生成はCodexセッション内ツールへ引き継ぐ運用のため、Python単体の画像生成はプリフライト必須条件にしない。"
    result["checks"]["image_generation"] = image_check

    for name, check in result["checks"].items():
        if isinstance(check, dict) and not check.get("ok"):
            result["errors"].append(f"{name}: {check.get('error') or check.get('dns_error') or check.get('tcp_error') or 'not ok'}")

    result["status"] = "ok" if not result["errors"] else "error"
    write_preflight(result)
    return result


def write_preflight(result: dict[str, Any]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "external_preflight_latest.json", result)
    write_json(LOGS_DIR / f"external-preflight-{timestamp}.json", result)
    write_json(WORDPRESS_DIR / "external_preflight_latest.json", result)
    write_markdown(WORDPRESS_DIR / "external_preflight_latest.md", render_preflight(result))


def render_preflight(result: dict[str, Any]) -> str:
    lines = [
        "# 外部連携プリフライト",
        "",
        f"- 生成日時: {result.get('generated_at')}",
        f"- ステータス: {result.get('status')}",
        "",
        "## チェック",
        "",
    ]
    for name, check in result.get("checks", {}).items():
        if not isinstance(check, dict):
            continue
        lines.append(f"- {name}: {'OK' if check.get('ok') else 'NG'}")
    errors = result.get("errors") or []
    if errors:
        lines.extend(["", "## エラー", ""])
        for error in errors:
            lines.append(f"- {error}")
    lines.extend(
        [
            "",
            "## 方針",
            "",
            "このプリフライトがNGの場合、記事生成後の外部成果物作成、WordPress下書き保存、Google Drive確認用テキスト保存へ進まない。",
        ]
    )
    return "\n".join(lines)


def load_smtp_secret(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _smtp_login_check(secret: dict[str, Any]) -> dict[str, Any]:
    host = str(secret.get("host") or "")
    port = int(secret.get("port") or 587)
    username = str(secret.get("username") or "")
    password = str(secret.get("password") or "")
    use_tls = bool(secret.get("use_tls", True))
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(username, password)
            smtp.noop()
        return {"checked": True, "ok": True}
    except (OSError, smtplib.SMTPException, socket.error) as exc:
        return {
            "checked": True,
            "ok": False,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
