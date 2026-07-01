from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .io_utils import read_json, read_text, write_json, write_markdown
from .paths import CONFIG_DIR, GENERATED_DIR


DRIVE_UPLOAD_URL = (
    "https://www.googleapis.com/upload/drive/v3/files"
    "?uploadType=multipart&supportsAllDrives=true&fields=id%2Cname%2CmimeType%2CwebViewLink"
)
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_TOKEN_PATH = CONFIG_DIR / "secrets" / "google_drive_access_token.txt"


def build_review_text_file(upload: bool = False) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    folder_id = str(settings.get("review_text_drive_folder_id") or "")
    generated_at = datetime.now()
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    article_markdown = read_text(article_path) if article_path.exists() else ""
    title = extract_title(article_markdown)
    body = extract_body(article_markdown)
    file_name = build_review_file_name(title, now=generated_at)
    output_dir = GENERATED_DIR / "review-texts"
    output_path = output_dir / file_name
    text = render_review_text(title, body)
    write_markdown(output_path, text)
    write_markdown(output_dir / "review_text_latest.txt", text)

    upload_result = {"status": "skipped", "reason": "upload flag is false"}
    if upload:
        upload_result = {
            "status": "blocked_deprecated_upload_entrypoint",
            "reason": (
                "Drive upload from build_review_text_file() is disabled. "
                "Use run_review_text_batch_upload.py after WordPress batch verification."
            ),
        }

    result = {
        "status": "ok" if article_markdown else "no_article",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "title": title,
        "file_name": file_name,
        "file_date_source": generated_at.isoformat(timespec="seconds"),
        "file_date_source_type": "created_at",
        "output_path": f"03_generated/review-texts/{file_name}",
        "latest_path": "03_generated/review-texts/review_text_latest.txt",
        "drive_folder_id": folder_id,
        "drive_folder_url": f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else "",
        "upload": upload_result,
    }
    write_json(output_dir / "review_text_latest.json", result)
    write_markdown(output_dir / "review_text_latest.md", render_review_text_report(result))
    return result


def extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
    return match.group(1).strip() if match else "記事タイトル未設定"


def extract_body(markdown: str) -> str:
    body = re.sub(r"^#\s+.+\n+", "", markdown, count=1, flags=re.MULTILINE)
    body = re.sub(r"<!--.*?-->\s*", "", body, flags=re.DOTALL)
    return body.strip()


def render_review_text(title: str, body: str) -> str:
    return "\n".join(
        [
            "＜記事タイトル＞",
            "",
            title.strip(),
            "",
            "ーーーーーーーーーー",
            "＜記事本文＞",
            "",
            body.strip(),
        ]
    )


def build_review_file_name(title: str, now: datetime | None = None) -> str:
    current = now or datetime.now()
    date_prefix = current.strftime("%y%m%d")
    safe_title = sanitize_filename(title)
    return f"{date_prefix} {safe_title}.txt"


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:90] or "記事タイトル未設定"


def upload_review_text(path: Path, folder_id: str) -> dict[str, Any]:
    if not folder_id:
        return {"status": "blocked", "reason": "review_text_drive_folder_id is empty"}
    if not DRIVE_TOKEN_PATH.exists():
        return {
            "status": "auth_required",
            "reason": "Google Drive access token is not configured.",
            "token_path": "config/secrets/google_drive_access_token.txt",
        }
    access_token = read_text(DRIVE_TOKEN_PATH).strip()
    if not access_token:
        return {"status": "auth_required", "reason": "Google Drive access token file is empty."}
    try:
        existing = find_drive_file_by_name(path.name, folder_id, access_token)
        if existing:
            result = update_file_in_drive(path, str(existing["id"]), access_token)
            result["duplicate_name_count"] = existing.get("duplicate_name_count", 1)
            result["method"] = result.get("method") or "updated_existing_file"
            return result
        return upload_file_to_drive(path, folder_id, access_token)
    except HTTPError as exc:
        return {"status": "error", "reason": f"Google Drive upload failed: HTTP {exc.code}"}
    except URLError as exc:
        return {"status": "error", "reason": f"Google Drive upload failed: {exc.reason}"}
    except Exception as exc:
        return {"status": "error", "reason": f"Google Drive upload failed: {type(exc).__name__}: {exc}"}


def upload_file_to_drive(path: Path, folder_id: str, access_token: str) -> dict[str, Any]:
    boundary = f"ksrfp-review-text-{uuid4().hex}"
    metadata = {
        "name": path.name,
        "mimeType": "text/plain",
        "parents": [folder_id],
    }
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
            json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode("utf-8"),
            b"Content-Type: text/plain; charset=UTF-8\r\n\r\n",
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = Request(
        DRIVE_UPLOAD_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    return {
        "status": "uploaded",
        "file_id": data.get("id"),
        "name": data.get("name"),
        "mimeType": data.get("mimeType"),
        "webViewLink": data.get("webViewLink") or f"https://drive.google.com/file/d/{data.get('id')}/view",
    }


def find_drive_file_by_name(file_name: str, folder_id: str, access_token: str) -> dict[str, Any] | None:
    escaped_name = file_name.replace("\\", "\\\\").replace("'", "\\'")
    escaped_folder = folder_id.replace("\\", "\\\\").replace("'", "\\'")
    params = urlencode(
        {
            "q": f"name = '{escaped_name}' and '{escaped_folder}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": "10",
            "orderBy": "modifiedTime desc",
        }
    )
    request = Request(
        f"{DRIVE_FILES_URL}?{params}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    files = data.get("files", [])
    if not files:
        return None
    selected = dict(files[0])
    selected["duplicate_name_count"] = len(files)
    return selected


def update_file_in_drive(path: Path, file_id: str, access_token: str) -> dict[str, Any]:
    boundary = f"ksrfp-review-text-{uuid4().hex}"
    metadata = {
        "name": path.name,
        "mimeType": "text/plain",
    }
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
            json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode("utf-8"),
            b"Content-Type: text/plain; charset=UTF-8\r\n\r\n",
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = Request(
        f"{DRIVE_UPLOAD_URL.rsplit('/files', 1)[0]}/files/{file_id}?uploadType=multipart&supportsAllDrives=true&fields=id%2Cname%2CmimeType%2CwebViewLink",
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        method="PATCH",
    )
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    return {
        "status": "uploaded",
        "method": "updated_existing_file",
        "file_id": data.get("id"),
        "name": data.get("name"),
        "mimeType": data.get("mimeType"),
        "webViewLink": data.get("webViewLink") or f"https://drive.google.com/file/d/{data.get('id')}/view",
    }


def render_review_text_report(result: dict[str, Any]) -> str:
    upload = result.get("upload", {})
    return "\n".join(
        [
            "# 確認用テキスト生成結果",
            "",
            f"- 生成日時: {result['generated_at']}",
            f"- ステータス: {result['status']}",
            f"- 記事タイトル: {result['title']}",
            f"- ファイル名: {result['file_name']}",
            f"- ファイル名日付: {result.get('file_date_source') or 'generated_at'}",
            f"- ファイル名日付の種類: {result.get('file_date_source_type') or 'created_at'}",
            f"- 保存先: {result['output_path']}",
            f"- Driveフォルダ: {result.get('drive_folder_url') or '未設定'}",
            f"- Driveアップロード: {upload.get('status')}",
            f"- DriveファイルID: {upload.get('file_id') or '未取得'}",
            f"- Drive URL: {upload.get('webViewLink') or '未取得'}",
        ]
    )
