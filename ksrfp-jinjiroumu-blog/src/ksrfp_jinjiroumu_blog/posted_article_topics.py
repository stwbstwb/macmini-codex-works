from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .io_utils import read_csv_dicts, write_csv_dicts, write_json, write_markdown
from .paths import CANNIBALIZATION_DIR


THEME_RULES = [
    (
        "お知らせ",
        ["お知らせ", "休業", "年末年始", "夏季休業", "/news/"],
    ),
    (
        "助成金・給付金",
        ["助成金", "給付金", "補助金", "奨励金", "雇用調整助成金", "キャリアアップ助成金"],
    ),
    (
        "労働時間・休日休暇",
        ["労働時間", "残業", "36協定", "休日", "休憩", "有給", "年次有給休暇", "変形労働時間"],
    ),
    (
        "就業規則・労務管理",
        ["就業規則", "労務管理", "服務規律", "懲戒", "副業", "テレワーク", "在宅勤務"],
    ),
    (
        "ハラスメント・安全衛生",
        ["ハラスメント", "カスハラ", "パワハラ", "セクハラ", "安全衛生", "ストレスチェック", "労災"],
    ),
    (
        "採用・雇用契約",
        ["採用", "求人", "雇用契約", "労働条件通知書", "試用期間", "内定", "パート", "アルバイト"],
    ),
    (
        "退職・解雇",
        ["退職", "解雇", "雇止め", "退職勧奨", "懲戒解雇", "定年"],
    ),
    (
        "育児介護・両立支援",
        ["育児", "介護", "産休", "育休", "看護休暇", "両立支援"],
    ),
    (
        "社会保険・労働保険",
        ["社会保険", "健康保険", "厚生年金", "雇用保険", "労働保険", "扶養", "算定基礎"],
    ),
    (
        "給与計算・賃金",
        ["給与", "賃金", "最低賃金", "割増賃金", "賞与", "年末調整", "所得税"],
    ),
    (
        "年金",
        ["年金", "在職老齢年金", "老齢年金", "障害年金", "遺族年金"],
    ),
    (
        "ライフプランニング",
        ["ライフプラン", "老後", "相続", "iDeCo", "NISA", "資産形成"],
    ),
]


def classify_posted_article_topics() -> dict[str, Any]:
    inventory_path = CANNIBALIZATION_DIR / "posted_articles_inventory.csv"
    articles = read_csv_dicts(inventory_path)
    rows: list[dict[str, Any]] = []

    for article in articles:
        theme, keywords = classify_article(article)
        rows.append(
            {
                "post_id": article.get("post_id", ""),
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "category": article.get("category", ""),
                "published_date": article.get("published_date", ""),
                "major_theme": theme,
                "matched_keywords": " / ".join(keywords),
                "slug_or_id": article.get("slug_or_id", ""),
            }
        )

    rows.sort(key=lambda row: (str(row["major_theme"]), str(row["published_date"])), reverse=True)
    summary_rows = build_summary(rows)

    write_csv_dicts(
        CANNIBALIZATION_DIR / "posted_articles_theme_inventory.csv",
        rows,
        ["post_id", "title", "url", "category", "published_date", "major_theme", "matched_keywords", "slug_or_id"],
    )
    write_csv_dicts(
        CANNIBALIZATION_DIR / "posted_articles_theme_summary.csv",
        summary_rows,
        ["major_theme", "count", "latest_published_date", "sample_titles"],
    )
    result = {
        "status": "ok",
        "article_count": len(rows),
        "theme_count": len(summary_rows),
        "theme_summary": summary_rows,
    }
    write_json(CANNIBALIZATION_DIR / "posted_articles_theme_summary.json", result)
    write_markdown(CANNIBALIZATION_DIR / "posted_articles_theme_report.md", render_report(result))
    return result


def classify_article(article: dict[str, str]) -> tuple[str, list[str]]:
    text = "\n".join(
        [
            article.get("title", ""),
            article.get("category", ""),
            article.get("url", ""),
            article.get("path", ""),
        ]
    )
    matches: list[tuple[str, list[str]]] = []
    for theme, keywords in THEME_RULES:
        hit_keywords = [keyword for keyword in keywords if keyword in text]
        if hit_keywords:
            matches.append((theme, hit_keywords))

    if not matches:
        return "その他", []

    matches.sort(key=lambda item: len(item[1]), reverse=True)
    return matches[0]


def build_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter(str(row["major_theme"]) for row in rows)
    latest_by_theme: dict[str, str] = defaultdict(str)
    samples_by_theme: dict[str, list[str]] = defaultdict(list)

    for row in sorted(rows, key=lambda item: parse_date_key(str(item["published_date"])), reverse=True):
        theme = str(row["major_theme"])
        published = str(row["published_date"])
        if published and published > latest_by_theme[theme]:
            latest_by_theme[theme] = published
        if len(samples_by_theme[theme]) < 3:
            samples_by_theme[theme].append(str(row["title"]))

    return [
        {
            "major_theme": theme,
            "count": count,
            "latest_published_date": latest_by_theme.get(theme, ""),
            "sample_titles": " / ".join(samples_by_theme.get(theme, [])),
        }
        for theme, count in counts.most_common()
    ]


def parse_date_key(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.min


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# 投稿済み記事 主要テーマ分類",
        "",
        f"- 分類記事数: {result['article_count']}",
        f"- テーマ数: {result['theme_count']}",
        "",
        "## テーマ別件数",
        "",
    ]
    for row in result["theme_summary"]:
        lines.append(
            f"- {row['major_theme']}: {row['count']}件 / 最新: {row['latest_published_date'] or '不明'}"
        )

    lines.extend(["", "## 使い方", ""])
    lines.append("- 新規テーマ選定時は、同一または近接テーマの過去記事を確認し、タイトル・検索意図・本文の重複を避ける。")
    lines.append("- 件数が多いテーマは、完全な新規記事よりもリライトや関連記事への内部リンクも検討する。")
    lines.append("- 件数が少なく、かつGSCで表示回数があるテーマは、新規記事候補として優先度を上げる。")
    return "\n".join(lines)
