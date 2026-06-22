from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def build_featured_image_plan(article: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    title = str(article.get("title") or "")
    keyword = str(article.get("target_seo_keyword") or "")
    topic_type = str(article.get("topic_type") or "")
    source = brief.get("source") if isinstance(brief.get("source"), dict) else {}
    file_base = safe_file_base(title or keyword or "rewrite_article")
    prompt = build_prompt(title=title, keyword=keyword, topic_type=topic_type)

    return {
        "status": "ok",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "target_seo_keyword": keyword,
        "topic_type": topic_type,
        "source_post_id": source.get("post_id"),
        "file_base": file_base,
        "suggested_image_filename": f"{file_base}.png",
        "suggested_text_filename": f"{file_base}.txt",
        "prompt": prompt,
        "image_requirements": {
            "aspect_ratio": "16:9",
            "recommended_size": "1200x630",
            "background_text_in_image": False,
            "final_title_overlay_required": True,
            "title_overlay_style": "centered_blue_title_bands",
            "style": "clean professional Japanese business editorial photography",
        },
    }


def build_prompt(*, title: str, keyword: str, topic_type: str) -> str:
    if topic_type == "disciplinary_rules":
        subject = "A business manager and HR staff member reviewing a work rules binder and checklist on a desk"
        scene = "Modern Japanese small-business office meeting table, soft daylight, calm and trustworthy atmosphere"
    elif topic_type == "life_planning":
        subject = "A Japanese couple reviewing household budget notes, health insurance pamphlets, and a laptop at a dining table"
        scene = "Bright Japanese home dining table, practical financial planning atmosphere, calm natural daylight"
    else:
        subject = "Japanese small-business owner and HR staff reviewing workplace documents at a clean office desk"
        scene = "Modern Japanese office, practical and calm business setting"

    return "\n".join(
        [
            "Use case: ads-marketing",
            "Asset type: business blog featured image, landscape 16:9",
            f"Article title context: {title}",
            f"Target SEO keyword context: {keyword}",
            "Primary request: Create a clean, professional featured image for a Japanese financial planning and social insurance blog article.",
            f"Scene/backdrop: {scene}.",
            f"Subject: {subject}; documents should look realistic but contain no readable text.",
            "Composition: Wide landscape composition with generous open space in the center for a later title overlay.",
            "Style: Photorealistic editorial business photography, natural colors, clean and practical, not dramatic.",
            "Avoid: No readable text, no logos, no law-enforcement imagery, no courtroom, no handcuffs, no threatening scene, no watermark, no title text embedded in the image.",
            "Post-processing: The article title will be added later as centered blue bands with bold white Japanese text.",
        ]
    )


def safe_file_base(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "", value)
    value = re.sub(r"\s+", "", value)
    value = value.strip(" .")
    return value[:80] or "rewrite_article"
