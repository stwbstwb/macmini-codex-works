from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any


DOMAIN_KEYWORDS = [
    "民間の医療保険",
    "民間医療保険",
    "懲戒処分",
    "就業規則",
    "労働条件通知書",
    "雇用契約書",
    "労使協定",
    "36協定",
    "休憩",
    "残業代",
    "割増賃金",
    "労働時間",
    "平均賃金",
    "社会保険",
    "労働保険",
    "給与計算",
    "年金",
    "医療保険",
    "高額療養費",
    "ハラスメント",
    "カスハラ",
    "評価制度",
    "採用",
    "労務管理",
    "退職",
    "解雇",
    "有給休暇",
    "慶弔休暇",
    "パート",
    "アルバイト",
    "社会保険手続き",
]


def build_rewrite_brief(
    *,
    candidate: dict[str, Any],
    post: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    source_title = extract_rendered_text(post.get("title")) or str(candidate.get("title") or "")
    source_excerpt = extract_rendered_text(post.get("excerpt")) or str(candidate.get("excerpt") or "")
    content_raw = extract_raw_html(post.get("content"))
    content_text = normalize_content_text(content_raw)
    headings = extract_headings(content_raw)
    category_names = candidate.get("category_names") or []
    tag_names = candidate.get("tag_names") or []

    extraction = extract_theme_and_keywords(
        title=source_title,
        excerpt=source_excerpt,
        content_text=content_text,
        headings=headings,
        category_names=category_names,
    )
    selected = build_selected_topic(candidate, extraction, source_excerpt)

    return {
        "status": "ok",
        "generated_at": generated_at,
        "source": {
            "type": "past_wordpress_article",
            "post_id": candidate.get("post_id") or post.get("id"),
            "title": source_title,
            "url": candidate.get("url") or post.get("link"),
            "slug": post.get("slug"),
            "published_date": candidate.get("published_date") or post.get("date"),
            "modified_date": post.get("modified"),
            "views_total": candidate.get("views_total"),
            "views_recent": candidate.get("views_recent"),
            "computed_character_count": candidate.get("computed_character_count"),
            "h2_count": candidate.get("h2_count"),
            "h3_count": candidate.get("h3_count"),
            "category_names": category_names,
            "tag_names": tag_names,
            "selection_score": candidate.get("score"),
            "selection_reasons": candidate.get("reasons") or [],
        },
        "extraction": extraction,
        "source_article_snapshot": {
            "excerpt": source_excerpt,
            "content_character_count": len(content_text),
            "headings": headings,
        },
        "selected": selected,
        "alternatives": [],
        "generation_handoff": {
            "mode": "rewrite_past_article_as_new_article",
            "wordpress_write": False,
            "keep_same_theme": True,
            "keep_same_target_seo_keyword": True,
            "target_outputs": [
                "article_title",
                "article_outline",
                "article_body_text",
                "featured_image",
                "google_drive_text_file",
                "google_drive_image_file",
            ],
            "notes": [
                "WordPressへの下書き保存は行わない",
                "元記事のテーマとターゲットSEOキーワードは維持する",
                "本文は既存記事の単純な加筆ではなく、新規記事として再構成する",
            ],
        },
        "item_index": 1,
        "item_total": 1,
        "settings": {
            "project_name": settings.get("project_name"),
            "timezone": settings.get("timezone"),
        },
    }


def build_selected_topic(
    candidate: dict[str, Any],
    extraction: dict[str, Any],
    source_excerpt: str,
) -> dict[str, Any]:
    return {
        "topic_title": extraction["rewrite_theme"],
        "target_seo_keyword": extraction["target_seo_keyword"],
        "related_keywords": "、".join(extraction["related_keywords"]),
        "section_group": "past_article_rewrite",
        "labels": "、".join(candidate.get("category_names") or []),
        "excerpt": source_excerpt,
        "selection_reason": "past_article_low_views_and_thin_content",
        "final_score": candidate.get("score"),
        "matched_gsc_queries": extraction["target_seo_keyword"],
        "nearest_article_title": candidate.get("title"),
        "nearest_article_url": candidate.get("url"),
        "nearest_similarity": "source_article",
        "source_post_id": candidate.get("post_id"),
        "source_views_total": candidate.get("views_total"),
        "source_views_recent": candidate.get("views_recent"),
    }


def extract_theme_and_keywords(
    *,
    title: str,
    excerpt: str,
    content_text: str,
    headings: list[dict[str, str]],
    category_names: list[str],
) -> dict[str, Any]:
    evidence_text = " ".join(
        [
            title,
            excerpt,
            " ".join(heading["text"] for heading in headings),
            content_text[:3000],
            " ".join(category_names),
        ]
    )
    quoted_terms = extract_quoted_terms(title)
    title_terms = extract_domain_terms(title)
    heading_terms = extract_domain_terms(" ".join(heading["text"] for heading in headings))
    domain_terms = extract_domain_terms(evidence_text)
    related_keywords = dedupe_preserve_order([*quoted_terms, *title_terms, *heading_terms, *domain_terms])[:8]

    if not related_keywords:
        related_keywords = fallback_keywords_from_title(title)

    target_seo_keyword = build_target_keyword(related_keywords)
    source_theme = normalize_title_as_theme(title)
    rewrite_theme = build_rewrite_theme(source_theme, target_seo_keyword)
    target_reader = infer_target_reader(category_names, evidence_text)

    return {
        "source_theme": source_theme,
        "rewrite_theme": rewrite_theme,
        "target_seo_keyword": target_seo_keyword,
        "related_keywords": related_keywords,
        "target_reader": target_reader,
        "search_intent": build_search_intent(
            target_seo_keyword,
            source_theme=source_theme,
            target_reader=target_reader,
            category_names=category_names,
        ),
        "confidence": "medium" if target_seo_keyword else "low",
        "evidence": {
            "quoted_terms": quoted_terms,
            "title_terms": title_terms,
            "heading_terms": heading_terms,
            "domain_terms": domain_terms[:12],
            "heading_count": len(headings),
        },
    }


def extract_rendered_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("raw") or value.get("rendered") or ""
    return normalize_content_text(str(value or ""))


def extract_raw_html(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("raw") or value.get("rendered") or "")
    return str(value or "")


def normalize_content_text(value: str) -> str:
    value = re.sub(r"<!--.*?-->", " ", value, flags=re.DOTALL)
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.DOTALL | re.IGNORECASE)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.DOTALL | re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_headings(content: str) -> list[dict[str, str]]:
    headings: list[dict[str, str]] = []
    for match in re.finditer(r"<h([2-3])\b[^>]*>(.*?)</h\1>", content, flags=re.IGNORECASE | re.DOTALL):
        text = normalize_content_text(match.group(2))
        if text:
            headings.append({"level": f"h{match.group(1)}", "text": text})
    return headings


