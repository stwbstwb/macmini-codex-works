from __future__ import annotations

import re

from .io_utils import read_text, write_json, write_markdown
from .paths import GENERATED_DIR
import json


BANNED_PHRASES = [
    "再検索する必要がなくなる",
    "検索上位10記事",
    "ChatGPT",
    "柏谷横浜社労士事務所では",
    "ご相談を承っています",
    "ご相談ください",
    "お問い合わせください",
    "お気軽にご相談",
    "社労士に相談した方がよいケース",
    "専門家に相談",
    "専門家へ相談",
    "人事労務だより",
    "出典PDF",
    "掲載されていた",
    "掲載されていました",
    "取り上げられていた",
    "取り上げられていました",
    "この記事では、人事労務の情報は",
    "制度・ニュースの概要",
    "事例",
    "成功例",
]

PRACTICAL_TERMS = [
    "36協定",
    "就業規則",
    "社内ルール",
    "申請",
    "助成金",
    "待遇",
    "説明義務",
    "ストレスチェック",
    "メンタルヘルス",
    "ハラスメント",
    "労働時間",
    "賃金",
    "記録",
    "社内周知",
]

GENERIC_TEMPLATE_HEADINGS = [
    "導入前チェックリスト",
    "申請前のチェックリスト",
    "実務チェックリスト",
    "導入時のチェックリスト",
    "対応前チェックリスト",
    "確認チェックリスト",
]


def run_quality_check() -> dict[str, object]:
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    outline_path = GENERATED_DIR / "outlines" / "article_outline_latest.md"
    source_plan_path = GENERATED_DIR / "outlines" / "source_check_plan_latest.md"
    fact_check_path = GENERATED_DIR / "articles" / "fact_check_items_latest.json"

    article = read_text(article_path) if article_path.exists() else ""
    outline = read_text(outline_path) if outline_path.exists() else ""
    source_plan = read_text(source_plan_path) if source_plan_path.exists() else ""
    fact_check = json.loads(read_text(fact_check_path)) if fact_check_path.exists() else {}
    unverified_count = int(fact_check.get("unverified_count") or 0)
    fact_check_exists = bool(fact_check)

    h2s = re.findall(r"^## (.+)$", article, flags=re.MULTILINE)
    h3s = re.findall(r"^### (.+)$", article, flags=re.MULTILINE)
    heading_lengths = measure_heading_body_lengths(article)
    short_heading_blocks = [
        block
        for block in heading_lengths
        if block["level"] in (2, 3, 4) and int(block["body_length"]) < 200
    ]
    h2_duplicates = sorted({heading for heading in h2s if h2s.count(heading) > 1})
    generic_template_headings = [heading for heading in h2s if heading in GENERIC_TEMPLATE_HEADINGS]
    repetition = detect_intra_article_repetition(article)
    checks = {
        "article_exists": bool(article),
        "outline_exists": bool(outline),
        "source_plan_exists": bool(source_plan),
        "character_count": len(article),
        "h2_count": len(h2s),
        "h3_count": len(h3s),
        "h2_duplicates": h2_duplicates,
        "generic_template_headings": generic_template_headings,
        "first_h2_is_intro": bool(h2s and h2s[0] == "はじめに"),
        "last_h2_is_summary": bool(h2s and h2s[-1] == "まとめ"),
        "heading_body_lengths": heading_lengths,
        "short_heading_blocks": short_heading_blocks[:20],
        "all_heading_blocks_have_minimum_body": not short_heading_blocks,
        "has_newsletter_source_terms": any(
            phrase in article
            for phrase in [
                "人事労務だより",
                "出典PDF",
                "掲載されていた",
                "掲載されていました",
                "取り上げられていた",
                "取り上げられていました",
            ]
        ),
        "has_office_cta": any(
            phrase in article
            for phrase in [
                "柏谷横浜社労士事務所では",
                "ご相談を承っています",
                "ご相談ください",
                "お問い合わせください",
                "お気軽にご相談",
            ]
        ),
        "has_practical_points": "実務" in article and any(term in article for term in PRACTICAL_TERMS),
        "has_objective_expert_tone": "確認" in article and "実務" in article and "まとめ" in h2s,
        "has_source_check_plan": bool(source_plan),
        "fact_check_exists": fact_check_exists,
        "unverified_fact_count": unverified_count,
        "publication_ready": fact_check_exists and unverified_count == 0,
        "banned_phrases": [phrase for phrase in BANNED_PHRASES if phrase in article],
        "repetition": repetition,
        "has_repeated_paragraphs": bool(repetition["repeated_paragraphs"] or repetition["repeated_openings"]),
    }
    checks["draft_quality_passed"] = (
        checks["article_exists"]
        and checks["outline_exists"]
        and checks["source_plan_exists"]
        and checks["character_count"] >= 3000
        and checks["h2_count"] >= 7
        and not checks["h2_duplicates"]
        and not checks["generic_template_headings"]
        and checks["first_h2_is_intro"]
        and checks["last_h2_is_summary"]
        and checks["all_heading_blocks_have_minimum_body"]
        and checks["has_practical_points"]
        and checks["has_objective_expert_tone"]
        and not checks["has_office_cta"]
        and not checks["has_newsletter_source_terms"]
        and not checks["banned_phrases"]
        and not checks["has_repeated_paragraphs"]
    )
    checks["passed"] = checks["draft_quality_passed"] and checks["publication_ready"]
    write_json(GENERATED_DIR / "articles" / "article_quality_check_latest.json", checks)
    write_markdown(GENERATED_DIR / "articles" / "article_quality_check_latest.md", render_quality_report(checks))
    return checks


