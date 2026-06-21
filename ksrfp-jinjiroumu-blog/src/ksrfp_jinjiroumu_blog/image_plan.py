from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .image_gate import featured_image_gate_passed
from .io_utils import read_json, read_text, write_json, write_markdown
from .paths import CONFIG_DIR, GENERATED_DIR


LINE_START_FORBIDDEN = set("、。，．・：；？！?!)）】」』〉》〕］｝")
LINE_END_FORBIDDEN = set("（【「『〈《〔［｛(")


def build_featured_image_plan() -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    brief = read_json(GENERATED_DIR / "outlines" / "article_brief_latest.json", {}) or {}
    selected = brief.get("selected", {}) if isinstance(brief, dict) else {}
    item_index = brief.get("item_index") if isinstance(brief, dict) else None
    image_settings = settings.get("featured_image", {})
    topic = selected.get("topic_title", "")
    labels = selected.get("labels", "")
    title = image_title(topic)
    slug = image_slug(topic, labels)
    if item_index:
        slug = f"{slug}-item-{item_index}"
    width = int(image_settings.get("width") or 1200)
    height = int(image_settings.get("height") or 630)
    style = image_settings.get("style") or "清潔感のあるビジネス向け。"
    output_path = GENERATED_DIR / "images" / f"{slug}-featured.png"
    title_overlay = image_settings.get("title_overlay", {}) if isinstance(image_settings, dict) else {}
    article_title = extract_article_title() or selected.get("article_title") or topic
    base_result = ensure_base_image(output_path, width, height, topic, title, brief)
    overlay_result = apply_title_overlay(output_path, str(article_title), title_overlay, width, height)
    file_exists = output_path.exists() and output_path.is_file() and output_path.stat().st_size > 0
    wordpress_ready = file_exists and featured_image_gate_passed(
        {
            "file_exists": file_exists,
            "wordpress_ready": file_exists,
            "base_image": base_result,
            "photorealistic_required": True,
        }
    )

    plan = {
        "status": image_plan_status(topic, file_exists, base_result),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "topic_title": topic,
        "article_title": article_title,
        "labels": labels,
        "width": width,
        "height": height,
        "file_name": f"{slug}-featured.png",
        "alt_text": build_alt_text(topic, labels, str(article_title)),
        "scene_profile": image_scene_profile(selected, article_title),
        "prompt": build_prompt(selected, article_title, title, style, width, height),
        "output_path": f"03_generated/images/{slug}-featured.png",
        "file_exists": file_exists,
        "file_size": output_path.stat().st_size if file_exists else 0,
        "title_overlay": overlay_result,
        "base_image": base_result,
        "photorealistic_required": True,
        "code_generated_placeholder_allowed": False,
        "new_image_required": True,
        "wordpress_ready": wordpress_ready,
        "next_action": (
            "WordPressメディアアップロードへ渡す。"
            if wordpress_ready
            else "記事ごとに新規生成した写真背景ソースを作成し、再度タイトル合成してからWordPressへ渡す。既存画像・過去画像・同テーマ画像の再利用は不可。"
        ),
    }
    write_json(GENERATED_DIR / "images" / "featured_image_plan_latest.json", plan)
    write_markdown(GENERATED_DIR / "images" / "featured_image_plan_latest.md", render_image_plan(plan))
    return plan


