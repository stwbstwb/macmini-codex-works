from __future__ import annotations

from typing import Any


PHOTO_BACKGROUND_REASON = "アイキャッチ背景が写真品質ではありません。AI生成の写真背景ソースを作成してください。"
FRESH_PHOTO_BACKGROUND_REASON = (
    "アイキャッチ背景は、記事ごとに新規生成した写真品質ソースが必須です。"
    "過去画像・既存画像・同テーマ画像の再利用は不可です。"
)

BLOCKED_BASE_STATUSES = {
    "requires_photorealistic_source",
    "requires_fresh_photorealistic_source",
    "stale_photo_source_rejected",
    "existing_image_rejected",
    "generated_thematic_background",
    "generated_thematic_background_placeholder",
}

BLOCKED_QUALITY_GATES = {
    "blocked_until_photo_source_ready",
    "blocked_until_fresh_article_photo_source_ready",
    "existing_image_reuse_blocked",
    "placeholder_only",
}


def featured_image_gate_reasons(
    image_plan: dict[str, Any],
    image_exists: bool | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not image_plan:
        return ["アイキャッチ画像計画がありません。"]

    if image_exists is False or image_plan.get("file_exists") is False:
        reasons.append("アイキャッチ画像ファイルが存在しません。")

    if image_plan.get("wordpress_ready") is False:
        reasons.append("アイキャッチ画像がWordPressアップロード準備完了になっていません。")

    if image_plan.get("photorealistic_required", True):
        base_image = image_plan.get("base_image", {})
        base_image = base_image if isinstance(base_image, dict) else {}
        base_status = str(base_image.get("status") or "")
        quality_gate = str(base_image.get("quality_gate") or "")
        source_match = str(base_image.get("source_match") or "")
        photo_source_exists = bool(
            base_image.get("photo_source_exists") or image_plan.get("photo_source_exists")
        )
        photo_source_fresh = bool(base_image.get("photo_source_fresh"))
        if base_status in BLOCKED_BASE_STATUSES or quality_gate in BLOCKED_QUALITY_GATES:
            reasons.append(
                FRESH_PHOTO_BACKGROUND_REASON
                if "fresh" in quality_gate or "reuse" in quality_gate or "stale" in base_status
                else PHOTO_BACKGROUND_REASON
            )
        elif base_status != "photo_source_copied" and not photo_source_exists:
            reasons.append("アイキャッチ背景の写真ソースが確認できません。")
        elif not photo_source_fresh or source_match != "fresh_article_source":
            reasons.append(FRESH_PHOTO_BACKGROUND_REASON)

    return list(dict.fromkeys(reasons))


def featured_image_gate_passed(
    image_plan: dict[str, Any],
    image_exists: bool | None = None,
) -> bool:
    return not featured_image_gate_reasons(image_plan, image_exists=image_exists)