def extract_quoted_terms(title: str) -> list[str]:
    terms = []
    for pattern in (r"「([^」]{2,30})」", r"『([^』]{2,30})』", r"“([^”]{2,30})”"):
        terms.extend(match.strip() for match in re.findall(pattern, title) if match.strip())
    return terms


def extract_domain_terms(text: str) -> list[str]:
    return [keyword for keyword in DOMAIN_KEYWORDS if keyword in text]


def fallback_keywords_from_title(title: str) -> list[str]:
    cleaned = normalize_title_as_theme(title)
    chunks = re.split(r"[、。！？!?｜|：:／/（）()\s]+|とは|について|解説|必要|です|ます", cleaned)
    return [chunk for chunk in chunks if 2 <= len(chunk) <= 20][:4]


def build_target_keyword(related_keywords: list[str]) -> str:
    if not related_keywords:
        return ""

    primary = related_keywords[0]
    if " " in primary:
        return primary
    if len(related_keywords) >= 2 and related_keywords[1] not in primary:
        return f"{primary} {related_keywords[1]}"
    return primary


def normalize_title_as_theme(title: str) -> str:
    cleaned = re.sub(r"[!！?？]+$", "", title.strip())
    cleaned = cleaned.replace("「", "").replace("」", "")
    cleaned = cleaned.replace("『", "").replace("』", "")
    return cleaned.strip()