def extract_article_title() -> str:
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    if not article_path.exists():
        return ""
    match = re.search(r"^#\s+(.+)$", read_text(article_path), flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def ensure_base_image(output_path: Path, width: int, height: int, topic: str, title: str, brief: dict[str, Any]) -> dict[str, Any]:
    photo_source_path = output_path.with_name(output_path.stem + "-photo-source" + output_path.suffix)
    required_new_after = brief_generated_at(brief)
    if photo_source_path.exists():
        fresh = is_source_fresh(photo_source_path, required_new_after)
        if not fresh:
            return {
                "status": "stale_photo_source_rejected",
                "path": f"03_generated/images/{output_path.name}",
                "source_path": f"03_generated/images/{photo_source_path.name}",
                "photo_source_exists": True,
                "photo_source_fresh": False,
                "new_image_required": True,
                "source_modified_at": datetime.fromtimestamp(photo_source_path.stat().st_mtime).isoformat(timespec="seconds"),
                "required_new_after": required_new_after,
                "quality_gate": "fresh_article_photo_source_required",
                "note": "記事ごとに新規生成した写真背景ソースが必須です。過去画像・既存画像・同テーマ画像の再利用は不可です。",
            }
        shutil.copy2(photo_source_path, output_path)
        return {
            "status": "photo_source_copied",
            "path": f"03_generated/images/{output_path.name}",
            "source_path": f"03_generated/images/{photo_source_path.name}",
            "photo_source_exists": True,
            "photo_source_fresh": True,
            "new_image_required": True,
            "source_modified_at": datetime.fromtimestamp(photo_source_path.stat().st_mtime).isoformat(timespec="seconds"),
            "required_new_after": required_new_after,
            "quality_gate": "fresh_article_photo_source_verified",
            "source_match": "fresh_article_source",
        }
    if output_path.exists():
        return {
            "status": "existing_image_rejected",
            "path": f"03_generated/images/{output_path.name}",
            "source_path": f"03_generated/images/{photo_source_path.name}",
            "photo_source_exists": False,
            "photo_source_fresh": False,
            "new_image_required": True,
            "required_new_after": required_new_after,
            "quality_gate": "existing_image_reuse_blocked",
            "note": "生成済みアイキャッチ画像の再利用は不可です。記事ごとに新規写真背景ソースを生成してください。",
        }

    return {
        "status": "requires_fresh_photorealistic_source",
        "path": f"03_generated/images/{output_path.name}",
        "source_path": f"03_generated/images/{photo_source_path.name}",
        "photo_source_exists": False,
        "photo_source_fresh": False,
        "new_image_required": True,
        "required_new_after": required_new_after,
        "quality_gate": "blocked_until_fresh_article_photo_source_ready",
        "note": "記事テーマと本文内容に合う写真品質の背景画像を、毎記事ごとに新規生成してください。既存画像・過去画像・同テーマ画像の再利用は不可です。",
    }


def brief_generated_at(brief: dict[str, Any]) -> str | None:
    value = brief.get("generated_at") if isinstance(brief, dict) else None
    return str(value) if value else None


def is_source_fresh(path: Path, required_new_after: str | None) -> bool:
    if not required_new_after:
        return False
    try:
        required = datetime.fromisoformat(required_new_after)
    except ValueError:
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    return modified >= required


def image_plan_status(topic: str, file_exists: bool, base_result: dict[str, Any]) -> str:
    if not topic:
        return "no_topic"
    if featured_image_gate_passed(
        {
            "file_exists": file_exists,
            "wordpress_ready": file_exists,
            "base_image": base_result,
            "photorealistic_required": True,
        }
    ):
        return "ok"
    if base_result.get("status") == "requires_photorealistic_source":
        return "requires_photorealistic_source"
    if base_result.get("status") == "requires_fresh_photorealistic_source":
        return "requires_fresh_photorealistic_source"
    return "blocked"


def generate_thematic_background(width: int, height: int, topic: str, title: str) -> Image.Image:
    palette = topic_palette(topic, title)
    image = Image.new("RGB", (width, height), palette["wall"])
    draw = ImageDraw.Draw(image, "RGBA")

    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = blend_hex(palette["wall"], palette["wall_bottom"], ratio)
        draw.line([(0, y), (width, y)], fill=color)

    draw.rectangle([0, int(height * 0.57), width, height], fill=hex_to_rgba(palette["desk"], 238))
    draw.rectangle([0, int(height * 0.57), width, int(height * 0.59)], fill=(255, 255, 255, 70))
    draw.rounded_rectangle(
        [int(width * 0.05), int(height * 0.08), int(width * 0.42), int(height * 0.50)],
        radius=18,
        fill=(255, 255, 255, 82),
        outline=(255, 255, 255, 120),
        width=2,
    )
    for x in [0.14, 0.25, 0.36]:
        draw.line(
            [(int(width * x), int(height * 0.09)), (int(width * x), int(height * 0.49))],
            fill=(255, 255, 255, 80),
            width=2,
        )

    if "メンタルヘルス" in topic or "ストレスチェック" in topic:
        draw_mental_health_scene(draw, width, height, palette)
    elif "助成金" in topic or "奨励金" in topic or "リスキリング" in topic:
        draw_subsidy_scene(draw, width, height, palette)
    elif "パート" in topic or "有期" in topic or "正社員" in topic:
        draw_employment_scene(draw, width, height, palette)
    elif "労働時間" in topic or "働き方改革" in topic:
        draw_working_hours_scene(draw, width, height, palette)
    elif "高年齢者" in topic or "労働災害" in topic or "安全衛生" in topic:
        draw_safety_scene(draw, width, height, palette)
    elif "社宅" in topic or "現物給与" in topic or "給与計算" in topic:
        draw_payroll_housing_scene(draw, width, height, palette)
    else:
        draw_general_labor_scene(draw, width, height, palette)

    return image


def topic_palette(topic: str, title: str) -> dict[str, str]:
    text = f"{topic} {title}"
    if "メンタルヘルス" in text or "ストレスチェック" in text:
        return {"wall": "#dbece8", "wall_bottom": "#f3f7f3", "desk": "#d2ded8", "accent": "#1f8a83", "accent2": "#7aa874"}
    if "助成金" in text or "奨励金" in text or "リスキリング" in text:
        return {"wall": "#dce8f2", "wall_bottom": "#f5f7fb", "desk": "#d7dde6", "accent": "#1f6fb2", "accent2": "#2c9f74"}
    if "パート" in text or "有期" in text or "正社員" in text:
        return {"wall": "#e7e2da", "wall_bottom": "#f8f5ee", "desk": "#ddd3c7", "accent": "#245d8f", "accent2": "#b8782b"}
    if "労働時間" in text or "働き方改革" in text:
        return {"wall": "#dde7ee", "wall_bottom": "#f7f8f9", "desk": "#d8dde0", "accent": "#315f8f", "accent2": "#6a8fb3"}
    if "高年齢者" in text or "労働災害" in text or "安全衛生" in text:
        return {"wall": "#e8ece1", "wall_bottom": "#faf8ef", "desk": "#ddd8c7", "accent": "#6f7f27", "accent2": "#d2a32a"}
    if "社宅" in text or "現物給与" in text or "給与計算" in text:
        return {"wall": "#e3e8ef", "wall_bottom": "#f8f7f2", "desk": "#d5dbe3", "accent": "#274b78", "accent2": "#9a7a42"}
    return {"wall": "#dde8e6", "wall_bottom": "#f7f8f6", "desk": "#d8dedc", "accent": "#265d9b", "accent2": "#748c69"}


def draw_laptop(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, accent: str) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=(42, 50, 58, 235))
    draw.rounded_rectangle([x + 14, y + 14, x + w - 14, y + h - 16], radius=8, fill=hex_to_rgba(accent, 150))
    draw.rectangle([x - 28, y + h, x + w + 42, y + h + 20], fill=(54, 58, 64, 220))
    draw.rectangle([x + int(w * 0.35), y + h + 5, x + int(w * 0.65), y + h + 9], fill=(255, 255, 255, 82))


