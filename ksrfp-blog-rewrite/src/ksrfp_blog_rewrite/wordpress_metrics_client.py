from __future__ import annotations

import base64
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .io_utils import read_json, read_text
from .paths import CONFIG_DIR, PROJECT_ROOT


WORDPRESS_SECRET_NAME_HINTS = (
    "wordpress",
    "wp",
    "アプリケーション",
    "パスワード",
)

NON_WORDPRESS_SECRET_NAMES = {
    "email_smtp.json",
}


class WordPressMetricsError(RuntimeError):
    """Raised when the rewrite metrics endpoint cannot be read."""


def read_settings() -> dict[str, Any]:
    return read_json(CONFIG_DIR / "project_settings.json", {}) or {}


def build_basic_auth_token(username: str, application_password: str) -> str:
    raw = f"{username}:{application_password}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def read_wordpress_credentials(settings: dict[str, Any]) -> dict[str, Any]:
    env_username = os.environ.get("KSRFP_WP_USERNAME")
    env_password = os.environ.get("KSRFP_WP_APPLICATION_PASSWORD")

    if env_username and env_password:
        return {
            "ready": True,
            "username": env_username,
            "application_password": env_password,
            "source": "environment",
        }

    secret_path = os.environ.get("KSRFP_WORDPRESS_SECRET_PATH") or settings.get("wordpress_secret_path")
    if secret_path:
        path = resolve_project_path(str(secret_path))
        credentials = read_credentials_file(path)
        if credentials["ready"]:
            credentials["source"] = str(path)
            return credentials

    for directory in settings.get("wordpress_secret_search_dirs", []):
        secret_file = find_secret_file(resolve_project_path(str(directory)))
        if not secret_file:
            continue
        credentials = read_credentials_file(secret_file)
        if credentials["ready"]:
            credentials["source"] = str(secret_file)
            return credentials

    return {
        "ready": False,
        "username": None,
        "application_password": None,
        "source": None,
    }


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def find_secret_file(directory: Path) -> Path | None:
    if not directory.exists():
        return None

    candidates = sorted([*directory.glob("*.rtf"), *directory.glob("*.json"), *directory.glob("*.txt")])
    candidates = [path for path in candidates if path.name.lower() not in {"readme.md", *NON_WORDPRESS_SECRET_NAMES}]
    hinted = [path for path in candidates if has_wordpress_secret_name_hint(path.name)]

    return hinted[0] if hinted else candidates[0] if candidates else None


def has_wordpress_secret_name_hint(name: str) -> bool:
    normalized = unicodedata.normalize("NFC", name).lower()
    return any(hint in normalized for hint in WORDPRESS_SECRET_NAME_HINTS)


def read_credentials_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ready": False,
        "username": None,
        "application_password": None,
        "source": str(path),
    }

    if not path.exists():
        return result

    text = read_text(path)
    username = None
    password = None

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        username = data.get("username") or data.get("user") or data.get("login")
        password = data.get("application_password") or data.get("app_password") or data.get("password")
    else:
        plain = rtf_to_text(text) if path.suffix.lower() == ".rtf" else text
        username = find_labeled_value(plain, ["ユーザー名", "ログインID", "username", "user", "login"])
        password = find_labeled_value(plain, ["アプリケーションパスワード", "application password", "app password", "password"])

    result["username"] = clean_secret_value(username) if isinstance(username, str) else None
    result["application_password"] = clean_secret_value(password) if isinstance(password, str) else None
    result["ready"] = bool(result["username"] and result["application_password"])
    return result


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
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized_labels = {normalize_label(label) for label in labels}

    for line in lines:
        for separator in ("：", ":"):
            if separator not in line:
                continue
            left, right = line.split(separator, 1)
            if normalize_label(left) in normalized_labels and right.strip():
                return right.strip()

    for label in labels:
        pattern = re.compile(rf"{re.escape(label)}\s*[:：]\s*([^|\n\r]+)", flags=re.IGNORECASE)
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            value = re.split(
                r"\s{3,}|(?:ユーザー名|ログインID|username|user|login|アプリケーションパスワード|application password|app password|password)\s*[:：]",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            return value.strip()

    for index, line in enumerate(lines):
        normalized_line = normalize_label(line)
        for label in labels:
            if normalize_label(label) == normalized_line and index + 1 < len(lines):
                return lines[index + 1].strip()

    return None


def normalize_label(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).lower())


def clean_secret_value(value: str) -> str:
    cleaned = value.strip().strip("\"'`\\")
    cleaned = re.sub(r"\\+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


class WordPressMetricsClient:
    def __init__(self, endpoint: str, username: str, application_password: str) -> None:
        self.endpoint = endpoint.rstrip("?")
        self.auth_header = "Basic " + build_basic_auth_token(username, application_password)

    def fetch_page(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{self.endpoint}?{query}" if query else self.endpoint
        request = Request(
            url,
            headers={
                "Authorization": self.auth_header,
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise WordPressMetricsError(f"WordPress metrics endpoint returned HTTP {exc.code}: {body[:500]}") from exc
        except URLError as exc:
            raise WordPressMetricsError(f"WordPress metrics endpoint connection failed: {exc}") from exc

    def fetch_all_posts(
        self,
        *,
        post_type: str,
        status: str,
        per_page: int,
        days: int,
        include_content: bool = False,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        page = 1
        total_pages = 1
        last_payload: dict[str, Any] = {}

        while page <= total_pages:
            payload = self.fetch_page(
                {
                    "post_type": post_type,
                    "status": status,
                    "per_page": per_page,
                    "page": page,
                    "days": days,
                    "include_content": "true" if include_content else "false",
                }
            )
            last_payload = payload
            items.extend(payload.get("items", []))
            pagination = payload.get("pagination", {}) if isinstance(payload.get("pagination"), dict) else {}
            total_pages = int(pagination.get("total_pages") or 1)
            page += 1

        return {
            "source": last_payload.get("source", {}),
            "pagination": {
                "total_pages": total_pages,
                "fetched_items": len(items),
            },
            "items": items,
        }
