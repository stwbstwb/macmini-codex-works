from __future__ import annotations

import json
import re
from html import unescape
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen

from .io_utils import read_json, read_text, write_json, write_markdown
from .paths import CONFIG_DIR, DRIVE_DIR, DRIVE_NEWSLETTER_DIR, LOCAL_NEWSLETTER_DIR
from .state_manager import completed_pdf_names, ensure_state_files


DRIVE_TOKEN_PATH = CONFIG_DIR / "secrets" / "google_drive_access_token.txt"
DRIVE_PUBLIC_FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}?usp=drive_link"
DRIVE_DIRECT_DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"
DRIVE_USERCONTENT_DOWNLOAD_URL = "https://drive.usercontent.google.com/download?export=download&id={file_id}&confirm=t"
PUBLIC_PDF_PATTERN = re.compile(
    r'\[\[null,"(?P<id>[A-Za-z0-9_-]{20,})"\].{0,2600}?\[\[\["(?P<name>[^"]+\.pdf)"',
    flags=re.DOTALL,
)


def build_drive_status() -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    external_enabled = bool(settings.get("enable_external_api_calls"))
    folder_id = settings.get("google_drive_folder_id", "")
    token_exists = DRIVE_TOKEN_PATH.exists()
    public_folder_enabled = bool(settings.get("google_drive_public_folder_enabled", True))
    download_latest_enabled = bool(settings.get("google_drive_download_latest", True))
    local_pdfs = local_pdf_inventory()

    status: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "not_checked",
        "external_api_enabled": external_enabled,
        "public_folder_enabled": public_folder_enabled,
        "download_latest_enabled": download_latest_enabled,
        "auth_token_found": token_exists,
        "folder_id": folder_id,
        "drive_pdf_count": None,
        "drive_pdfs": [],
        "latest_drive_pdf": None,
        "selected_drive_pdf": None,
        "all_drive_pdfs_completed": False,
        "downloaded_pdf": None,
        "local_pdf_count": len(local_pdfs),
        "local_pdfs": local_pdfs,
        "latest_local_pdf": local_pdfs[0] if local_pdfs else None,
        "next_action": None,
    }

    if public_folder_enabled:
        try:
            drive_pdfs = list_public_drive_pdfs(folder_id)
            latest_drive_pdf = drive_pdfs[0] if drive_pdfs else None
            selected_drive_pdf = select_uncompleted_drive_pdf(drive_pdfs)
            status["status"] = "ok" if drive_pdfs else "no_drive_pdfs"
            status["drive_pdf_count"] = len(drive_pdfs)
            status["drive_pdfs"] = drive_pdfs
            status["latest_drive_pdf"] = latest_drive_pdf
            status["selected_drive_pdf"] = selected_drive_pdf
            status["all_drive_pdfs_completed"] = bool(drive_pdfs and not selected_drive_pdf)
            if selected_drive_pdf and download_latest_enabled:
                downloaded = ensure_drive_pdf_downloaded(selected_drive_pdf)
                status["downloaded_pdf"] = downloaded
                status["local_pdfs"] = local_pdf_inventory()
                status["local_pdf_count"] = len(status["local_pdfs"])
                status["latest_local_pdf"] = status["local_pdfs"][0] if status["local_pdfs"] else None
            if selected_drive_pdf:
                status["next_action"] = "未作成の最新号を解析対象にする。"
            elif drive_pdfs:
                status["next_action"] = "Drive上の全PDFが記事作成済みのため、記事作成を停止して通知する。"
            else:
                status["next_action"] = "DriveフォルダにPDFがあるか確認する。"
        except Exception as exc:
            status["status"] = "public_folder_error"
            status["error"] = str(exc)
            status["next_action"] = "公開フォルダの権限、ネットワーク接続、HTML構造変更を確認する。"
    elif not external_enabled:
        status["status"] = "external_api_disabled"
        status["next_action"] = "Google Drive API認証または公開フォルダ取得を有効化する。"
    elif not token_exists:
        status["status"] = "auth_required"
        status["next_action"] = "Google Drive APIのアクセストークンを config/secrets/google_drive_access_token.txt に保存する。"
    else:
        try:
            drive_pdfs = list_drive_pdfs(folder_id, read_text(DRIVE_TOKEN_PATH).strip())
            status["status"] = "ok"
            status["drive_pdf_count"] = len(drive_pdfs)
            status["drive_pdfs"] = drive_pdfs
            status["next_action"] = "最新PDFをダウンロードして解析対象にする。"
        except Exception as exc:
            status["status"] = "error"
            status["error"] = str(exc)
            status["next_action"] = "認証情報、フォルダ権限、ネットワーク接続を確認する。"

    write_json(DRIVE_DIR / "drive_status_latest.json", status)
    write_markdown(DRIVE_DIR / "drive_status_latest.md", render_drive_status(status))
    return status


def select_uncompleted_drive_pdf(drive_pdfs: list[dict[str, Any]]) -> dict[str, Any] | None:
    state = ensure_state_files()
    completed = completed_pdf_names(state.get("processed_pdfs", {}))
    for item in drive_pdfs:
        if item.get("name") not in completed:
            return item
    return None