def draw_document_stack(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, accent: str) -> None:
    for offset, alpha in [(18, 160), (9, 190), (0, 235)]:
        draw.rounded_rectangle([x + offset, y - offset, x + w + offset, y + h - offset], radius=10, fill=(255, 255, 255, alpha))
    for i in range(5):
        yy = y + 28 + i * 24
        draw.rounded_rectangle([x + 34, yy, x + w - 28, yy + 8], radius=4, fill=hex_to_rgba(accent, 80))
    draw.ellipse([x + w - 76, y + 34, x + w - 42, y + 68], fill=hex_to_rgba(accent, 150))


def draw_checklist(draw: ImageDraw.ImageDraw, x: int, y: int, rows: int, accent: str) -> None:
    for i in range(rows):
        yy = y + i * 34
        draw.rounded_rectangle([x, yy, x + 22, yy + 22], radius=5, outline=hex_to_rgba(accent, 170), width=3)
        draw.line([(x + 5, yy + 12), (x + 10, yy + 17), (x + 18, yy + 6)], fill=hex_to_rgba(accent, 190), width=3)
        draw.rounded_rectangle([x + 36, yy + 5, x + 190, yy + 14], radius=5, fill=(255, 255, 255, 110))


def draw_subsidy_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    draw_laptop(draw, int(width * 0.10), int(height * 0.36), int(width * 0.29), int(height * 0.22), palette["accent"])
    draw_document_stack(draw, int(width * 0.66), int(height * 0.25), int(width * 0.22), int(height * 0.32), palette["accent2"])
    draw_checklist(draw, int(width * 0.69), int(height * 0.33), 4, palette["accent2"])
    draw.rounded_rectangle([int(width * 0.44), int(height * 0.18), int(width * 0.62), int(height * 0.38)], radius=18, fill=hex_to_rgba(palette["accent2"], 105))
    draw.arc([int(width * 0.46), int(height * 0.21), int(width * 0.59), int(height * 0.34)], start=25, end=325, fill=(255, 255, 255, 170), width=8)


def draw_mental_health_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    draw_document_stack(draw, int(width * 0.12), int(height * 0.25), int(width * 0.26), int(height * 0.32), palette["accent"])
    draw_checklist(draw, int(width * 0.16), int(height * 0.34), 3, palette["accent"])
    pot = [int(width * 0.70), int(height * 0.43), int(width * 0.80), int(height * 0.60)]
    draw.rounded_rectangle(pot, radius=12, fill=hex_to_rgba(palette["accent2"], 180))
    stem_x = int(width * 0.75)
    draw.line([(stem_x, int(height * 0.43)), (stem_x, int(height * 0.24))], fill=hex_to_rgba(palette["accent2"], 210), width=8)
    for dx, dy in [(-80, -95), (-42, -135), (44, -128), (80, -88)]:
        draw.ellipse([stem_x + dx, int(height * 0.42) + dy, stem_x + dx + 92, int(height * 0.42) + dy + 58], fill=hex_to_rgba(palette["accent2"], 135))
    draw.rounded_rectangle([int(width * 0.49), int(height * 0.24), int(width * 0.60), int(height * 0.38)], radius=18, fill=hex_to_rgba(palette["accent"], 100))


def draw_employment_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    draw_document_stack(draw, int(width * 0.55), int(height * 0.25), int(width * 0.27), int(height * 0.33), palette["accent"])
    draw_laptop(draw, int(width * 0.10), int(height * 0.38), int(width * 0.27), int(height * 0.20), palette["accent"])
    draw.rounded_rectangle([int(width * 0.40), int(height * 0.40), int(width * 0.58), int(height * 0.50)], radius=24, fill=(194, 132, 76, 135))
    draw.rounded_rectangle([int(width * 0.51), int(height * 0.37), int(width * 0.69), int(height * 0.47)], radius=24, fill=(145, 104, 74, 125))
    draw.rounded_rectangle([int(width * 0.64), int(height * 0.20), int(width * 0.78), int(height * 0.30)], radius=12, outline=hex_to_rgba(palette["accent2"], 170), width=4)


def draw_working_hours_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    draw_laptop(draw, int(width * 0.56), int(height * 0.34), int(width * 0.30), int(height * 0.22), palette["accent"])
    clock = [int(width * 0.15), int(height * 0.18), int(width * 0.35), int(height * 0.56)]
    draw.ellipse(clock, fill=(255, 255, 255, 180), outline=hex_to_rgba(palette["accent"], 180), width=6)
    cx = int((clock[0] + clock[2]) / 2)
    cy = int((clock[1] + clock[3]) / 2)
    draw.line([(cx, cy), (cx, cy - 78)], fill=hex_to_rgba(palette["accent"], 220), width=6)
    draw.line([(cx, cy), (cx + 70, cy + 36)], fill=hex_to_rgba(palette["accent"], 220), width=6)
    draw_document_stack(draw, int(width * 0.39), int(height * 0.28), int(width * 0.18), int(height * 0.29), palette["accent2"])