def render_quality_report(checks: dict[str, object]) -> str:
    lines = [
        "# 記事品質チェック",
        "",
        f"- 下書き品質判定: {'OK' if checks['draft_quality_passed'] else '要確認'}",
        f"- 公開可能判定: {'OK' if checks['publication_ready'] else '根拠確認待ち'}",
        f"- 総合判定: {'OK' if checks['passed'] else '要確認'}",
        f"- 文字数: {checks['character_count']}",
        f"- H2数: {checks['h2_count']}",
        f"- H3数: {checks['h3_count']}",
        f"- H2重複: {', '.join(checks['h2_duplicates']) if checks['h2_duplicates'] else 'なし'}",
        f"- 汎用テンプレート見出し: {', '.join(checks['generic_template_headings']) if checks['generic_template_headings'] else 'なし'}",
        f"- はじめに開始: {checks['first_h2_is_intro']}",
        f"- まとめ終了: {checks['last_h2_is_summary']}",
        f"- 各見出し200文字以上: {checks['all_heading_blocks_have_minimum_body']}",
        f"- 事務所アピール・CTAなし: {not checks['has_office_cta']}",
        f"- 出典管理語なし: {not checks['has_newsletter_source_terms']}",
        f"- 客観的な専門家トーン: {checks['has_objective_expert_tone']}",
        f"- 実務ポイント: {checks['has_practical_points']}",
        f"- 一次情報確認計画: {checks['has_source_check_plan']}",
        f"- ファクトチェック項目: {checks['unverified_fact_count']}件",
        f"- 禁止表現: {', '.join(checks['banned_phrases']) if checks['banned_phrases'] else 'なし'}",
        f"- 同一段落・定型文反復: {'あり' if checks.get('has_repeated_paragraphs') else 'なし'}",
        "",
        "## 注意",
        "",
        "このチェックは機械的な初期チェックです。法律、制度、日付、数値は投稿前に一次情報で確認し、未確認のまま公開工程へ進めないでください。",
    ]
    short_blocks = checks.get("short_heading_blocks") or []
    if short_blocks:
        lines.extend(["", "## 200文字未満の見出しブロック", ""])
        for block in short_blocks:
            lines.append(f"- {'#' * int(block['level'])} {block['heading']}: {block['body_length']}文字")
    repetition = checks.get("repetition") if isinstance(checks.get("repetition"), dict) else {}
    repeated_paragraphs = repetition.get("repeated_paragraphs") if isinstance(repetition, dict) else []
    repeated_openings = repetition.get("repeated_openings") if isinstance(repetition, dict) else []
    if repeated_paragraphs:
        lines.extend(["", "## 反復している段落", ""])
        for item in repeated_paragraphs[:10]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('count')}回: {item.get('sample')}")
    if repeated_openings:
        lines.extend(["", "## 反復している文頭パターン", ""])
        for item in repeated_openings[:10]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('count')}回: {item.get('opening')}")
    return "\n".join(lines)


