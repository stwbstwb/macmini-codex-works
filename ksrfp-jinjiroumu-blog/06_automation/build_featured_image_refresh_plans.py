#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.image_gate import featured_image_gate_reasons  # noqa: E402
from ksrfp_jinjiroumu_blog.image_plan import (  # noqa: E402
    apply_title_overlay,
    build_alt_text,
    build_prompt,
    image_scene_profile,
    image_slug,
    image_title,
)
from ksrfp_jinjiroumu_blog.io_utils import read_json, write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import GENERATED_DIR, LOGS_DIR  # noqa: E402


MANIFEST_PATH = GENERATED_DIR / "images" / "featured_image_refresh_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build strict featured-image plans from freshly generated photo sources.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    manifest = read_json(manifest_path, {}) or {}
    payload = build_plans(manifest, manifest_path)
    status = payload.get("status")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


def build_plans(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    requested_at = str(manifest.get("requested_at") or "")
    items = manifest.get("items", []) if isinstance(manifest.get("items"), list) else []
    results: list[dict[str, Any]] = []
    duplicate_sources: list[dict[str, Any]] = []
    seen_sources: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        result = build_item_plan(item, requested_at)
        results.append(result)
        digest = result.get("source_digest")
        if result.get("status") == "ok" and digest:
            if digest in seen_sources:
                duplicate_sources.append(
                    {
                        "source_digest": digest,
                        "first": seen_sources[digest],
                        "duplicate": {
                            "item_index": result.get("item_index"),
                            "post_id": result.get("post_id"),
                            "source_path": result.get("source_path"),
                        },
                    }
                )
            else:
                seen_sources[digest] = {
                    "item_index": result.get("item_index"),
                    "post_id": result.get("post_id"),
                    "source_path": result.get("source_path"),
                }

    if duplicate_sources:
        for result in results:
            if result.get("source_digest") in {item.get("source_digest") for item in duplicate_sources}:
                result["status"] = "blocked_duplicate_source"
                result["blocked_reasons"] = ["同一バッチ内で写真ソースが重複しています。"]

    payload = {
        "status": "ok" if results and all(item.get("status") == "ok" for item in results) else "blocked",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_path": relative(manifest_path),
        "requested_at": requested_at,
        "item_count": len(results),
        "duplicate_sources": duplicate_sources,
        "items": results,
    }
    write_json(LOGS_DIR / "featured_image_refresh_plan_latest.json", payload)
    write_json(LOGS_DIR / f"featured-image-refresh-plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json", payload)
    write_markdown(GENERATED_DIR / "images" / "featured_image_refresh_plan_latest.md", render_report(payload))
    return payload


def build_item_plan(item: dict[str, Any], requested_at: str) -> dict[str, Any]:
    item_index = int(item.get("item_index") or 0)
    post_id = int(item.get("post_id") or 0)
    article_title = str(item.get("article_title") or "")
    selected = {
        "topic_title": str(item.get("topic_title") or ""),
        "section_group": str(item.get("section_group") or ""),
        "labels": str(item.get("labels") or ""),
        "excerpt": str(item.get("excerpt") or ""),
        "pdf_name": str(item.get("pdf_name") or ""),
    }
    topic = selected["topic_title"]
    slug = str(item.get("slug") or image_slug(topic, selected["labels"]))
    slug = f"refresh-{item_index}-{slug}"
    width = int(item.get("width") or 1200)
    height = int(item.get("height") or 630)
    source_path = PROJECT_ROOT / str(item.get("source_path") or f"03_generated/images/{slug}-featured-photo-source.png")
    output_path = PROJECT_ROOT / f"03_generated/images/{slug}-featured.png"
    plan_path = GENERATED_DIR / "images" / f"featured_image_plan_item_{item_index}.json"
    source_modified_at = None
    source_digest = ""
    source_fresh = False
    blocked_reasons: list[str] = []

    if source_path.exists() and source_path.is_file():
        source_modified_at = datetime.fromtimestamp(source_path.stat().st_mtime).isoformat(timespec="seconds")
        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        source_fresh = is_fresh(source_path, requested_at)
    else:
        blocked_reasons.append("新規生成された写真ソースが存在しません。")

    if source_path.exists() and not source_fresh:
        blocked_reasons.append("写真ソースが記事ブリーフ作成後に生成されたものではありません。")

    if not blocked_reasons:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(source_path.read_bytes())
        overlay = apply_title_overlay(output_path, article_title, default_overlay_settings(), width, height)
        file_exists = output_path.exists() and output_path.is_file() and output_path.stat().st_size > 0
        base_image = {
            "status": "photo_source_copied",
            "path": relative(output_path),
            "source_path": relative(source_path),
            "photo_source_exists": True,
            "photo_source_fresh": True,
            "new_image_required": True,
            "source_modified_at": source_modified_at,
            "required_new_after": requested_at,
            "quality_gate": "fresh_article_photo_source_verified",
            "source_match": "fresh_article_source",
        }
        plan = {
            "status": "ok",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "post_id": post_id,
            "item_index": item_index,
            "topic_title": topic,
            "article_title": article_title,
            "labels": selected["labels"],
            "width": width,
            "height": height,
            "file_name": output_path.name,
            "alt_text": build_alt_text(topic, selected["labels"], article_title),
            "scene_profile": image_scene_profile(selected, article_title),
            "prompt": build_prompt(selected, article_title, image_title(topic), "清潔感のあるビジネス向け。", width, height),
            "output_path": relative(output_path),
            "file_exists": file_exists,
            "file_size": output_path.stat().st_size if file_exists else 0,
            "title_overlay": overlay,
            "base_image": base_image,
            "photorealistic_required": True,
            "new_image_required": True,
            "code_generated_placeholder_allowed": False,
            "wordpress_ready": True,
        }
        gate_reasons = featured_image_gate_reasons(plan, image_exists=file_exists)
        if gate_reasons:
            blocked_reasons.extend(gate_reasons)
            plan["status"] = "blocked"
            plan["wordpress_ready"] = False
        write_json(plan_path, plan)
        write_markdown(plan_path.with_suffix(".md"), render_plan_markdown(plan))
    else:
        plan = {
            "status": "blocked",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "post_id": post_id,
            "item_index": item_index,
            "topic_title": topic,
            "article_title": article_title,
            "source_path": relative(source_path),
            "blocked_reasons": blocked_reasons,
            "wordpress_ready": False,
        }
        write_json(plan_path, plan)
        write_markdown(plan_path.with_suffix(".md"), render_plan_markdown(plan))

    return {
        "status": "ok" if not blocked_reasons else "blocked",
        "item_index": item_index,
        "post_id": post_id,
        "article_title": article_title,
        "topic_title": topic,
        "scene_type": image_scene_profile(selected, article_title).get("scene_type"),
        "source_path": relative(source_path),
        "output_path": plan.get("output_path"),
        "plan_path": relative(plan_path),
        "source_modified_at": source_modified_at,
        "source_fresh": source_fresh,
        "source_digest": source_digest,
        "blocked_reasons": blocked_reasons,
    }


def is_fresh(path: Path, requested_at: str) -> bool:
    try:
        required = datetime.fromisoformat(requested_at)
    except ValueError:
        return False
    return datetime.fromtimestamp(path.stat().st_mtime) >= required


def default_overlay_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "layout": "centered_blue_title_bands",
        "blue": "#0057B8",
        "text_color": "#FFFFFF",
        "preferred_lines": 2,
        "max_lines": 3,
        "max_width_ratio": 0.86,
        "font_size": 68,
        "min_font_size": 34,
        "padding_x": 24,
        "padding_y": 12,
        "line_gap": 8,
        "radius": 10,
        "shadow": True,
    }