def draw_safety_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    draw_document_stack(draw, int(width * 0.58), int(height * 0.23), int(width * 0.24), int(height * 0.34), palette["accent"])
    draw_checklist(draw, int(width * 0.63), int(height * 0.33), 4, palette["accent"])
    helmet = [int(width * 0.14), int(height * 0.33), int(width * 0.38), int(height * 0.56)]
    draw.pieslice(helmet, start=180, end=360, fill=hex_to_rgba(palette["accent2"], 230))
    draw.rectangle([helmet[0], int(height * 0.45), helmet[2], int(height * 0.53)], fill=hex_to_rgba(palette["accent2"], 230))
    draw.rounded_rectangle([helmet[0] - 20, int(height * 0.51), helmet[2] + 34, int(height * 0.57)], radius=16, fill=hex_to_rgba(palette["accent2"], 210))
    for x in [0.20, 0.26, 0.32]:
        draw.line([(int(width * x), int(height * 0.34)), (int(width * x), int(height * 0.51))], fill=(255, 255, 255, 95), width=5)
    draw.rounded_rectangle([int(width * 0.39), int(height * 0.29), int(width * 0.51), int(height * 0.53)], radius=12, fill=hex_to_rgba(palette["accent"], 115))
    draw.line([(int(width * 0.42), int(height * 0.47)), (int(width * 0.47), int(height * 0.37)), (int(width * 0.50), int(height * 0.43))], fill=(255, 255, 255, 190), width=7)