def measure_heading_body_lengths(markdown: str) -> list[dict[str, object]]:
    headings = list(re.finditer(r"^(#{2,4})\s+(.+)$", markdown, flags=re.MULTILINE))
    blocks: list[dict[str, object]] = []
    for index, match in enumerate(headings):
        level = len(match.group(1))
        heading = match.group(2).strip()
        next_start = len(markdown)
        for next_match in headings[index + 1 :]:
            next_level = len(next_match.group(1))
            if next_level <= level:
                next_start = next_match.start()
                break
        body = markdown[match.end() : next_start]
        body_without_headings = re.sub(r"^#{2,4}\s+.+$", "", body, flags=re.MULTILINE)
        body_plain = re.sub(r"\s+", "", body_without_headings)
        blocks.append({"level": level, "heading": heading, "body_length": len(body_plain)})
    return blocks


def detect_intra_article_repetition(markdown: str) -> dict[str, object]:
    paragraphs = normalized_paragraph_records(markdown)
    by_text: dict[str, dict[str, object]] = {}
    for record in paragraphs:
        key = str(record["normalized"])
        if len(key) < 45:
            continue
        current = by_text.setdefault(
            key,
            {
                "count": 0,
                "sample": record["sample"],
            },
        )
        current["count"] = int(current["count"]) + 1

    repeated_paragraphs = [
        {
            "count": item["count"],
            "sample": item["sample"],
        }
        for item in by_text.values()
        if int(item["count"]) >= 3
    ]
    repeated_paragraphs.sort(key=lambda item: int(item["count"]), reverse=True)

    openings: dict[str, dict[str, object]] = {}
    for record in paragraphs:
        normalized = str(record["normalized"])
        if len(normalized) < 60:
            continue
        opening = normalized[:28]
        current = openings.setdefault(
            opening,
            {
                "count": 0,
                "opening": str(record["sample"])[:42],
            },
        )
        current["count"] = int(current["count"]) + 1
    repeated_openings = [
        {
            "count": item["count"],
            "opening": item["opening"],
        }
        for item in openings.values()
        if int(item["count"]) >= 5
    ]
    repeated_openings.sort(key=lambda item: int(item["count"]), reverse=True)

    return {
        "paragraph_count": len(paragraphs),
        "repeated_paragraphs": repeated_paragraphs,
        "repeated_openings": repeated_openings,
        "thresholds": {
            "repeated_paragraph_count_gte": 3,
            "repeated_opening_count_gte": 5,
            "min_normalized_paragraph_chars": 45,
        },
    }


def normalized_paragraph_records(markdown: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for raw in re.split(r"\n\s*\n", markdown):
        paragraph = raw.strip()
        if not paragraph:
            continue
        if paragraph.startswith(("#", "|", ">", "-", "*", "```", "<figure", "<table")):
            continue
        if re.match(r"^A[:：]", paragraph):
            continue
        cleaned = re.sub(r"\[[^\]]+]\([^)]+\)", "", paragraph)
        cleaned = re.sub(r"[#>*_`|「」『』（）()【】\[\]、。，．・:：;；!?！？\s]", "", cleaned)
        if not cleaned:
            continue
        records.append(
            {
                "sample": " ".join(paragraph.split())[:120],
                "normalized": cleaned,
            }
        )
    return records
