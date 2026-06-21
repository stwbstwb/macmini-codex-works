from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import re
import unicodedata
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .image_gate import featured_image_gate_reasons
from .io_utils import read_json, read_text, write_json, write_markdown
from .paths import CONFIG_DIR, WORDPRESS_DIR, WORDPRESS_PAYLOAD_DIR
from .state_manager import record_wordpress_scheduled_post, stable_key


WORDPRESS_SECRET_NAME_HINTS = (
    "wordpress",
    "wp",
    "アプリケーション",
    "パスワード",
)

NON_WORDPRESS_SECRET_NAMES = {
    "email_smtp.json",
}


def basic_auth_token(username: str, application_password: str) -> str:
    return base64.b64encode(f"{username}:{application_password}".encode("utf-8")).decode("ascii")


def build_wordpress_status() -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    payload = read_json(WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json", {}) or {}
    external_enabled = bool(settings.get("enable_external_api_calls"))
    credentials = read_wordpress_credentials()

    status: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "not_checked",
        "external_api_enabled": external_enabled,
        "api_base": settings.get("wordpress_api_base"),
        "secret_file_found": credentials["file_found"],
        "secret_file_path": credentials["file_path"],
        "username_found": credentials["username_found"],
        "application_password_found": credentials["application_password_found"],
        "payload_found": bool(payload),
        "payload_ready_to_send": bool(payload.get("ready_to_send")),
        "post_status": payload.get("wordpress", {}).get("status") if payload else None,
        "connection_checked": False,
        "connection_ok": False,
        "next_action": None,
    }

    if not external_enabled:
        status["status"] = "external_api_disabled"
        status["next_action"] = "WordPress接続テスト時に enable_external_api_calls を true にし、ユーザー確認のうえAPIを実行する。"
    elif not credentials["ready"]:
        status["status"] = "credentials_required"
        status["next_action"] = "config/secrets/ のWordPressアプリケーションパスワード情報を確認する。"
    elif not payload.get("ready_to_send"):
        status["status"] = "payload_blocked"
        status["next_action"] = "ファクトチェック、表示確認、下書き保存テストを完了してから送信する。"
    else:
        try:
            connection = check_wordpress_connection(
                str(settings.get("wordpress_api_base", "")).rstrip("/"),
                credentials["username"],
                credentials["application_password"],
            )
            status["status"] = "ok" if connection["ok"] else "connection_failed"
            status["connection_checked"] = True
            status["connection_ok"] = connection["ok"]
            status["http_status"] = connection.get("http_status")
            status["next_action"] = "下書き保存テストへ進む。" if connection["ok"] else "認証情報とREST APIの権限を確認する。"
        except Exception as exc:
            status["status"] = "error"
            status["connection_checked"] = True
            status["error"] = str(exc)
            status["next_action"] = "ネットワーク、認証情報、WordPress REST API権限を確認する。"

    write_json(WORDPRESS_DIR / "wordpress_status_latest.json", scrub_secret_fields(status))
    write_markdown(WORDPRESS_DIR / "wordpress_status_latest.md", render_wordpress_status(status))
    return scrub_secret_fields(status)


def read_wordpress_credentials() -> dict[str, Any]:
    secret_file = find_secret_file()
    result: dict[str, Any] = {
        "file_found": bool(secret_file),
        "file_path": str(secret_file) if secret_file else None,
        "username": None,
        "application_password": None,
        "username_found": False,
        "application_password_found": False,
        "ready": False,
    }
    if not secret_file:
        return result

    text = read_text(secret_file)
    if secret_file.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            username = data.get("username") or data.get("user") or data.get("login")
            password = data.get("application_password") or data.get("app_password") or data.get("password")
        except json.JSONDecodeError:
            username = None
            password = None
    else:
        plain = rtf_to_text(text) if secret_file.suffix.lower() == ".rtf" else text
        username = find_labeled_value(plain, ["ユーザー名", "ログインID", "username", "user", "login"])
        password = find_labeled_value(plain, ["アプリケーションパスワード", "application password", "app password", "password"])

    result["username"] = clean_secret_value(username) if isinstance(username, str) else None
    result["application_password"] = clean_secret_value(password) if isinstance(password, str) else None
    result["username_found"] = bool(result["username"])
    result["application_password_found"] = bool(result["application_password"])
    result["ready"] = result["username_found"] and result["application_password_found"]
    return result


def find_secret_file() -> Path | None:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    configured_path = settings.get("wordpress_secret_path")
    if configured_path:
        path = CONFIG_DIR.parent / str(configured_path)
        if path.exists():
            return path

    secrets_dir = CONFIG_DIR / "secrets"
    if not secrets_dir.exists():
        return None
    candidates = sorted([*secrets_dir.glob("*.rtf"), *secrets_dir.glob("*.json"), *secrets_dir.glob("*.txt")])
    candidates = [path for path in candidates if path.name.lower() not in {"readme.md", *NON_WORDPRESS_SECRET_NAMES}]
    hinted = [path for path in candidates if has_wordpress_secret_name_hint(path.name)]
    return hinted[0] if hinted else candidates[0] if candidates else None


def has_wordpress_secret_name_hint(name: str) -> bool:
    normalized = unicodedata.normalize("NFC", name).lower()
    return any(hint in normalized for hint in WORDPRESS_SECRET_NAME_HINTS)


