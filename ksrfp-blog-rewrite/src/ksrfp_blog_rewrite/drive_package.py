from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def prepare_drive_files(
    *,
    article: dict[str, Any],
    brief: dict[str, Any],
    image_plan: dict[str, Any],
    source_image_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    title = str(article.get("title") or image_plan.get("title") or "rewrite_article")
    file_base = str(image_plan.get("file_base") or title)
    text_path = output_dir / f"{file_base}.txt"
    image_path = output_dir / f"{file_base}.png"

    output_dir.mkdir(parents=True, exist_ok=True)
    text_path.write_text(render_rewrite_text_file(article=article, brief=brief), encoding="utf-8")
    shutil.copy2(source_image_path, image_path)

    source = brief.get("source", {}) if isinstance(brief.get("source"), dict) else {}
    return {
        "status": "ok",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "template": "past_article_rewrite_text_v1",
        "file_base": file_base,
        "title": title,
        "source": {
            "post_id": source.get("post_id") or article.get("source_post_id"),
            "title": source.get("title"),
            "url": source.get("url"),
            "published_date": source.get("published_date"),
        },
        "text_file": {
            "path": str(text_path),
            "name": text_path.name,
            "size_bytes": text_path.stat().st_size,
        },
        "image_file": {
            "path": str(image_path),
            "name": image_path.name,
            "size_bytes": image_path.stat().st_size,
        },
        "same_file_base": text_path.stem == image_path.stem,
    }


def render_rewrite_text_file(*, article: dict[str, Any], brief: dict[str, Any]) -> str:
    source = brief.get("source", {}) if isinstance(brief.get("source"), dict) else {}
    title = str(article.get("title") or "").strip()
    body_markdown = strip_leading_h1(str(article.get("body_markdown") or ""), title)

    lines = [
        "＜リライト対象記事＞",
        "",
        f"タイトル；{source.get('title') or ''}",
        f"URL：{source.get('url') or ''}",
        f"投稿ID：{source.get('post_id') or article.get('source_post_id') or ''}",
        f"公開日：{format_japanese_datetime(source.get('published_date'))}",
        "",
        "ーーーーーーーーーー",
        "＜記事タイトル＞",
        "",
        title,
        "",
        "ーーーーーーーーーー",
        "＜記事本文＞",
        "",
        body_markdown,
    ]
    return "\n".join(lines).rstrip() + "\n"


def strip_leading_h1(markdown: str, title: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].startswith("# "):
        heading = lines[0][2:].strip()
        if not title or heading == title:
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
    return "\n".join(lines).strip()


def format_japanese_datetime(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text

    ampm = "AM" if parsed.hour < 12 else "PM"
    hour = parsed.hour % 12 or 12
    return f"{parsed.year}年{parsed.month}月{parsed.day}日 {hour}:{parsed.minute:02d} {ampm}"