def local_pdf_inventory() -> list[dict[str, Any]]:
    pdfs = list(DRIVE_NEWSLETTER_DIR.glob("*.pdf")) + list(LOCAL_NEWSLETTER_DIR.glob("*.pdf"))
    rows: list[dict[str, Any]] = []
    for path in pdfs:
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "source": "drive-downloads" if DRIVE_NEWSLETTER_DIR in path.parents else "local-samples",
                "period_key": period_key(path.name),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    rows.sort(key=lambda row: (row["period_key"], row["modified_at"], row["name"]), reverse=True)
    return rows


def list_public_drive_pdfs(folder_id: str) -> list[dict[str, Any]]:
    request = Request(
        DRIVE_PUBLIC_FOLDER_URL.format(folder_id=folder_id),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    return parse_public_drive_pdfs(html)


def parse_public_drive_pdfs(html: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for match in PUBLIC_PDF_PATTERN.finditer(html):
        file_id = match.group("id")
        name = unescape(match.group("name"))
        if file_id in seen:
            continue
        seen.add(file_id)
        rows.append(
            {
                "id": file_id,
                "name": name,
                "period_key": period_key(name),
                "mimeType": "application/pdf",
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
                "downloadLink": DRIVE_DIRECT_DOWNLOAD_URL.format(file_id=file_id),
            }
        )
    rows.sort(key=lambda row: (row["period_key"], row["name"], row["id"]), reverse=True)
    return rows


def ensure_drive_pdf_downloaded(item: dict[str, Any]) -> dict[str, Any]:
    DRIVE_NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)
    filename = safe_pdf_filename(str(item["name"]))
    destination = DRIVE_NEWSLETTER_DIR / filename
    if destination.exists() and destination.stat().st_size > 0:
        return {
            "status": "already_exists",
            "name": filename,
            "path": str(destination),
            "size": destination.stat().st_size,
        }
    data = download_drive_file(str(item["id"]))
    if not data.startswith(b"%PDF"):
        raise ValueError(f"Downloaded file is not a PDF: {filename}")
    destination.write_bytes(data)
    return {
        "status": "downloaded",
        "name": filename,
        "path": str(destination),
        "size": destination.stat().st_size,
    }


def download_drive_file(file_id: str) -> bytes:
    opener = build_opener(HTTPCookieProcessor())
    for url in [
        DRIVE_DIRECT_DOWNLOAD_URL.format(file_id=file_id),
        DRIVE_USERCONTENT_DOWNLOAD_URL.format(file_id=file_id),
    ]:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(request, timeout=60) as response:
            data = response.read()
        if data.startswith(b"%PDF"):
            return data
    return data


def safe_pdf_filename(name: str) -> str:
    cleaned = Path(name).name
    cleaned = re.sub(r"[/:\\]+", "_", cleaned)
    return cleaned if cleaned.lower().endswith(".pdf") else f"{cleaned}.pdf"


def period_key(name: str) -> str:
    match = re.search(r"(20\d{2})\.(\d{1,2})", name)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    return "0000-00"


def list_drive_pdfs(folder_id: str, access_token: str) -> list[dict[str, Any]]:
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    params = urlencode(
        {
            "q": query,
            "fields": "files(id,name,modifiedTime,size,webViewLink,mimeType)",
            "orderBy": "modifiedTime desc",
            "pageSize": "100",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
    )
    request = Request(
        f"https://www.googleapis.com/drive/v3/files?{params}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("files", [])


def render_drive_status(status: dict[str, Any]) -> str:
    lines = [
        "# Google Drive連携ステータス",
        "",
        f"- 生成日時: {status['generated_at']}",
        f"- ステータス: {status['status']}",
        f"- 外部API有効: {status['external_api_enabled']}",
        f"- 公開フォルダ取得有効: {status['public_folder_enabled']}",
        f"- 最新PDFダウンロード有効: {status['download_latest_enabled']}",
        f"- 認証トークン検出: {status['auth_token_found']}",
        f"- DriveフォルダID: {status['folder_id']}",
        f"- Drive PDF数: {status['drive_pdf_count'] if status['drive_pdf_count'] is not None else '未取得'}",
        f"- 最新Drive PDF: {status['latest_drive_pdf'].get('name') if status.get('latest_drive_pdf') else '未取得'}",
        f"- 今回解析対象PDF: {status['selected_drive_pdf'].get('name') if status.get('selected_drive_pdf') else 'なし'}",
        f"- Drive上の全PDF作成済み: {status.get('all_drive_pdfs_completed')}",
        f"- ダウンロード結果: {status['downloaded_pdf'].get('status') if status.get('downloaded_pdf') else 'なし'}",
        f"- ローカルPDF数: {status['local_pdf_count']}",
        f"- 次の対応: {status['next_action']}",
        "",
        "## ローカルPDF候補",
        "",
    ]
    for item in status["local_pdfs"][:10]:
        lines.append(f"- {item['name']}（{item['source']} / {item['period_key']}）")
    if not status["local_pdfs"]:
        lines.append("- なし")
    lines.extend(["", "## Drive PDF候補", ""])
    for item in status["drive_pdfs"][:20]:
        lines.append(f"- {item.get('name')}（{item.get('modifiedTime')} / {item.get('id')}）")
    if not status["drive_pdfs"]:
        lines.append("- 未取得")
    return "\n".join(lines)