def build_rewrite_theme(source_theme: str, target_keyword: str) -> str:
    if is_life_planning_text(" ".join([source_theme, target_keyword])):
        return source_theme
    if target_keyword:
        return f"{target_keyword}に関する実務解説"
    return source_theme


def infer_target_reader(category_names: list[str], evidence_text: str) -> str:
    text = " ".join(category_names) + " " + evidence_text
    if "ライフプラン" in text or "年金" in text or "医療保険" in text:
        return "制度を調べている個人、従業員から相談を受ける人事労務担当者"
    if "クリニック" in text:
        return "クリニック経営者、院長、事務長、人事労務担当者"
    return "中小企業の経営者、人事労務担当者、管理職"


def build_search_intent(
    target_keyword: str,
    *,
    source_theme: str = "",
    target_reader: str = "",
    category_names: list[str] | None = None,
) -> str:
    life_planning_text = " ".join([target_keyword, source_theme, target_reader, " ".join(category_names or [])])
    if is_life_planning_text(life_planning_text):
        keyword_text = target_keyword or "民間の医療保険"
        return f"{keyword_text}について、公的医療保険や高額療養費、家計、ライフステージの変化を踏まえて必要性を判断したい。"
    if not target_keyword:
        return "元記事と同じテーマについて、実務で何を確認すべきかを知りたい。"
    return f"{target_keyword}について、会社が実務で何を確認し、どの書類・手順・記録を整えるべきかを知りたい。"


def is_life_planning_text(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "ライフプラン",
            "ライフステージ",
            "民間の医療保険",
            "民間医療保険",
            "高額療養費",
        )
    )


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    results = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def render_rewrite_brief(brief: dict[str, Any]) -> str:
    source = brief.get("source", {})
    extraction = brief.get("extraction", {})
    selected = brief.get("selected", {})
    headings = brief.get("source_article_snapshot", {}).get("headings", [])

    lines = [
        "# 過去記事リライト用ブリーフ",
        "",
        f"- 状態: {brief.get('status')}",
        f"- 生成日時: {brief.get('generated_at')}",
        "",
        "## 元記事",
        "",
        f"- post_id: {source.get('post_id')}",
        f"- title: {source.get('title')}",
        f"- url: {source.get('url')}",
        f"- views_total: {source.get('views_total')}",
        f"- views_recent: {source.get('views_recent')}",
        f"- computed_character_count: {source.get('computed_character_count')}",
        f"- h2_count: {source.get('h2_count')}",
        f"- h3_count: {source.get('h3_count')}",
        "",
        "## 抽出結果",
        "",
        f"- 元テーマ: {extraction.get('source_theme')}",
        f"- リライトテーマ: {extraction.get('rewrite_theme')}",
        f"- ターゲットSEOキーワード: {extraction.get('target_seo_keyword')}",
        f"- 関連キーワード: {'、'.join(extraction.get('related_keywords') or [])}",
        f"- 想定読者: {extraction.get('target_reader')}",
        f"- 検索意図: {extraction.get('search_intent')}",
        f"- 信頼度: {extraction.get('confidence')}",
        "",
        "## 後工程へ渡す selected",
        "",
        f"- topic_title: {selected.get('topic_title')}",
        f"- target_seo_keyword: {selected.get('target_seo_keyword')}",
        f"- section_group: {selected.get('section_group')}",
        f"- labels: {selected.get('labels')}",
        "",
        "## 元記事見出し",
        "",
    ]

    if headings:
        lines.extend(f"- {heading.get('level')}: {heading.get('text')}" for heading in headings[:40])
    else:
        lines.append("- なし")

    lines.extend(
        [
            "",
            "## 生成方針",
            "",
            "- WordPressへの下書き保存は行わない",
            "- 元記事と同じテーマ・ターゲットSEOキーワードで新規記事として再構成する",
            "- テキストファイルとアイキャッチ画像をGoogleドライブへ保存する後工程へ渡す",
        ]
    )

    return "\n".join(lines)
