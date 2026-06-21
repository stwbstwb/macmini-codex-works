from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any

from .article_brief import build_meta_description, build_slug, build_title_candidates, source_policy_violations
from .image_gate import featured_image_gate_reasons
from .io_utils import read_json, read_text, write_json, write_markdown
from .paths import CONFIG_DIR, GENERATED_DIR, WORDPRESS_PAYLOAD_DIR
from .schedule_planner import build_schedule_plan


DEFAULT_SETTINGS = {
    "default_post_status": "draft",
    "publication_requires_verified_facts": True,
    "wordpress_posting_requires_user_test": True,
}


def build_wordpress_payload() -> dict[str, Any]:
    WORDPRESS_PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    brief_path = GENERATED_DIR / "outlines" / "article_brief_latest.json"
    quality_path = GENERATED_DIR / "articles" / "article_quality_check_latest.json"
    fact_check_path = GENERATED_DIR / "articles" / "fact_check_items_latest.json"
    image_plan_path = GENERATED_DIR / "images" / "featured_image_plan_latest.json"

    article_markdown = read_text(article_path) if article_path.exists() else ""
    brief = read_json(brief_path, {}) or {}
    selected = brief.get("selected", {}) if isinstance(brief, dict) else {}
    quality = read_json(quality_path, {}) or {}
    fact_check = read_json(fact_check_path, {}) or {}
    image_plan = read_json(image_plan_path, {}) or {}

    title = extract_title(article_markdown) or first_title_candidate(selected)
    topic = selected.get("topic_title", "")
    labels = selected.get("labels", "")
    content_html = markdown_to_html(article_markdown)
    excerpt = build_meta_description(topic) if topic else ""
    category = assign_category(topic, labels, article_markdown, settings)
    tags = [] if not settings.get("wordpress_tags_enabled", False) else build_tags(topic, labels)
    schedule_plan = build_schedule_plan()
    ready_to_send, blocked_reasons = evaluate_ready_to_send(quality, fact_check, settings, image_plan)
    source_policy = source_policy_violations({key: str(value or "") for key, value in selected.items()})
    if source_policy:
        ready_to_send = False
        blocked_reasons.append("テーマ選定ポリシー違反があります: " + " / ".join(source_policy))

    wordpress_post = {
        "title": title,
        "status": settings.get("default_post_status", "draft"),
        "date": schedule_plan["scheduled_date_for_wordpress"],
        "date_gmt": schedule_plan["scheduled_date_gmt_for_wordpress"],
        "content": content_html,
        "excerpt": excerpt,
        "comment_status": "closed",
        "ping_status": "closed",
        "author": int(settings.get("wordpress_author", {}).get("id") or 2),
        "categories": [category["id"]] if category else [],
        "tags": tags,
        "featured_media": None,
    }
    if settings.get("set_post_slug", False):
        wordpress_post["slug"] = build_slug(topic, labels) if topic else slugify_title(title)

    payload = {
        "status": "ok" if article_markdown else "no_article",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ready_to_send": ready_to_send,
        "blocked_reasons": blocked_reasons,
        "wordpress": wordpress_post,
        "category_assignment": category,
        "schedule_plan": schedule_plan,
        "arkhe_css_editor": {
            "css": settings.get("arkhe_css_editor", ""),
            "rest_meta_key": None,
            "note": "Arkhe CSS EditorのREST API上のmeta keyは未確認。投稿API実装時に画面/APIで確認して反映する。",
        },
        "featured_image": summarize_featured_image(image_plan),
        "fact_check": summarize_fact_check(fact_check),
        "source": {
            "pdf_name": selected.get("pdf_name"),
            "section_group": selected.get("section_group"),
            "topic_title": topic,
            "topic_key": selected.get("topic_key"),
            "labels": labels,
            "date_mentions": selected.get("date_mentions"),
            "excerpt": selected.get("excerpt"),
            "nearest_article_title": selected.get("nearest_article_title"),
            "nearest_article_url": selected.get("nearest_article_url"),
            "nearest_similarity": selected.get("nearest_similarity"),
            "seo_article_fit": selected.get("seo_article_fit"),
            "editorial_policy_penalty": selected.get("editorial_policy_penalty"),
            "editorial_policy_reason": selected.get("editorial_policy_reason"),
            "selection_reason": selected.get("selection_reason"),
            "policy_violations": source_policy,
        },
        "quality": {
            "draft_quality_passed": bool(quality.get("draft_quality_passed")),
            "publication_ready": bool(quality.get("publication_ready")),
            "safe_to_publish": bool(quality.get("passed")),
            "fact_check_unverified": int(fact_check.get("unverified_count") or 0),
            "publication_gate": fact_check.get("publication_gate"),
        },
    }

    write_json(WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json", payload)
    write_markdown(WORDPRESS_PAYLOAD_DIR / "post_content_latest.html", content_html)
    write_markdown(WORDPRESS_PAYLOAD_DIR / "post_payload_latest.md", render_payload_summary(payload))
    return payload


def load_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    loaded = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    settings.update(loaded)
    return settings


def evaluate_ready_to_send(
    quality: dict[str, Any],
    fact_check: dict[str, Any],
    settings: dict[str, Any],
    image_plan: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    blocked_reasons: list[str] = []
    if not quality.get("draft_quality_passed"):
        blocked_reasons.append("下書き品質チェックがOKではありません。")
    if settings.get("publication_requires_verified_facts", True):
        if int(fact_check.get("unverified_count") or 0) > 0:
            blocked_reasons.append("法律・制度・日付・数値の未確認項目が残っています。")
        if fact_check.get("publication_gate") == "blocked_until_verified":
            blocked_reasons.append("ファクトチェックの公開ゲートが閉じています。")
    if settings.get("wordpress_posting_requires_user_test", True):
        blocked_reasons.append("WordPress下書き保存の動作確認と表示確認が未完了です。")
    blocked_reasons.extend(featured_image_gate_reasons(image_plan or {}))
    return not blocked_reasons, blocked_reasons


def summarize_featured_image(image_plan: dict[str, Any]) -> dict[str, Any]:
    base_image = image_plan.get("base_image", {}) if isinstance(image_plan, dict) else {}
    base_image = base_image if isinstance(base_image, dict) else {}
    return {
        "status": image_plan.get("status"),
        "output_path": image_plan.get("output_path"),
        "file_exists": image_plan.get("file_exists"),
        "wordpress_ready": image_plan.get("wordpress_ready"),
        "photorealistic_required": image_plan.get("photorealistic_required", True),
        "base_status": base_image.get("status"),
        "base_quality_gate": base_image.get("quality_gate"),
        "photo_source_exists": bool(base_image.get("photo_source_exists") or image_plan.get("photo_source_exists")),
        "photo_source_fresh": bool(base_image.get("photo_source_fresh")),
        "source_match": base_image.get("source_match"),
        "source_modified_at": base_image.get("source_modified_at"),
        "required_new_after": base_image.get("required_new_after"),
    }


def summarize_fact_check(fact_check: dict[str, Any]) -> dict[str, Any]:
    items = fact_check.get("items", []) if isinstance(fact_check, dict) else []
    verified_items: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        verified_items.append(
            {
                "claim": item.get("claim"),
                "item_type": item.get("item_type"),
                "status": item.get("status"),
                "verified_source_url": item.get("verified_source_url"),
                "verified_at": item.get("verified_at"),
                "verification_note": item.get("verification_note"),
                "required_source": item.get("required_source"),
            }
        )
    return {
        "status": fact_check.get("status"),
        "publication_gate": fact_check.get("publication_gate"),
        "unverified_count": int(fact_check.get("unverified_count") or 0),
        "verified_count": int(fact_check.get("verified_count") or 0),
        "verified_items": verified_items,
    }


def extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def first_title_candidate(selected: dict[str, Any]) -> str:
    topic = selected.get("topic_title", "")
    labels = selected.get("labels", "")
    return build_title_candidates(topic, labels)[0] if topic else ""


def slugify_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", title.lower()).strip("-")
    return cleaned or "labor-management-update"


def build_tags(topic: str, labels: str) -> list[str]:
    tags = ["人事労務", "中小企業"]
    if "労働時間" in topic or "働き方改革" in topic:
        tags.extend(["労働時間", "36協定", "働き方改革"])
    if "助成金" in topic or "subsidy" in labels:
        tags.append("助成金")
    if "パート" in topic or "有期" in topic:
        tags.extend(["パート", "有期雇用"])
    if "ハラスメント" in topic or "カスハラ" in topic:
        tags.append("ハラスメント")
    if "ストレスチェック" in topic or "メンタルヘルス" in topic:
        tags.extend(["メンタルヘルス", "ストレスチェック"])
    return list(dict.fromkeys(tags))


def assign_category(topic: str, labels: str, article_markdown: str, settings: dict[str, Any]) -> dict[str, Any]:
    categories = {category["slug"]: category for category in settings.get("wordpress_categories", [])}
    target = f"{topic}\n{labels}\n{article_markdown}"
    direct_topic_rules = [
        ("labor-management", ["同一賃金ガイドライン", "同一労働同一賃金ガイドライン", "女性活躍推進法", "一般事業主行動計画"]),
        ("benefits", ["出生時育児休業給付金", "育児休業給付金", "産後パパ育休"]),
        ("subsidy", ["65歳超雇用推進助成金", "65 歳超雇用推進助成金", "高年齢者評価制度等雇用管理改善コース"]),
    ]
    for slug, keywords in direct_topic_rules:
        if slug in categories and any(keyword in target for keyword in keywords):
            category = categories[slug]
            return {
                "id": int(category["id"]),
                "name": category["name"],
                "slug": category["slug"],
                "score": 120,
                "reason": "記事テーマで優先カテゴリに一致。",
            }
    priority_rules = [
        ("subsidy", ["subsidy", "助成金", "奨励金", "補助金"]),
        ("benefits", ["benefits", "給付金", "教育訓練給付"]),
        ("pension", ["pension", "年金", "遺族年金", "在職老齢年金", "厚生年金"]),
        ("payroll", ["payroll", "給与計算", "賃金台帳", "割増賃金"]),
    ]
    for slug, keywords in priority_rules:
        if slug in categories and any(keyword in f"{topic}\n{labels}" for keyword in keywords):
            category = categories[slug]
            return {
                "id": int(category["id"]),
                "name": category["name"],
                "slug": category["slug"],
                "score": 99,
                "reason": "テーマまたはラベルで優先カテゴリに一致。",
            }
    rules = [
        ("助成金", "subsidy", ["助成金", "奨励金", "補助金", "subsidy"]),
        ("給付金", "benefits", ["給付金", "教育訓練給付", "benefits"]),
        ("年金", "pension", ["年金", "遺族年金", "在職老齢年金", "厚生年金"]),
        ("給与計算", "payroll", ["給与計算", "賃金台帳", "割増賃金", "社会保険料", "算定基礎", "現物給与"]),
        ("ライフプランニング", "life-planning", ["ライフプランニング", "扶養", "健康保険と年金", "相続", "老後"]),
        (
            "労務管理",
            "labor-management",
            [
                "労務管理",
                "労働時間",
                "36協定",
                "就業規則",
                "有給休暇",
                "休憩",
                "ハラスメント",
                "ストレスチェック",
                "安全衛生",
                "雇用保険",
                "パート",
                "有期",
            ],
        ),
    ]
    scores: list[dict[str, Any]] = []
    for name, slug, keywords in rules:
        score = sum(3 if keyword in topic else 1 for keyword in keywords if keyword in target)
        if slug == "labor-management" and any(label in labels for label in ["labor_management", "law_change"]):
            score += 2
        if slug == "subsidy" and "subsidy" in labels:
            score += 3
        if score > 0 and slug in categories:
            category = categories[slug]
            scores.append(
                {
                    "id": int(category["id"]),
                    "name": category["name"],
                    "slug": category["slug"],
                    "score": score,
                    "reason": " / ".join(keyword for keyword in keywords if keyword in target)[:160],
                }
            )
    if not scores:
        fallback = categories.get("labor-management") or next(iter(categories.values()))
        return {
            "id": int(fallback["id"]),
            "name": fallback["name"],
            "slug": fallback["slug"],
            "score": 0,
            "reason": "明確なカテゴリ一致がないため既定カテゴリを設定。",
        }
    scores.sort(key=lambda row: (row["score"], row["id"] == 7), reverse=True)
    return scores[0]


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    blockquote: list[str] = []
    in_comment = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{format_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            output.append("<ul>")
            output.extend(f"<li>{format_inline(item)}</li>" for item in list_items)
            output.append("</ul>")
            list_items.clear()

    def flush_blockquote() -> None:
        if blockquote:
            output.append(f"<blockquote><p>{format_inline(' '.join(blockquote))}</p></blockquote>")
            blockquote.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        if not line:
            flush_paragraph()
            flush_list()
            flush_blockquote()
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_blockquote()
            level = len(heading.group(1))
            if level == 1:
                continue
            output.append(f"<h{level}>{format_inline(heading.group(2))}</h{level}>")
            continue
        if line.startswith(">"):
            flush_paragraph()
            flush_list()
            blockquote.append(line.lstrip("> ").strip())
            continue
        if line.startswith("- "):
            flush_paragraph()
            flush_blockquote()
            list_items.append(line[2:].strip())
            continue
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    flush_blockquote()
    return "\n".join(output)


def format_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


def render_payload_summary(payload: dict[str, Any]) -> str:
    wordpress = payload["wordpress"]
    quality = payload["quality"]
    category = payload.get("category_assignment") or {}
    featured_image = payload.get("featured_image") or {}
    lines = [
        "# WordPress投稿ペイロード",
        "",
        f"- 生成日時: {payload['generated_at']}",
        f"- 送信可能: {payload['ready_to_send']}",
        f"- 投稿ステータス: {wordpress['status']}",
        f"- タイトル: {wordpress['title']}",
        f"- スラッグ: {'設定しない' if 'slug' not in wordpress else wordpress['slug']}",
        f"- 設定日時: {wordpress.get('date', '未設定')}",
        f"- 投稿者ID: {wordpress['author']}",
        f"- カテゴリ: {category.get('name', '未設定')}（ID: {category.get('id', '未設定')} / slug: {category.get('slug', '未設定')}）",
        f"- カテゴリ判定理由: {category.get('reason', 'なし')}",
        f"- タグ: {'設定しない' if not wordpress['tags'] else ', '.join(map(str, wordpress['tags']))}",
        f"- 下書き品質: {quality['draft_quality_passed']}",
        f"- 公開可能: {quality['publication_ready']}",
        f"- 未確認ファクト: {quality['fact_check_unverified']}件",
        f"- 公開ゲート: {quality['publication_gate']}",
        f"- Arkhe CSS Editor: {'設定あり' if payload.get('arkhe_css_editor', {}).get('css') else '未設定'}",
        f"- アイキャッチ準備: {featured_image.get('wordpress_ready')}",
        f"- アイキャッチ背景: {featured_image.get('base_status')}",
        f"- 写真背景ソース: {featured_image.get('photo_source_exists')}",
        "",
        "## 停止理由",
        "",
    ]
    if payload["blocked_reasons"]:
        lines.extend(f"- {reason}" for reason in payload["blocked_reasons"])
    else:
        lines.append("- なし")
    lines.extend(
        [
            "",
            "## 注意",
            "",
            "このファイルはWordPress送信前のペイロード確認用です。未確認ファクト、API接続テスト、表示確認が残る場合は送信しません。",
        ]
    )
    return "\n".join(lines)
