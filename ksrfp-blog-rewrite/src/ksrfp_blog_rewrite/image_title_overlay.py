from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


LINE_START_FORBIDDEN = set("、。，．・：；？！?!)）】」』〉》〕］｝")
LINE_END_FORBIDDEN = set("（【「『〈《〔［｛(")


def apply_title_overlay(
    *,
    image_path: Path,
    title: str,
    overlay_settings: dict[str, Any],
    width: int,
    height: int,
    background_path: Path,
    previous_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enabled = overlay_settings.get("enabled", True) if isinstance(overlay_settings, dict) else True
    if not enabled:
        return {"status": "skipped", "reason": "title overlay disabled"}
    if not image_path.exists():
        return {"status": "error", "reason": f"image file is missing: {image_path}"}
    if not title.strip():
        return {"status": "error", "reason": "title is empty"}

    current_hash = sha256_file(image_path)
    previous_output_hash = str((previous_overlay or {}).get("output_sha256") or "")
    if current_hash != previous_output_hash:
        shutil.copy2(image_path, background_path)
    elif not background_path.exists():
        return {"status": "error", "reason": "background source is missing and current image is already overlaid"}

    settings = default_overlay_settings()
    if isinstance(overlay_settings, dict):
        settings.update({key: value for key, value in overlay_settings.items() if value is not None})

    background = Image.open(background_path).convert("RGB")
    background = fit_to_size(background, width, height)
    rendered = render_centered_title_bands(background, title.strip(), settings)
    rendered.save(image_path, optimize=True)

    return {
        "status": "ok",
        "style": "centered_blue_title_bands",
        "title": title.strip(),
        "width": width,
        "height": height,
        "line_count": int(rendered.info.get("title_line_count", 0) or 0),
        "background_path": str(background_path),
        "output_path": str(image_path),
        "background_sha256": sha256_file(background_path),
        "output_sha256": sha256_file(image_path),
        "output_size_bytes": image_path.stat().st_size,
    }


def default_overlay_settings() -> dict[str, Any]:
    return {
        "enabled": True,
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


def fit_to_size(image: Image.Image, width: int, height: int) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio > target_ratio:
        resized_height = height
        resized_width = int(height * source_ratio)
    else:
        resized_width = width
        resized_height = int(width / source_ratio)
    resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
    left = int((resized_width - width) / 2)
    top = int((resized_height - height) / 2)
    return resized.crop((left, top, left + width, top + height))


def render_centered_title_bands(image: Image.Image, title: str, settings: dict[str, Any]) -> Image.Image:
    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    padding_x = int(settings["padding_x"])
    padding_y = int(settings["padding_y"])
    max_text_width = int(canvas.width * float(settings["max_width_ratio"])) - padding_x * 2
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
            "rect_width": metric["width"] + padding_x * 2,
            "rect_height": metric["height"] + padding_y * 2,
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
        text_x = x + padding_x + int((rect["rect_width"] - rect["text_width"] - padding_x * 2) / 2)
        text_y = y + padding_y - int(rect["offset_y"])
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
        for line_count in unique_line_count_order(preferred_lines, 1, max_lines):
            lines = split_title_balanced(title, line_count, font, max_text_width)
            if lines:
                return font, lines
        lines = greedy_wrap(title, font, max_text_width, max_lines)
        if lines:
            return font, lines
    font = load_japanese_bold_font(min_font_size)
    return font, greedy_wrap(title, font, max_text_width, max_lines) or [title.replace(" ", "")]


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
        return [compact] if measure_text_width(compact, font) <= max_text_width and valid_title_lines([compact]) else []
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
    for char in compact:
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
    return lines if valid_title_lines(lines) else []


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


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