def rtf_to_text(text: str) -> str:
    text = text.replace("\\par", "\n")
    text = re.sub(r"\\u(-?\d+)\??", unicode_escape_to_char, text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def unicode_escape_to_char(match: re.Match[str]) -> str:
    value = int(match.group(1))
    if value < 0:
        value += 65536
    try:
        return chr(value)
    except ValueError:
        return " "


def find_labeled_value(text: str, labels: list[str]) -> str | None:
    normalized_labels = {normalize_label(label): label for label in labels}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        for separator in ("：", ":"):
            if separator not in line:
                continue
            left, right = line.split(separator, 1)
            if normalize_label(left) in normalized_labels:
                return right.strip()

    for label in labels:
        pattern = re.compile(rf"{re.escape(label)}\s*[:：]\s*([^|\n\r]+)", flags=re.IGNORECASE)
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            value = re.split(r"\s{3,}|(?:ユーザー名|ログインID|username|user|login|アプリケーションパスワード|application password|app password|password)\s*[:：]", value, maxsplit=1, flags=re.IGNORECASE)[0]
            return value.strip()
    for index, line in enumerate(lines):
        normalized_line = normalize_label(line)
        for label in labels:
            if normalize_label(label) == normalized_line and index + 1 < len(lines):
                return lines[index + 1].strip()
    return None


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def clean_secret_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().strip("\"'`\\")
    cleaned = re.sub(r"\\+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or None


def check_wordpress_connection(api_base: str, username: str, application_password: str) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    request = Request(f"{api_base}/users/me?context=edit", headers={"Authorization": f"Basic {token}"})
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
        return {
            "ok": 200 <= response.status < 300,
            "http_status": response.status,
            "user_id": data.get("id"),
            "user_slug": data.get("slug"),
            "user_name": data.get("name"),
        }


def build_wordpress_readonly_check() -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    credentials = read_wordpress_credentials()
    configured_categories = settings.get("wordpress_categories", [])
    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "not_checked",
        "api_base": api_base,
        "credentials_ready": bool(credentials.get("ready")),
        "connection": None,
        "categories": [],
        "category_comparison": [],
        "tags_checked": False,
        "tags_count": None,
        "future_posts_checked": False,
        "future_posts_count": None,
        "future_posts": [],
        "errors": [],
    }
    if not credentials.get("ready"):
        payload["status"] = "credentials_required"
        payload["errors"].append("WordPress credentials are not ready.")
        write_wordpress_readonly_check(payload)
        return payload

    try:
        payload["connection"] = check_wordpress_connection(
            api_base,
            credentials["username"],
            credentials["application_password"],
        )
    except Exception as exc:
        payload["errors"].append(f"connection: {exc}")

    try:
        categories = fetch_wordpress_taxonomy(api_base, "categories")
        payload["categories"] = categories
        payload["category_comparison"] = compare_configured_categories(configured_categories, categories)
    except Exception as exc:
        payload["errors"].append(f"categories: {exc}")

    try:
        tags = fetch_wordpress_taxonomy(api_base, "tags")
        payload["tags_checked"] = True
        payload["tags_count"] = len(tags)
    except Exception as exc:
        payload["errors"].append(f"tags: {exc}")

    try:
        future_posts = fetch_wordpress_posts(
            api_base,
            credentials["username"],
            credentials["application_password"],
            {"status": "future", "per_page": "100", "_fields": "id,date,date_gmt,status,link,title"},
        )
        payload["future_posts_checked"] = True
        payload["future_posts_count"] = len(future_posts)
        payload["future_posts"] = summarize_posts(future_posts)
    except Exception as exc:
        payload["errors"].append(f"future_posts: {exc}")

    payload["status"] = "ok" if not payload["errors"] else "partial"
    write_wordpress_readonly_check(payload)
    return payload


def build_wordpress_publish_plan(
    post_payload_path: Path | None = None,
    image_plan_path: Path | None = None,
    output_suffix: str = "latest",
) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    post_payload_file = post_payload_path or WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json"
    image_plan_file = image_plan_path or CONFIG_DIR.parent / "03_generated" / "images" / "featured_image_plan_latest.json"
    post_payload = read_json(post_payload_file, {}) or {}
    image_plan = read_json(image_plan_file, {}) or {}
    credentials = read_wordpress_credentials()
    image_path = CONFIG_DIR.parent / str(image_plan.get("output_path", ""))
    image_file_exists = image_path.exists() and image_path.is_file() and image_path.stat().st_size > 0
    image_blocked_reasons = featured_image_gate_reasons(image_plan, image_exists=image_file_exists)
    blocked_reasons = list(dict.fromkeys([*post_payload.get("blocked_reasons", []), *image_blocked_reasons]))
    base_image = image_plan.get("base_image", {}) if isinstance(image_plan.get("base_image"), dict) else {}
    plan = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": settings.get("wordpress_api_base"),
        "credentials_ready": bool(credentials.get("ready")),
        "payload_ready_to_send": bool(post_payload.get("ready_to_send")),
        "blocked_reasons": blocked_reasons,
        "post_status": (post_payload.get("wordpress") or {}).get("status"),
        "post_date": (post_payload.get("wordpress") or {}).get("date"),
        "post_title": (post_payload.get("wordpress") or {}).get("title"),
        "post_payload_path": relative_project_path(post_payload_file),
        "image_plan_path": relative_project_path(image_plan_file),
        "featured_image_path": str(image_path),
        "featured_image_exists": image_file_exists,
        "featured_image_quality_ready": not image_blocked_reasons,
        "featured_image_base_status": base_image.get("status"),
        "featured_image_quality_gate": base_image.get("quality_gate"),
        "featured_image_alt": image_plan.get("alt_text"),
        "arkhe_css_editor": post_payload.get("arkhe_css_editor", {}),
        "write_guard": "Use --execute with KSRFP_ALLOW_WORDPRESS_WRITE=1. Default is dry-run only.",
    }
    plan["status"] = (
        "ready"
        if plan["credentials_ready"]
        and plan["payload_ready_to_send"]
        and plan["featured_image_exists"]
        and plan["featured_image_quality_ready"]
        else "blocked"
    )
    plan["next_action"] = (
        "動作確認フェーズでメディアアップロードと下書き保存を実行する。"
        if plan["status"] == "ready"
        else "停止理由を解消してから、動作確認フェーズで実行する。"
    )
    write_json(WORDPRESS_DIR / f"wordpress_publish_plan_{output_suffix}.json", plan)
    write_markdown(WORDPRESS_DIR / f"wordpress_publish_plan_{output_suffix}.md", render_wordpress_publish_plan(plan))
    if output_suffix != "latest":
        write_json(WORDPRESS_DIR / "wordpress_publish_plan_latest.json", plan)
        write_markdown(WORDPRESS_DIR / "wordpress_publish_plan_latest.md", render_wordpress_publish_plan(plan))
    return plan


