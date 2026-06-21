#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import LOGS_DIR  # noqa: E402
from ksrfp_jinjiroumu_blog.wordpress_client import (  # noqa: E402
    read_wordpress_credentials,
    update_media_alt_text,
)


def main() -> int:
    payload: dict[str, Any] = {
        "status": "not_started",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "items": [],
    }
    try:
        if os.environ.get("KSRFP_ALLOW_WORDPRESS_WRITE") != "1":
            raise RuntimeError("Write guard is active. Set KSRFP_ALLOW_WORDPRESS_WRITE=1 to execute.")
        settings = read_json(PROJECT_ROOT / "config" / "project_settings.json", {}) or {}
        refresh = read_json(LOGS_DIR / "wordpress_featured_image_refresh_latest.json", {}) or {}
        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            raise RuntimeError("WordPress credentials are not ready.")
        api_base = str(settings.get("wordpress_api_base", "")).rstrip("/")
        items = refresh.get("items", []) if isinstance(refresh.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_index = int(item.get("item_index") or 0)
            media_id = int(item.get("media", {}).get("id") or 0) if isinstance(item.get("media"), dict) else 0
            plan = read_json(PROJECT_ROOT / "03_generated" / "images" / f"featured_image_plan_item_{item_index}.json", {}) or {}
            alt_text = str(plan.get("alt_text") or "")
            if media_id and alt_text:
                update_media_alt_text(
                    api_base,
                    str(credentials["username"]),
                    str(credentials["application_password"]),
                    media_id,
                    alt_text,
                )
                payload["items"].append(
                    {
                        "item_index": item_index,
                        "media_id": media_id,
                        "alt_text": alt_text,
                    }
                )
        payload["status"] = "ok"
        return_code = 0
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()
        return_code = 1
    finally:
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(LOGS_DIR / "wordpress_featured_image_refresh_alt_update_latest.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