def render_plan_markdown(plan: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# アイキャッチ差し替え計画",
            "",
            f"- ステータス: {plan.get('status')}",
            f"- 投稿ID: {plan.get('post_id')}",
            f"- 記事タイトル: {plan.get('article_title')}",
            f"- テーマ: {plan.get('topic_title')}",
            f"- シーン: {plan.get('scene_profile', {}).get('scene_type') if isinstance(plan.get('scene_profile'), dict) else ''}",
            f"- 画像: {plan.get('output_path')}",
            f"- WordPress準備: {plan.get('wordpress_ready')}",
        ]
    )


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# 6件アイキャッチ差し替え計画",
        "",
        f"- ステータス: {payload.get('status')}",
        f"- 対象件数: {payload.get('item_count')}",
        f"- リクエスト時刻: {payload.get('requested_at')}",
        "",
    ]
    for item in payload.get("items", []):
        lines.extend(
            [
                f"## {item.get('item_index')}件目",
                "",
                f"- 投稿ID: {item.get('post_id')}",
                f"- 記事タイトル: {item.get('article_title')}",
                f"- シーン: {item.get('scene_type')}",
                f"- 写真ソース新規: {item.get('source_fresh')}",
                f"- ステータス: {item.get('status')}",
                "",
            ]
        )
    return "\n".join(lines)


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