def publish_wordpress_payload(
    execute: bool = False,
    post_payload_path: Path | None = None,
    image_plan_path: Path | None = None,
    output_suffix: str = "latest",
) -> dict[str, Any]:
    if not execute:
        plan = build_wordpress_publish_plan(
            post_payload_path=post_payload_path,
            image_plan_path=image_plan_path,
            output_suffix=output_suffix,
        )
        return {"status": "dry_run", "plan": plan}

    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    credentials = read_wordpress_credentials()
    post_payload_file = post_payload_path or WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json"
    image_plan_file = image_plan_path or CONFIG_DIR.parent / "03_generated" / "images" / "featured_image_plan_latest.json"
    post_payload = read_json(post_payload_file, {}) or {}
    image_plan = read_json(image_plan_file, {}) or {}
    image_path = CONFIG_DIR.parent / str(image_plan.get("output_path", ""))
    if not credentials.get("ready"):
        raise RuntimeError("WordPress credentials are not ready.")
    if not post_payload.get("ready_to_send"):
        raise RuntimeError("WordPress payload is not ready to send.")
    image_file_exists = image_path.exists() and image_path.is_file() and image_path.stat().st_size > 0
    if not image_file_exists:
        raise RuntimeError(f"Featured image does not exist: {image_path}")
    image_blocked_reasons = featured_image_gate_reasons(image_plan, image_exists=image_file_exists)
    if image_blocked_reasons:
        raise RuntimeError("Featured image is not ready: " + " / ".join(image_blocked_reasons))
    image_sha256 = file_sha256(image_path)

    wordpress_post = dict(post_payload["wordpress"])
    existing_post = find_recoverable_state_post_for_payload(
        api_base,
        credentials["username"],
        credentials["application_password"],
        post_payload,
    )
    title_duplicates = find_existing_posts_by_exact_title(
        api_base,
        credentials["username"],
        credentials["application_password"],
        str(wordpress_post.get("title") or ""),
    )
    nonrecoverable_duplicates = [
        duplicate for duplicate in title_duplicates
        if not existing_post_can_be_recovered(duplicate)
    ]
    other_topic_duplicates = [
        duplicate for duplicate in title_duplicates
        if existing_post_can_be_recovered(duplicate)
        and not recoverable_post_matches_payload_topic(duplicate, post_payload)
    ]
    recoverable_duplicates = [
        duplicate for duplicate in title_duplicates
        if existing_post_can_be_recovered(duplicate)
        and recoverable_post_matches_payload_topic(duplicate, post_payload)
    ]
    if nonrecoverable_duplicates:
        raise RuntimeError(
            "Duplicate WordPress post title exists in a non-recoverable status: "
            + " / ".join(format_duplicate_post(duplicate) for duplicate in nonrecoverable_duplicates)
        )
    if other_topic_duplicates:
        raise RuntimeError(
            "Duplicate WordPress post title belongs to another automation topic and cannot be reused: "
            + " / ".join(format_duplicate_post(duplicate) for duplicate in other_topic_duplicates)
        )
    if (
        recoverable_duplicates
        and existing_post
        and any(int(duplicate.get("id") or 0) != int(existing_post.get("id") or 0) for duplicate in recoverable_duplicates)
    ):
        raise RuntimeError(
            "Duplicate WordPress post title conflicts with another recoverable draft: "
            f"target_id={existing_post.get('id')} duplicates="
            + " / ".join(format_duplicate_post(duplicate) for duplicate in recoverable_duplicates)
        )
    if recoverable_duplicates and not existing_post:
        existing_post = recoverable_duplicates[0]
        attach_scheduled_record(existing_post)

    existing_post_id = int(existing_post.get("id") or 0) if isinstance(existing_post, dict) else 0
    media = (
        reusable_media_for_existing_post(
            api_base,
            credentials["username"],
            credentials["application_password"],
            existing_post,
            image_sha256,
            str(image_plan.get("alt_text") or ""),
        )
        if existing_post_id
        else None
    )
    media_reused = bool(media)
    uploaded_media_id: int | None = None
    if not media:
        media = upload_media(
            api_base,
            credentials["username"],
            credentials["application_password"],
            image_path,
            str(image_plan.get("alt_text") or ""),
        )
        uploaded_media_id = int(media.get("id") or 0) or None
    wordpress_post["featured_media"] = media["id"]
    try:
        created = (
            update_post(api_base, credentials["username"], credentials["application_password"], existing_post_id, wordpress_post)
            if existing_post_id
            else create_post(api_base, credentials["username"], credentials["application_password"], wordpress_post)
        )
    except Exception:
        if uploaded_media_id:
            delete_wordpress_media_safely(
                api_base,
                credentials["username"],
                credentials["application_password"],
                uploaded_media_id,
            )
        raise
    result = {
        "status": "updated_existing" if existing_post_id else "created",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "duplicate_recovery": {
            "reused_existing_post": bool(existing_post_id),
            "existing_post_id": existing_post_id or None,
            "existing_post_status": existing_post.get("status") if isinstance(existing_post, dict) else None,
        },
        "media": {
            "id": media.get("id"),
            "link": media.get("source_url"),
            "reused_existing_media": media_reused,
        },
        "featured_image": {
            "path": relative_project_path(image_path),
            "sha256": image_sha256,
            "image_plan_path": relative_project_path(image_plan_file),
            "post_payload_path": relative_project_path(post_payload_file),
        },
        "post": {
            "id": created.get("id"),
            "status": created.get("status"),
            "date": created.get("date"),
            "link": created.get("link"),
        },
        "arkhe_css_editor": {"status": "pending", "state_recorded_before_css": True},
        "state_record": None,
        "post_payload_path": relative_project_path(post_payload_file),
        "image_plan_path": relative_project_path(image_plan_file),
    }
    result["state_record"] = record_wordpress_scheduled_post(post_payload, result)
    try:
        arkhe_result = apply_arkhe_css_editor(
            settings,
            credentials["username"],
            credentials["application_password"],
            int(created["id"]),
            str(post_payload.get("arkhe_css_editor", {}).get("css") or ""),
        )
        result["arkhe_css_editor"] = arkhe_result
    except Exception as exc:
        result["arkhe_css_editor"] = {
            "status": "error",
            "error": str(exc),
            "state_recorded_before_error": True,
        }
        write_json(WORDPRESS_DIR / f"wordpress_publish_result_{output_suffix}.json", result)
        write_markdown(WORDPRESS_DIR / f"wordpress_publish_result_{output_suffix}.md", render_wordpress_publish_result(result))
        if output_suffix != "latest":
            write_json(WORDPRESS_DIR / "wordpress_publish_result_latest.json", result)
            write_markdown(WORDPRESS_DIR / "wordpress_publish_result_latest.md", render_wordpress_publish_result(result))
        raise
    write_json(WORDPRESS_DIR / f"wordpress_publish_result_{output_suffix}.json", result)
    write_markdown(WORDPRESS_DIR / f"wordpress_publish_result_{output_suffix}.md", render_wordpress_publish_result(result))
    if output_suffix != "latest":
        write_json(WORDPRESS_DIR / "wordpress_publish_result_latest.json", result)
        write_markdown(WORDPRESS_DIR / "wordpress_publish_result_latest.md", render_wordpress_publish_result(result))
    return result


