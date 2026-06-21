from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .paths import GENERATED_DIR


MANIFEST_PATH = GENERATED_DIR / "wordpress-payloads" / "post_payloads_latest.json"


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_manifest_digest() -> str:
    return file_sha256(MANIFEST_PATH)


def manifest_fingerprint() -> dict[str, Any]:
    return {
        "manifest_path": "03_generated/wordpress-payloads/post_payloads_latest.json",
        "manifest_sha256": current_manifest_digest(),
    }


def payload_matches_current_manifest(payload: dict[str, Any]) -> bool:
    digest = current_manifest_digest()
    if not digest:
        return False
    if payload.get("manifest_sha256") == digest:
        return True
    fingerprint = payload.get("manifest_fingerprint")
    return isinstance(fingerprint, dict) and fingerprint.get("manifest_sha256") == digest