def draw_payroll_housing_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    house_x = int(width * 0.13)
    house_y = int(height * 0.31)
    house_w = int(width * 0.26)
    house_h = int(height * 0.22)
    draw.polygon(
        [
            (house_x - 20, house_y + 42),
            (house_x + house_w // 2, house_y - 48),
            (house_x + house_w + 20, house_y + 42),
        ],
        fill=hex_to_rgba(palette["accent2"], 210),
    )
    draw.rounded_rectangle([house_x, house_y + 30, house_x + house_w, house_y + house_h], radius=14, fill=(255, 255, 255, 195))
    draw.rounded_rectangle([house_x + 36, house_y + 92, house_x + 88, house_y + house_h], radius=8, fill=hex_to_rgba(palette["accent"], 135))
    draw.rounded_rectangle([house_x + 126, house_y + 70, house_x + 196, house_y + 118], radius=8, fill=hex_to_rgba(palette["accent"], 90))
    draw_document_stack(draw, int(width * 0.58), int(height * 0.23), int(width * 0.25), int(height * 0.34), palette["accent"])
    for i, w_ratio in enumerate([0.66, 0.76, 0.70, 0.80]):
        yy = int(height * (0.34 + i * 0.045))
        draw.rounded_rectangle([int(width * 0.63), yy, int(width * w_ratio), yy + 9], radius=5, fill=hex_to_rgba(palette["accent"], 115))
    draw.rounded_rectangle([int(width * 0.45), int(height * 0.41), int(width * 0.54), int(height * 0.52)], radius=16, fill=hex_to_rgba(palette["accent2"], 135))


def draw_general_labor_scene(draw: ImageDraw.ImageDraw, width: int, height: int, palette: dict[str, str]) -> None:
    draw_laptop(draw, int(width * 0.12), int(height * 0.36), int(width * 0.28), int(height * 0.22), palette["accent"])
    draw_document_stack(draw, int(width * 0.62), int(height * 0.25), int(width * 0.23), int(height * 0.33), palette["accent"])
    draw_checklist(draw, int(width * 0.66), int(height * 0.34), 4, palette["accent2"])


def hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.strip().lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


def blend_hex(start: str, end: str, ratio: float) -> tuple[int, int, int, int]:
    s = hex_to_rgba(start)
    e = hex_to_rgba(end)
    return tuple(int(s[i] + (e[i] - s[i]) * ratio) for i in range(3)) + (255,)


def apply_title_overlay(image_path: Path, title: str, overlay_settings: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    enabled = overlay_settings.get("enabled", True) if isinstance(overlay_settings, dict) else True
    if not enabled:
        return {"status": "skipped", "reason": "title overlay disabled"}
    if not image_path.exists():
        return {"status": "waiting_for_base_image", "reason": "base image does not exist yet"}
    if not title.strip():
        return {"status": "skipped", "reason": "title is empty"}

    base_path = image_path.with_name(image_path.stem + "-base" + image_path.suffix)
    # Keep the pre-overlay cache aligned with the current photo source.
    shutil.copy2(image_path, base_path)

    image = Image.open(base_path).convert("RGB")
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)

    settings = default_overlay_settings()
    if isinstance(overlay_settings, dict):
        settings.update({key: value for key, value in overlay_settings.items() if value is not None})
    rendered = render_centered_title_bands(image, title.strip(), settings)
    rendered.save(image_path, optimize=True)
    return {
        "status": "rendered",
        "style": "centered_blue_title_bands",
        "base_path": f"03_generated/images/{base_path.name}",
        "output_path": f"03_generated/images/{image_path.name}",
        "title": title.strip(),
        "line_count": int(rendered.info.get("title_line_count", 0) or 0),
    }


def default_overlay_settings() -> dict[str, Any]:
    return {
        "blue": "#0057B8",
        "text_color": "#FFFFFF",
        "max_width_ratio": 0.86,
        "preferred_lines": 2,
        "max_lines": 3,
        "font_size": 68,
        "min_font_size": 34,
        "line_gap": 8,
        "padding_x": 24,
        "padding_y": 12,
        "radius": 10,
        "shadow": True,
    }


def render_centered_title_bands(image: Image.Image, title: str, settings: dict[str, Any]) -> Image.Image:
    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    max_text_width = int(canvas.width * float(settings["max_width_ratio"])) - int(settings["padding_x"]) * 2
    font, lines = choose_font_and_lines(
        title,
        max_text_width=max_text_width,
        preferred_lines=int(settings["preferred_lines"]),
        max_lines=int(settings["max_lines"]),
        font_size=int(settings["font_size"]),
        min_font_size=int(settings["min_font_size"]),
    )
    metrics = [text_metrics(line, font) for line in lines]
    rects = [
        {
            "text": line,
            "text_width": metric["width"],
            "text_height": metric["height"],
            "offset_y": metric["offset_y"],
            "rect_width": metric["width"] + int(settings["padding_x"]) * 2,
            "rect_height": metric["height"] + int(settings["padding_y"]) * 2,
        }
        for line, metric in zip(lines, metrics)
    ]
    total_height = sum(rect["rect_height"] for rect in rects) + int(settings["line_gap"]) * (len(rects) - 1)
    y = int((canvas.height - total_height) / 2)
    band_color = color_to_rgba(str(settings["blue"]))
    text_color = color_to_rgba(str(settings["text_color"]))

    for rect in rects:
        x = int((canvas.width - rect["rect_width"]) / 2)
        box = [x, y, x + rect["rect_width"], y + rect["rect_height"]]
        if settings.get("shadow", True):
            shadow = [box[0] + 4, box[1] + 4, box[2] + 4, box[3] + 4]
            draw.rounded_rectangle(shadow, radius=int(settings["radius"]), fill=(0, 0, 0, 72))
        draw.rounded_rectangle(box, radius=int(settings["radius"]), fill=band_color)
        text_x = x + int(settings["padding_x"]) + int((rect["rect_width"] - rect["text_width"] - int(settings["padding_x"]) * 2) / 2)
        text_y = y + int(settings["padding_y"]) - int(rect["offset_y"])
        draw.text((text_x, text_y), rect["text"], font=font, fill=text_color)
        y += rect["rect_height"] + int(settings["line_gap"])

    output = canvas.convert("RGB")
    output.info["title_line_count"] = str(len(lines))
    return output


def choose_font_and_lines(
    title: str,
    max_text_width: int,
    preferred_lines: int,
    max_lines: int,
    font_size: int,
    min_font_size: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(font_size, min_font_size - 1, -2):
        font = load_japanese_bold_font(size)
        for lines in semantic_title_line_candidates(title, max_lines):
            if lines_fit(lines, font, max_text_width):
                return font, lines
        for line_count in unique_line_count_order(preferred_lines, 1, max_lines):
            lines = split_title_balanced(title, line_count, font, max_text_width)
            if lines:
                return font, lines
        lines = greedy_wrap(title, font, max_text_width, max_lines)
        if lines and len(lines) <= max_lines:
            return font, lines
    font = load_japanese_bold_font(min_font_size)
    return font, greedy_wrap(title, font, max_text_width, max_lines) or [title]


def semantic_title_line_candidates(title: str, max_lines: int) -> list[list[str]]:
    compact = title.replace(" ", "")
    candidates: list[list[str]] = []
    if "とは？" in compact:
        first, rest = compact.split("とは？", 1)
        first = f"{first}とは？"
        if rest:
            marker = "が確認したい"
            if marker in rest:
                left, right = rest.split(marker, 1)
                second = f"{left}{marker}"
                if right:
                    candidates.append([first, second, right])
                candidates.append([first, f"{second}{right}"])
            candidates.append([first, rest])
    return [lines for lines in candidates if 1 < len(lines) <= max_lines and valid_title_lines(lines)]


def lines_fit(lines: list[str], font: ImageFont.FreeTypeFont, max_text_width: int) -> bool:
    return valid_title_lines(lines) and all(measure_text_width(line, font) <= max_text_width for line in lines)


def unique_line_count_order(*values: int) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value > 0 and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def split_title_balanced(title: str, line_count: int, font: ImageFont.FreeTypeFont, max_text_width: int) -> list[str]:
    compact = title.replace(" ", "")
    if line_count <= 1:
        return [compact] if measure_text_width(compact, font) <= max_text_width else []
    if len(compact) < line_count * 4:
        return []

    best: tuple[float, list[str]] | None = None

    def search(start: int, parts: list[str]) -> None:
        nonlocal best
        remaining_parts = line_count - len(parts)
        if remaining_parts == 1:
            candidate = compact[start:]
            lines = parts + [candidate]
            widths = [measure_text_width(line, font) for line in lines]
            if not candidate or max(widths) > max_text_width or not valid_title_lines(lines):
                return
            score = (max(widths) - min(widths)) + sum(abs(len(line) - len(compact) / line_count) * 6 for line in lines)
            if best is None or score < best[0]:
                best = (score, lines)
            return
        min_end = start + 4
        max_end = len(compact) - (remaining_parts - 1) * 4
        for end in range(min_end, max_end + 1):
            line = compact[start:end]
            if not valid_title_lines(parts + [line]):
                continue
            if measure_text_width(line, font) > max_text_width:
                break
            search(end, parts + [line])

    search(0, [])
    return best[1] if best else []


def greedy_wrap(title: str, font: ImageFont.FreeTypeFont, max_text_width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    compact = title.replace(" ", "")
    for index, char in enumerate(compact):
        candidate = current + char
        if current and measure_text_width(candidate, font) > max_text_width:
            if len(lines) >= max_lines - 1:
                return []
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        return []
    if any(measure_text_width(line, font) > max_text_width for line in lines):
        return []
    if not valid_title_lines(lines):
        return []
    return lines


def valid_title_lines(lines: list[str]) -> bool:
    for line in lines:
        if not line:
            return False
        if line[0] in LINE_START_FORBIDDEN:
            return False
        if line[-1] in LINE_END_FORBIDDEN:
            return False
    return True


def load_japanese_bold_font(size: int) -> ImageFont.FreeTypeFont:
    for pattern in (
        "/System/Library/Fonts/*角*W8.ttc",
        "/System/Library/Fonts/*角*W7.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ):
        matches = sorted(Path("/").glob(pattern.lstrip("/")))
        if not matches:
            continue
        try:
            return ImageFont.truetype(str(matches[0]), size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def text_metrics(text: str, font: ImageFont.FreeTypeFont) -> dict[str, int]:
    bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
    return {
        "width": bbox[2] - bbox[0],
        "height": bbox[3] - bbox[1],
        "offset_y": bbox[1],
    }


def measure_text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    return text_metrics(text, font)["width"]


def color_to_rgba(value: str) -> tuple[int, int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 6:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255
    return 0, 87, 184, 255


def image_title(topic: str) -> str:
    if "65" in topic and "雇用推進助成金" in topic:
        return "高年齢者雇用管理"
    if "女性活躍推進法" in topic or "一般事業主行動計画" in topic:
        return "女性活躍推進"
    if "同一賃金ガイドライン" in topic or "同一労働同一賃金ガイドライン" in topic:
        return "待遇説明・賃金制度"
    if "子ども・子育て支援金" in topic:
        return "社会保険と給与計算"
    if "無期転換" in topic:
        return "契約更新管理"
    if "労働時間" in topic or "働き方改革" in topic:
        return "労働時間管理"
    if "パート" in topic or "有期" in topic:
        return "雇用管理"
    if "助成金" in topic:
        return "助成金活用"
    if "ストレスチェック" in topic or "メンタルヘルス" in topic:
        return "メンタルヘルス対策"
    if "ハラスメント" in topic or "カスハラ" in topic:
        return "ハラスメント対策"
    if "高年齢者" in topic or "労働災害" in topic or "安全衛生" in topic:
        return "安全衛生対策"
    if "社宅" in topic or "現物給与" in topic:
        return "社宅・給与計算"
    return "人事労務"


def image_slug(topic: str, labels: str) -> str:
    if "65" in topic and "雇用推進助成金" in topic:
        return "senior-employment-subsidy"
    if "女性活躍推進法" in topic or "一般事業主行動計画" in topic:
        return "women-action-plan"
    if "同一賃金ガイドライン" in topic or "同一労働同一賃金ガイドライン" in topic:
        return "equal-pay-guideline"
    if "子ども・子育て支援金" in topic:
        return "social-insurance"
    if "無期転換" in topic:
        return "fixed-term-conversion"
    if "労働時間" in topic or "働き方改革" in topic:
        return "working-hours"
    if "パート" in topic or "有期" in topic:
        return "part-time-employment"
    if "助成金" in topic or "subsidy" in labels:
        return "subsidy"
    if "ストレスチェック" in topic or "メンタルヘルス" in topic:
        return "mental-health"
    if "ハラスメント" in topic or "カスハラ" in topic:
        return "harassment"
    if "高年齢者" in topic or "労働災害" in topic or "安全衛生" in topic:
        return "occupational-safety"
    if "社宅" in topic or "現物給与" in topic:
        return "payroll-housing"
    normalized = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return normalized or "labor-management"


def build_alt_text(topic: str, labels: str = "", article_title: str = "") -> str:
    text = f"{topic} {labels} {article_title}"
    if "65" in text and "雇用推進助成金" in text:
        return "高年齢者雇用管理の評価面談と制度書類確認を表すビジネスイメージ"
    if "女性活躍推進法" in text or "一般事業主行動計画" in text:
        return "女性活躍推進法の行動計画と人事データ確認を表すビジネスイメージ"
    if "同一賃金ガイドライン" in text or "同一労働同一賃金ガイドライン" in text:
        return "待遇差の点検と賃金制度見直しを表すビジネスイメージ"
    if "子ども・子育て支援金" in text:
        return "社会保険料と給与計算の確認を表すビジネスイメージ"
    if "無期転換" in text:
        return "有期契約の更新管理と労働条件確認を表すビジネスイメージ"
    if "労働時間" in text or "働き方改革" in text:
        return "中小企業の労働時間管理と36協定の見直しを表すビジネスイメージ"
    if "トライアル雇用" in text:
        return "採用面談とトライアル雇用の実務確認を表すビジネスイメージ"
    if "人材開発支援助成金" in text or "リスキリング" in text or "研修" in text:
        return "社員研修とリスキリング支援の実務を表すビジネスイメージ"
    if "パート" in text or "有期" in text:
        return "パート・有期雇用の待遇説明と雇用管理を表すビジネスイメージ"
    if "高年齢者" in text or "労働災害" in text or "安全衛生" in text:
        return "高年齢者の労働災害防止と安全衛生対策を表すビジネスイメージ"
    if "社宅" in text or "現物給与" in text:
        return "社宅貸与と現物給与の給与計算確認を表すビジネスイメージ"
    return "中小企業の人事労務管理を表すビジネスイメージ"


def build_prompt(selected: dict[str, Any], article_title: str, short_theme: str, style: str, width: int, height: int) -> str:
    topic = str(selected.get("topic_title") or "")
    section = str(selected.get("section_group") or "")
    labels = str(selected.get("labels") or "")
    excerpt = str(selected.get("excerpt") or "")
    profile = image_scene_profile(selected, article_title)
    return "\n".join(
        [
            "Use case: photorealistic-natural",
            f"Asset type: {width}x{height} Japanese business blog featured-image background, no title text yet",
            (
                "Primary request: Generate a brand-new, article-specific photorealistic background image. "
                "Do not reuse any previous generated image, stock-looking generic office scene, or same-theme image from another article."
            ),
            f"Article title: {article_title}",
            f"Source topic: {topic}",
            f"Source section: {section}",
            f"Labels: {labels}",
            f"Short visual theme: {short_theme}",
            f"Article context summary: {compact_prompt_text(excerpt, 260)}",
            f"Scene type: {profile['scene_type']}",
            f"Scene/backdrop: {profile['backdrop']}",
            f"People: {profile['people']}",
            f"Main visual elements: {profile['elements']}",
            (
                "Composition: wide 1200:630 hero background, professional editorial photography, "
                "clear subject relevance, varied angle and environment chosen for this specific article, "
                "soft open center area for later blue title-band overlay, natural depth of field."
            ),
            (
                "Hard requirements: photorealistic only; no illustration, no vector, no infographic, no simple generated placeholder; "
                "no readable text, numbers, logos, brands, company names, watermarks, signs, or identifiable personal information in the background."
            ),
            (
                "Variation requirement: choose a materially different scene and composition from other articles in the same batch. "
                "Depending on the theme, use meetings, interviews, client consultation, payroll desk, factory/warehouse safety scene, "
                "business district/cityscape, or field-work setting instead of defaulting to the same office tabletop."
            ),
            "Overlay note: the article title will be added later as centered blue bands with white text; do not place title text in the image.",
            f"Design direction: {style}",
        ]
    )


def image_scene_profile(selected: dict[str, Any], article_title: str) -> dict[str, str]:
    text = " ".join(
        str(value)
        for value in [
            selected.get("topic_title"),
            selected.get("section_group"),
            selected.get("labels"),
            article_title,
            selected.get("excerpt"),
        ]
        if value
    )
    if "65" in text and "雇用推進助成金" in text:
        return {
            "scene_type": "高年齢者雇用管理・評価面談",
            "backdrop": "small HR consultation room where a senior employee and HR manager review blank role and evaluation documents, warm daylight, calm professional setting",
            "people": "two Japanese businesspeople, one senior employee and one HR manager, shown from side or hands only, non-identifiable faces",
            "elements": "blank evaluation sheets, role assignment folder, pen, laptop edge, calendar without readable dates, no logos or readable text",
        }
    if "女性活躍推進法" in text or "一般事業主行動計画" in text:
        return {
            "scene_type": "一般事業主行動計画・人事データ確認",
            "backdrop": "HR planning table with diverse managers reviewing blank workforce charts and action plan materials, bright meeting room, policy planning atmosphere",
            "people": "two or three Japanese businesspeople, mixed genders, seen from shoulders, hands, or back, non-identifiable faces",
            "elements": "blank charts, sticky notes without text, tablet, folders, neutral data printouts with no readable numbers or words",
        }
    if "同一賃金ガイドライン" in text or "同一労働同一賃金ガイドライン" in text:
        return {
            "scene_type": "待遇差点検・賃金制度見直し",
            "backdrop": "compensation review desk with HR staff comparing blank wage table documents and employment contract folders, focused professional lighting",
            "people": "two Japanese businesspeople's hands and partial side profiles, non-identifiable, discussing documents across a table",
            "elements": "blank wage table, employment contract folders, calculator, colored tabs without text, laptop with blurred screen and no readable content",
        }
    if any(key in text for key in ["子ども・子育て支援金", "社会保険", "給与計算", "保険料"]):
        return {
            "scene_type": "給与計算・社会保険料確認の実務デスク",
            "backdrop": "payroll or accounting desk with HR staff reviewing a laptop and calculator, clean office with soft natural light",
            "people": "one or two businesspeople's hands or side profiles, non-identifiable, focused on payroll review",
            "elements": "blank payroll-like sheets, calculator, laptop, calendar without readable dates, neutral files",
        }
    if any(key in text for key in ["無期転換", "契約更新", "有期労働契約", "労働条件"]):
        return {
            "scene_type": "契約更新・労働条件確認の面談",
            "backdrop": "small meeting room or consultation table where HR and employee review contract documents, bright but serious business atmosphere",
            "people": "two Japanese businesspeople seen from hands, shoulders, or side/back, no identifiable faces, one person pointing at blank contract pages",
            "elements": "blank contract documents, pen, folder, laptop edge, appointment calendar without readable text",
        }
    if any(key in text for key in ["トライアル雇用", "採用", "雇用助成金"]):
        return {
            "scene_type": "採用面談・人事担当者と応募者の打ち合わせ",
            "backdrop": "modern meeting room or HR interview space, recruiter and candidate seated across a table, calm daylight, businesslike but approachable",
            "people": "two or three Japanese businesspeople, side or back view, non-identifiable faces, natural meeting posture",
            "elements": "blank resume-like papers with no readable text, pen, tablet or laptop, folder, subtle office plants",
        }
    if any(key in text for key in ["人材開発支援助成金", "リスキリング", "研修", "訓練", "人への投資"]):
        return {
            "scene_type": "社員研修・リスキリング支援の実務",
            "backdrop": "small corporate training room or workshop scene, employees learning with laptops and a facilitator near a whiteboard with no readable writing",
            "people": "several Japanese businesspeople from side/back, non-identifiable, participating in training or skills workshop",
            "elements": "laptops, blank training handouts, notebook, pen, whiteboard without readable text, calm professional learning atmosphere",
        }
    if any(key in text for key in ["労働時間", "36協定", "勤怠", "働き方改革", "残業"]):
        return {
            "scene_type": "勤怠・労働時間管理の確認",
            "backdrop": "office work area with wall clock, HR staff checking attendance data on a laptop, slightly wider angle than a tabletop-only scene",
            "people": "one or two businesspeople from side/back, non-identifiable, reviewing time-management materials",
            "elements": "clock, laptop screen without readable UI, blank timesheet-like papers, calendar with no legible dates",
        }
    if any(key in text for key in ["高年齢者", "労働災害", "安全衛生", "作業環境", "熱中症"]):
        return {
            "scene_type": "職場の安全衛生・作業現場確認",
            "backdrop": "factory, warehouse, or construction-adjacent workplace safety inspection scene, clean and realistic, not an office desk",
            "people": "worker or supervisor in safety helmet/vest from side or back, non-identifiable, inspecting workplace",
            "elements": "helmet, safety vest, clipboard without readable text, machinery or warehouse shelves softly blurred",
        }
    if any(key in text for key in ["社宅", "現物給与", "住宅", "家賃"]):
        return {
            "scene_type": "社宅・住宅手当・給与計算の確認",
            "backdrop": "businessperson reviewing housing-related payroll documents with an apartment building or urban residential exterior softly visible",
            "people": "businessperson's hands or side profile only, non-identifiable",
            "elements": "blank housing contract-like pages, calculator, keys, laptop, city apartment background",
        }
    if any(key in text for key in ["ストレスチェック", "メンタルヘルス", "休職", "復職"]):
        return {
            "scene_type": "人事面談・メンタルヘルス相談",
            "backdrop": "quiet consultation room or calm HR interview space with warm daylight and privacy-aware composition",
            "people": "two businesspeople in a respectful consultation posture, side/back view, non-identifiable",
            "elements": "notebook, blank form, tea cup, soft plants, uncluttered table",
        }
    if any(key in text for key in ["ハラスメント", "カスハラ", "相談窓口", "苦情"]):
        return {
            "scene_type": "相談対応・顧客対応の面談",
            "backdrop": "office consultation booth or service counter meeting space, serious but calm business atmosphere",
            "people": "staff and visitor in conversation from side/back, non-identifiable, professional distance",
            "elements": "blank memo pad, laptop, partition, folder, no readable signage",
        }
    if any(key in text for key in ["年金", "ライフプラン", "老齢", "退職"]):
        return {
            "scene_type": "ライフプラン・年金相談",
            "backdrop": "consultation table with business district or cityscape visible through window, calm planning atmosphere",
            "people": "advisor and client from side/back, non-identifiable, reviewing blank planning documents",
            "elements": "blank planning sheets, calculator, pen, laptop, city view",
        }
    return {
        "scene_type": "中小企業の人事労務相談・実務確認",
        "backdrop": "varied Japanese business setting chosen for the article, such as meeting room, client consultation, HR workspace, or business district exterior",
        "people": "businesspeople may appear when relevant, side/back view or hands only, non-identifiable",
        "elements": "blank documents, laptop, folder, pen, contextual business props with no readable text",
    }


def compact_prompt_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def render_image_plan(plan: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# アイキャッチ画像生成計画",
            "",
            f"- 生成日時: {plan['generated_at']}",
            f"- ステータス: {plan['status']}",
            f"- テーマ: {plan['topic_title']}",
            f"- 記事タイトル: {plan.get('article_title') or '未設定'}",
            f"- サイズ: {plan['width']} x {plan['height']}",
            f"- ファイル名: {plan['file_name']}",
            f"- 保存予定: {plan['output_path']}",
            f"- 実ファイル検出: {plan['file_exists']}",
            f"- ファイルサイズ: {plan['file_size']}",
            f"- タイトル帯: {plan.get('title_overlay', {}).get('status', '未処理')}",
            f"- 背景画像ステータス: {plan.get('base_image', {}).get('status', '未確認')}",
            f"- 写真品質必須: {plan.get('photorealistic_required')}",
            f"- 新規生成必須: {plan.get('new_image_required')}",
            f"- コード生成背景許可: {plan.get('code_generated_placeholder_allowed')}",
            f"- シーンタイプ: {plan.get('scene_profile', {}).get('scene_type', '未設定') if isinstance(plan.get('scene_profile'), dict) else '未設定'}",
            f"- 代替テキスト: {plan['alt_text']}",
            f"- WordPressアップロード準備: {plan['wordpress_ready']}",
            f"- 次の対応: {plan['next_action']}",
            "",
            "## 画像生成プロンプト",
            "",
            plan["prompt"],
        ]
    )