def relative_project_path(path: Path) -> str:
    try:
        return str(path.relative_to(CONFIG_DIR.parent))
    except ValueError:
        return str(path)


def build_wordpress_post_verification(post_id: int | None = None) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    credentials = read_wordpress_credentials()
    post_payload = read_json(WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json", {}) or {}
    publish_result = read_json(WORDPRESS_DIR / "wordpress_publish_result_latest.json", {}) or {}
    update_result = read_json(WORDPRESS_DIR / "wordpress_update_result_latest.json", {}) or {}
    if post_id is None:
        post_id = int(
            (update_result.get("post") or {}).get("id")
            or (publish_result.get("post") or {}).get("id")
            or 0
        )
    if not post_id:
        raise RuntimeError("WordPress post ID is required for verification.")
    if not credentials.get("ready"):
        raise RuntimeError("WordPress credentials are not ready.")

    post = fetch_wordpress_post(
        api_base,
        credentials["username"],
        credentials["application_password"],
        post_id,
    )
    featured_media_id = int(post.get("featured_media") or 0)
    media = (
        fetch_wordpress_media(
            api_base,
            credentials["username"],
            credentials["application_password"],
            featured_media_id,
        )
        if featured_media_id
        else {}
    )
    expected = post_payload.get("wordpress", {}) if isinstance(post_payload.get("wordpress"), dict) else {}
    expected_status = str(expected.get("status") or settings.get("default_post_status") or "draft")
    if int((update_result.get("post") or {}).get("id") or 0) == post_id:
        expected_status = str((update_result.get("post") or {}).get("status") or expected_status)
        expected_date = (update_result.get("post") or {}).get("date") or expected.get("date")
    else:
        expected_date = expected.get("date")
    update_media_id = int((update_result.get("media") or {}).get("id") or 0)
    publish_media_id = int((publish_result.get("media") or {}).get("id") or 0)
    expected_media_id = update_media_id or publish_media_id
    meta = post.get("meta") if isinstance(post.get("meta"), dict) else {}
    arkhe_meta_candidates = {
        key: value
        for key, value in meta.items()
        if "arkhe" in str(key).lower() or "css" in str(key).lower()
    }
    admin_meta = read_arkhe_css_editor_meta(
        settings,
        credentials["username"],
        credentials["application_password"],
        post_id,
    )
    verification = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "ok",
        "post_id": post_id,
        "post": {
            "id": post.get("id"),
            "status": post.get("status"),
            "date": post.get("date"),
            "date_gmt": post.get("date_gmt"),
            "link": post.get("link"),
            "author": post.get("author"),
            "categories": post.get("categories", []),
            "tags": post.get("tags", []),
            "featured_media": featured_media_id,
            "slug": post.get("slug"),
            "title": post.get("title", {}).get("raw")
            if isinstance(post.get("title"), dict)
            else post.get("title"),
        },
        "media": {
            "id": media.get("id"),
            "source_url": media.get("source_url"),
            "alt_text": media.get("alt_text"),
            "mime_type": media.get("mime_type"),
        },
        "checks": {
            "status_matches_expected": post.get("status") == expected_status,
            "date_matches": normalize_datetime_text(post.get("date")) == normalize_datetime_text(expected_date),
            "author_matches": int(post.get("author") or 0) == int(expected.get("author") or 0),
            "categories_match": sorted(post.get("categories", [])) == sorted(expected.get("categories", [])),
            "tags_empty": post.get("tags", []) == [],
            "featured_media_matches": bool(expected_media_id and featured_media_id == expected_media_id),
            "content_contains_h2": "<h2" in extract_rendered(post.get("content", "")),
            "content_contains_h3": "<h3" in extract_rendered(post.get("content", "")),
            "arkhe_meta_exposed": bool(arkhe_meta_candidates),
            "arkhe_css_saved": bool(admin_meta.get("matches_expected")),
        },
        "arkhe_meta_candidates": arkhe_meta_candidates,
        "arkhe_css_editor": admin_meta,
        "note": "Arkhe CSS Editorのmeta keyがREST APIに公開されていない場合、管理画面での確認が必要。",
    }
    verification["status"] = "ok" if all(
        value
        for key, value in verification["checks"].items()
        if key != "arkhe_meta_exposed"
    ) else "partial"
    write_json(WORDPRESS_DIR / "wordpress_post_verification_latest.json", verification)
    write_markdown(WORDPRESS_DIR / "wordpress_post_verification_latest.md", render_wordpress_post_verification(verification))
    return verification


