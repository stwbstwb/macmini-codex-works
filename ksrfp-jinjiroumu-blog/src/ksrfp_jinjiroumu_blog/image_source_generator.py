from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .paths import CONFIG_DIR, GENERATED_DIR, LOGS_DIR, PROJECT_ROOT


def image_generation_settings() -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    image_generation = settings.get("image_generation", {})
    if not isinstance(image_generation, dict):
        image_generation = {}
    return {
        "provider": image_generation.get("provider") or "codex_image_tool_handoff",
        "model": image_generation.get("model") or "chatgpt_max_plan_imagegen",
        "request_size": image_generation.get("request_size") or "1536x1024",
        "quality": image_generation.get("quality") or "high",
        "output_format": image_generation.get("output_format") or "png",
    }


def image_generation_preflight() -> dict[str, Any]:
    settings = image_generation_settings()
    return {
        "ok": False,
        "checked": True,
        "provider": settings["provider"],
        "model": settings["model"],
        "handoff_required": True,
        "reason": "画像生成はCodex画像生成ツールへ引き継ぐ運用です。追加課金を要する画像生成手段は使いません。",
    }


def ensure_fresh_image_source_from_plan(
    image_plan: dict[str, Any],
    item_index: int | None = None,
    run_key: str | None = None,
) -> dict[str, Any]:
    """Generate the required fresh photorealistic source for a blocked image plan."""
    settings = image_generation_settings()
    started_at = datetime.now().isoformat(timespec="seconds")
    source_path = expected_source_path(image_plan)
    width = int(image_plan.get("width") or 1200)
    height = int(image_plan.get("height") or 630)
    prompt = str(image_plan.get("prompt") or "").strip()

    if not source_path:
        return write_generation_log(
            {
                "status": "blocked",
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "item_index": item_index,
                "reason": "image plan does not include a photo source path",
            },
            run_key,
        )
    if not prompt:
        return write_generation_log(
            {
                "status": "blocked",
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "item_index": item_index,
                "source_path": relative(source_path),
                "reason": "image plan prompt is empty",
            },
            run_key,
        )

    return write_generation_log(
        {
            "status": "blocked_auth_required",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "item_index": item_index,
            "provider": settings["provider"],
            "model": settings["model"],
            "source_path": relative(source_path),
            "expected_width": width,
            "expected_height": height,
            "reason": "画像生成はCodex画像生成ツールへ引き継ぐ運用です。追加課金を要する画像生成手段は使いません。",
        },
        run_key,
    )


def expected_source_path(image_plan: dict[str, Any]) -> Path | None:
    base_image = image_plan.get("base_image", {}) if isinstance(image_plan.get("base_image"), dict) else {}
    source = base_image.get("source_path") or image_plan.get("source_path")
    if not source and image_plan.get("output_path"):
        output = PROJECT_ROOT / str(image_plan["output_path"])
        source = str(output.with_name(output.stem + "-photo-source" + output.suffix).relative_to(PROJECT_ROOT))
    if not source:
        return None
    return PROJECT_ROOT / str(source)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_generation_log(payload: dict[str, Any], run_key: str | None = None) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(LOGS_DIR / "image_source_generation_latest.json", payload)
    write_json(LOGS_DIR / f"image-source-generation-{timestamp}.json", payload)
    if run_key:
        safe = "".join(char if char.isalnum() else "-" for char in run_key).strip("-") or timestamp
        write_json(LOGS_DIR / "runs" / safe / f"image_source_generation_item_{payload.get('item_index') or 'latest'}.json", payload)
    return payload


def relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