def fetch_wordpress_taxonomy(api_base: str, taxonomy: str) -> list[dict[str, Any]]:
    params = urlencode({"per_page": "100", "_fields": "id,name,slug,count"})
    request = Request(f"{api_base}/{taxonomy}?{params}")
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_media(
    api_base: str,
    username: str,
    application_password: str,
    image_path: Path,
    alt_text: str,
) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    request = Request(
        f"{api_base}/media",
        data=image_path.read_bytes(),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{image_path.name}"',
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        media = json.loads(response.read().decode("utf-8"))
    if alt_text:
        update_media_alt_text(api_base, username, application_password, int(media["id"]), alt_text)
        media["alt_text"] = alt_text
    return media


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reusable_media_for_existing_post(
    api_base: str,
    username: str,
    application_password: str,
    existing_post: dict[str, Any] | None,
    image_sha256: str,
    alt_text: str,
) -> dict[str, Any] | None:
    if not isinstance(existing_post, dict):
        return None
    state_record = existing_post.get("_automation_state_record")
    if not isinstance(state_record, dict):
        state_record = find_scheduled_record_for_post_id(int(existing_post.get("id") or 0))
    if not isinstance(state_record, dict):
        return None
    if str(state_record.get("featured_image_sha256") or "") != image_sha256:
        return None
    media_id = int(state_record.get("featured_media_id") or existing_post.get("featured_media") or 0)
    if not media_id:
        return None
    try:
        media = fetch_wordpress_media(api_base, username, application_password, media_id)
        if alt_text and str(media.get("alt_text") or "") != alt_text:
            update_media_alt_text(api_base, username, application_password, media_id, alt_text)
            media["alt_text"] = alt_text
        media["reused_existing_media"] = True
        return media
    except Exception:
        return None


def delete_wordpress_media_safely(
    api_base: str,
    username: str,
    application_password: str,
    media_id: int,
) -> dict[str, Any]:
    try:
        return delete_wordpress_media(api_base, username, application_password, media_id)
    except Exception as exc:
        return {"status": "error", "media_id": media_id, "error": str(exc)}


def delete_wordpress_media(api_base: str, username: str, application_password: str, media_id: int) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    request = Request(
        f"{api_base}/media/{media_id}?{urlencode({'force': 'true'})}",
        headers={"Authorization": f"Basic {token}"},
        method="DELETE",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    payload["status"] = "deleted"
    payload["media_id"] = media_id
    return payload


def apply_arkhe_css_editor(
    settings: dict[str, Any],
    username: str,
    application_password: str,
    post_id: int,
    css: str,
) -> dict[str, Any]:
    if not css.strip():
        return {"status": "skipped", "reason": "CSS is empty."}
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    settings_result = update_arkhe_css_settings(
        api_base,
        username,
        application_password,
        css,
    )
    settings_result["post_id"] = post_id
    return settings_result


def update_arkhe_css_settings(api_base: str, username: str, application_password: str, css: str) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    settings_url = api_base.rsplit("/wp/v2", 1)[0] + "/wp/v2/settings"
    request = Request(settings_url, headers={"Authorization": f"Basic {token}"})
    with urlopen(request, timeout=30) as response:
        current = json.loads(response.read().decode("utf-8"))

    front = str(current.get("arkhe_css_front") or "")
    editor = str(current.get("arkhe_css_editor") or "")
    css = css.strip()
    front_new = append_css_if_missing(front, css)
    editor_new = append_css_if_missing(editor, css)
    data = json.dumps(
        {
            "arkhe_css_front": front_new,
            "arkhe_css_editor": editor_new,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        settings_url,
        data=data,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        updated = json.loads(response.read().decode("utf-8"))
    updated_front = str(updated.get("arkhe_css_front") or "")
    updated_editor = str(updated.get("arkhe_css_editor") or "")
    return {
        "status": "updated",
        "method": "rest_settings",
        "settings_keys": ["arkhe_css_front", "arkhe_css_editor"],
        "css_length": len(css),
        "front_contains_css": css in updated_front,
        "editor_contains_css": css in updated_editor,
        "arkhe_css_front_before_length": len(front),
        "arkhe_css_front_after_length": len(updated_front),
        "arkhe_css_editor_before_length": len(editor),
        "arkhe_css_editor_after_length": len(updated_editor),
    }


def append_css_if_missing(existing: str, css: str) -> str:
    if not css:
        return existing
    if css in existing:
        return existing
    separator = "\n\n" if existing.strip() else ""
    return f"{existing.rstrip()}{separator}{css}\n"


def update_post_meta_rest(
    api_base: str,
    username: str,
    application_password: str,
    post_id: int,
    key: str,
    value: str,
) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    data = json.dumps({"meta": {key: value}}, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{api_base}/posts/{post_id}",
        data=data,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "status": "updated",
            "method": "rest_meta",
            "meta_key": key,
            "css_length": len(value),
            "post_id": payload.get("id"),
        }
    except Exception as exc:
        return {
            "status": "error",
            "method": "rest_meta",
            "meta_key": key,
            "error": str(exc),
        }


def read_arkhe_css_editor_meta(
    settings: dict[str, Any],
    username: str,
    application_password: str,
    post_id: int,
) -> dict[str, Any]:
    expected = str(settings.get("arkhe_css_editor", "") or "")
    api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
    token = basic_auth_token(username, application_password)
    settings_url = api_base.rsplit("/wp/v2", 1)[0] + "/wp/v2/settings"
    try:
        request = Request(settings_url, headers={"Authorization": f"Basic {token}"})
        with urlopen(request, timeout=30) as response:
            current = json.loads(response.read().decode("utf-8"))
        front = str(current.get("arkhe_css_front") or "")
        editor = str(current.get("arkhe_css_editor") or "")
        return {
            "status": "ok",
            "method": "rest_settings",
            "post_id": post_id,
            "settings_keys": ["arkhe_css_front", "arkhe_css_editor"],
            "front_value_found": bool(front),
            "editor_value_found": bool(editor),
            "front_value_length": len(front),
            "editor_value_length": len(editor),
            "matches_expected": normalize_css(expected) in normalize_css(front)
            and normalize_css(expected) in normalize_css(editor),
        }
    except Exception as exc:
        return {
            "status": "error",
            "method": "rest_settings",
            "post_id": post_id,
            "error": str(exc),
            "matches_expected": False,
        }


def wordpress_xmlrpc_url(settings: dict[str, Any]) -> str:
    if settings.get("wordpress_xmlrpc_url"):
        return str(settings["wordpress_xmlrpc_url"])
    return "https://ksrfp.com/ksrfp/xmlrpc.php"


def normalize_css(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def update_media_alt_text(
    api_base: str,
    username: str,
    application_password: str,
    media_id: int,
    alt_text: str,
) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    data = json.dumps({"alt_text": alt_text}, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{api_base}/media/{media_id}",
        data=data,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def create_post(api_base: str, username: str, application_password: str, post_data: dict[str, Any]) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    data = json.dumps(post_data, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{api_base}/posts",
        data=data,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def update_post(api_base: str, username: str, application_password: str, post_id: int, post_data: dict[str, Any]) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    data = json.dumps(post_data, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{api_base}/posts/{post_id}",
        data=data,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_wordpress_post(api_base: str, username: str, application_password: str, post_id: int) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    params = urlencode({"context": "edit"})
    request = Request(
        f"{api_base}/posts/{post_id}?{params}",
        headers={"Authorization": f"Basic {token}"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_wordpress_media(api_base: str, username: str, application_password: str, media_id: int) -> dict[str, Any]:
    token = basic_auth_token(username, application_password)
    params = urlencode({"context": "edit"})
    request = Request(
        f"{api_base}/media/{media_id}?{params}",
        headers={"Authorization": f"Basic {token}"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_datetime_text(value: Any) -> str:
    return str(value or "").replace("+09:00", "")[:19]


def extract_rendered(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("rendered") or value.get("raw") or "")
    return str(value or "")


def fetch_wordpress_posts(
    api_base: str,
    username: str,
    application_password: str,
    params: dict[str, str],
) -> list[dict[str, Any]]:
    token = basic_auth_token(username, application_password)
    request = Request(
        f"{api_base}/posts?{urlencode(params)}",
        headers={"Authorization": f"Basic {token}"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def find_existing_post_by_exact_title(
    api_base: str,
    username: str,
    application_password: str,
    title: str,
) -> dict[str, Any] | None:
    matches = find_existing_posts_by_exact_title(api_base, username, application_password, title)
    return matches[0] if matches else None


def find_existing_posts_by_exact_title(
    api_base: str,
    username: str,
    application_password: str,
    title: str,
) -> list[dict[str, Any]]:
    normalized_target = normalize_title_for_duplicate_check(title)
    if not normalized_target:
        return []
    matches: list[dict[str, Any]] = []
    for status in ["draft", "future", "pending", "private", "publish"]:
        posts = fetch_wordpress_posts(
            api_base,
            username,
            application_password,
            {
                "status": status,
                "search": title,
                "per_page": "20",
                "context": "edit",
                "_fields": "id,title,status,date,link,slug,featured_media",
            },
        )
        for post in posts:
            title_value = post.get("title", {}) if isinstance(post.get("title"), dict) else post.get("title")
            title_text = (
                str(title_value.get("raw") or title_value.get("rendered") or "")
                if isinstance(title_value, dict)
                else str(title_value or "")
            )
            if normalize_title_for_duplicate_check(title_text) == normalized_target:
                duplicate = dict(post)
                duplicate["title_text"] = normalize_visible_text(title_text)
                matches.append(duplicate)
    return matches


def format_duplicate_post(post: dict[str, Any]) -> str:
    return f"id={post.get('id')} status={post.get('status')} title={post.get('title_text')}"


def existing_post_can_be_recovered(post: dict[str, Any]) -> bool:
    """Only reuse non-public posts already recorded by this automation."""
    if str(post.get("status") or "") not in {"draft", "future", "pending", "private"}:
        return False
    post_id = int(post.get("id") or 0)
    if not post_id:
        return False
    return bool(find_scheduled_record_for_post_id(post_id))


def scheduled_post_items() -> list[dict[str, Any]]:
    scheduled = read_json(CONFIG_DIR.parent / "08_state" / "scheduled_posts.json", {}) or {}
    items = scheduled.get("items", []) if isinstance(scheduled.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def find_scheduled_record_for_post_id(post_id: int) -> dict[str, Any] | None:
    matches = [
        item for item in scheduled_post_items()
        if int(item.get("wordpress_post_id") or 0) == int(post_id or 0)
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: str(item.get("created_at") or ""))[-1]


def find_scheduled_record_for_topic_key(topic_key: str) -> dict[str, Any] | None:
    matches = [
        item for item in scheduled_post_items()
        if str(item.get("topic_key") or "") == str(topic_key or "") and item.get("wordpress_post_id")
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: str(item.get("created_at") or ""))[-1]


def attach_scheduled_record(post: dict[str, Any]) -> dict[str, Any]:
    record = find_scheduled_record_for_post_id(int(post.get("id") or 0))
    if record:
        post["_automation_state_record"] = record
    return post


def find_recoverable_state_post_for_payload(
    api_base: str,
    username: str,
    application_password: str,
    post_payload: dict[str, Any],
) -> dict[str, Any] | None:
    source = post_payload.get("source", {}) if isinstance(post_payload.get("source"), dict) else {}
    topic_key = stable_key(source.get("pdf_name"), source.get("section_group"), source.get("topic_title"))
    if not topic_key:
        return None
    latest = find_scheduled_record_for_topic_key(topic_key)
    if not latest:
        return None
    post_id = int(latest.get("wordpress_post_id") or 0)
    if not post_id:
        return None
    try:
        post = fetch_wordpress_post(api_base, username, application_password, post_id)
    except Exception:
        return None
    title_value = post.get("title", {}) if isinstance(post.get("title"), dict) else post.get("title")
    title_text = (
        str(title_value.get("raw") or title_value.get("rendered") or "")
        if isinstance(title_value, dict)
        else str(title_value or "")
    )
    post["title_text"] = normalize_visible_text(title_text)
    post["_automation_state_record"] = latest
    return post if existing_post_can_be_recovered(post) else None


def recoverable_post_matches_payload_topic(post: dict[str, Any], post_payload: dict[str, Any]) -> bool:
    post_id = int(post.get("id") or 0)
    if not post_id:
        return False
    source = post_payload.get("source", {}) if isinstance(post_payload.get("source"), dict) else {}
    topic_key = stable_key(source.get("pdf_name"), source.get("section_group"), source.get("topic_title"))
    return any(
        int(item.get("wordpress_post_id") or 0) == post_id and item.get("topic_key") == topic_key
        for item in scheduled_post_items()
    )


def normalize_title_for_duplicate_check(value: str) -> str:
    return normalize_visible_text(value).replace(" ", "")


def normalize_visible_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def compare_configured_categories(
    configured_categories: list[dict[str, Any]],
    live_categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    live_by_slug = {category.get("slug"): category for category in live_categories}
    rows = []
    for configured in configured_categories:
        live = live_by_slug.get(configured.get("slug"))
        rows.append(
            {
                "slug": configured.get("slug"),
                "configured_id": configured.get("id"),
                "configured_name": configured.get("name"),
                "live_id": live.get("id") if live else None,
                "live_name": live.get("name") if live else None,
                "matched": bool(live and int(live.get("id")) == int(configured.get("id"))),
            }
        )
    return rows


def summarize_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for post in posts:
        title = post.get("title", {})
        rows.append(
            {
                "id": post.get("id"),
                "date": post.get("date"),
                "status": post.get("status"),
                "link": post.get("link"),
                "title": title.get("rendered") if isinstance(title, dict) else title,
            }
        )
    return rows


def write_wordpress_readonly_check(payload: dict[str, Any]) -> None:
    write_json(WORDPRESS_DIR / "wordpress_readonly_check_latest.json", payload)
    write_markdown(WORDPRESS_DIR / "wordpress_readonly_check_latest.md", render_wordpress_readonly_check(payload))


def render_wordpress_readonly_check(payload: dict[str, Any]) -> str:
    connection = payload.get("connection") or {}
    lines = [
        "# WordPress読み取り専用チェック",
        "",
        f"- 生成日時: {payload['generated_at']}",
        f"- ステータス: {payload['status']}",
        f"- APIベースURL: {payload['api_base']}",
        f"- 認証情報準備OK: {payload['credentials_ready']}",
        f"- 認証接続OK: {connection.get('ok', False)}",
        f"- HTTPステータス: {connection.get('http_status', '未確認')}",
        f"- 認証ユーザーID: {connection.get('user_id', '未確認')}",
        f"- 認証ユーザーslug: {connection.get('user_slug', '未確認')}",
        f"- カテゴリ取得数: {len(payload.get('categories', []))}",
        f"- タグ取得済み: {payload.get('tags_checked')}",
        f"- タグ数: {payload.get('tags_count') if payload.get('tags_count') is not None else '未確認'}",
        f"- 予約投稿取得済み: {payload.get('future_posts_checked')}",
        f"- 予約投稿数: {payload.get('future_posts_count') if payload.get('future_posts_count') is not None else '未確認'}",
        "",
        "## カテゴリ照合",
        "",
    ]
    for row in payload.get("category_comparison", []):
        status = "OK" if row.get("matched") else "要確認"
        lines.append(
            f"- {status}: {row.get('slug')} / 設定ID {row.get('configured_id')} / API ID {row.get('live_id')} / API名 {row.get('live_name')}"
        )
    if not payload.get("category_comparison"):
        lines.append("- 未取得")

    lines.extend(["", "## 予約投稿", ""])
    for post in payload.get("future_posts", []):
        lines.append(f"- {post.get('date')} / ID {post.get('id')} / {post.get('title')}")
    if not payload.get("future_posts"):
        lines.append("- なし")

    lines.extend(["", "## エラー", ""])
    if payload.get("errors"):
        lines.extend(f"- {error}" for error in payload["errors"])
    else:
        lines.append("- なし")
    lines.extend(["", "## 注意", "", "- このチェックは読み取り専用であり、投稿・更新・削除は行わない。"])
    return "\n".join(lines)


def render_wordpress_publish_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# WordPress投稿実行計画",
        "",
        f"- 生成日時: {plan['generated_at']}",
        f"- ステータス: {plan['status']}",
        f"- APIベースURL: {plan['api_base']}",
        f"- 認証情報準備OK: {plan['credentials_ready']}",
        f"- 投稿ペイロード送信可能: {plan['payload_ready_to_send']}",
        f"- 投稿ステータス: {plan['post_status']}",
        f"- 設定日時: {plan['post_date']}",
        f"- 投稿タイトル: {plan['post_title']}",
        f"- アイキャッチ画像: {plan['featured_image_path']}",
        f"- アイキャッチ画像検出: {plan['featured_image_exists']}",
        f"- アイキャッチ品質OK: {plan.get('featured_image_quality_ready')}",
        f"- アイキャッチ背景: {plan.get('featured_image_base_status')}",
        f"- アイキャッチ品質ゲート: {plan.get('featured_image_quality_gate')}",
        f"- アイキャッチalt: {plan['featured_image_alt']}",
        f"- 書き込みガード: {plan['write_guard']}",
        f"- 次の対応: {plan['next_action']}",
        "",
        "## 停止理由",
        "",
    ]
    if plan["blocked_reasons"]:
        lines.extend(f"- {reason}" for reason in plan["blocked_reasons"])
    else:
        lines.append("- なし")
    arkhe = plan.get("arkhe_css_editor") or {}
    lines.extend(
        [
            "",
            "## Arkhe CSS Editor",
            "",
            f"- CSS設定あり: {bool(arkhe.get('css'))}",
            f"- REST meta key: {arkhe.get('rest_meta_key') or '未確認'}",
            f"- メモ: {arkhe.get('note') or 'なし'}",
            "",
            "## 注意",
            "",
            "- この計画ファイルの生成だけでは、WordPressへの書き込みは行わない。",
            "- 実行には明示的な `--execute` と環境変数 `KSRFP_ALLOW_WORDPRESS_WRITE=1` が必要。",
        ]
    )
    return "\n".join(lines)


def render_wordpress_publish_result(result: dict[str, Any]) -> str:
    post = result.get("post", {})
    media = result.get("media", {})
    return "\n".join(
        [
            "# WordPress投稿実行結果",
            "",
            f"- 生成日時: {result['generated_at']}",
            f"- ステータス: {result['status']}",
            f"- メディアID: {media.get('id')}",
            f"- メディアURL: {media.get('link')}",
            f"- 投稿ID: {post.get('id')}",
            f"- 投稿ステータス: {post.get('status')}",
            f"- 設定日時: {post.get('date')}",
            f"- 投稿URL: {post.get('link')}",
        ]
    )


def render_wordpress_post_verification(verification: dict[str, Any]) -> str:
    post = verification.get("post", {})
    media = verification.get("media", {})
    checks = verification.get("checks", {})
    lines = [
        "# WordPress投稿検証結果",
        "",
        f"- 生成日時: {verification['generated_at']}",
        f"- ステータス: {verification['status']}",
        f"- 投稿ID: {verification['post_id']}",
        f"- 投稿ステータス: {post.get('status')}",
        f"- 設定日時: {post.get('date')}",
        f"- 投稿URL: {post.get('link')}",
        f"- 投稿者ID: {post.get('author')}",
        f"- カテゴリID: {post.get('categories')}",
        f"- タグ: {post.get('tags')}",
        f"- アイキャッチID: {post.get('featured_media')}",
        f"- アイキャッチURL: {media.get('source_url')}",
        f"- アイキャッチalt: {media.get('alt_text')}",
        f"- WordPress生成slug: {post.get('slug')}",
        "",
        "## チェック",
        "",
    ]
    for key, value in checks.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Arkhe CSS Editor候補meta", ""])
    candidates = verification.get("arkhe_meta_candidates", {})
    if candidates:
        for key in candidates:
            lines.append(f"- {key}")
    else:
        lines.append("- REST APIレスポンス上では未検出")
    lines.extend(["", "## メモ", "", f"- {verification.get('note') or 'なし'}"])
    return "\n".join(lines)


def scrub_secret_fields(status: dict[str, Any]) -> dict[str, Any]:
    clean = dict(status)
    clean.pop("username", None)
    clean.pop("application_password", None)
    return clean


def render_wordpress_status(status: dict[str, Any]) -> str:
    lines = [
        "# WordPress連携ステータス",
        "",
        f"- 生成日時: {status['generated_at']}",
        f"- ステータス: {status['status']}",
        f"- 外部API有効: {status['external_api_enabled']}",
        f"- APIベースURL: {status['api_base']}",
        f"- 秘密情報ファイル検出: {status['secret_file_found']}",
        f"- ユーザー名検出: {status['username_found']}",
        f"- アプリケーションパスワード検出: {status['application_password_found']}",
        f"- ペイロード検出: {status['payload_found']}",
        f"- ペイロード送信可能: {status['payload_ready_to_send']}",
        f"- 投稿ステータス: {status['post_status']}",
        f"- 接続確認済み: {status['connection_checked']}",
        f"- 接続OK: {status['connection_ok']}",
        f"- 次の対応: {status['next_action']}",
        "",
        "## 注意",
        "",
        "- このレポートにはユーザー名・パスワードの値を出力しない。",
        "- ペイロードが `ready_to_send=false` の場合、WordPress API送信へ進まない。",
        "- 読み取り専用の接続確認は `wordpress_readonly_check_latest.md` に分けて記録する。",
    ]
    return "\n".join(lines)
