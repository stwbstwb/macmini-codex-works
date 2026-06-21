from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

from .ga_export import parse_ga_sections
from .io_utils import read_csv_dicts, to_int, write_csv_dicts, write_json, write_markdown
from .paths import CANNIBALIZATION_DIR, GA_DIR, SEO_ANALYSIS_DIR


THEME_KEYWORDS = {
    "社会保険": ["社会保険", "健康保険", "厚生年金", "扶養"],
    "雇用保険": ["雇用保険", "教育訓練給付", "失業"],
    "年金": ["年金", "遺族年金", "在職老齢年金"],
    "退職": ["退職", "退職者", "引継ぎ"],
    "有給休暇": ["有給", "年次有給休暇", "休暇"],
    "労働時間・休憩": ["労働時間", "残業", "休憩", "夜勤", "休日"],
    "労災": ["労災", "労働保険"],
    "パート・アルバイト": ["パート", "アルバイト", "短時間"],
    "給与計算": ["給与", "社会保険料", "算定基礎"],
    "助成金・給付金": ["助成金", "給付金"],
}


def build_ga_insights() -> dict[str, Any]:
    ga_path = first_ga_file()
    sections = parse_ga_sections(ga_path)
    page_rows = extract_page_title_rows(sections)
    posted_articles = read_csv_dicts(CANNIBALIZATION_DIR / "posted_articles_inventory.csv")
    category_by_title = build_category_lookup(posted_articles)

    aggregated: dict[str, dict[str, Any]] = {}
    for row in page_rows:
        title = clean_page_title(row["title"])
        views = row["views"]
        if not title:
            continue
        item = aggregated.setdefault(
            title,
            {
                "page_title": title,
                "views": 0,
                "variants": 0,
                "matched_category": "",
                "matched_url": "",
                "theme": classify_theme(title),
            },
        )
        item["views"] += views
        item["variants"] += 1

    rows = sorted(aggregated.values(), key=lambda row: int(row["views"]), reverse=True)
    for row in rows:
        category, url = nearest_category(row["page_title"], category_by_title)
        row["matched_category"] = category
        row["matched_url"] = url

    theme_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    for row in rows:
        theme_counter[row["theme"]] += int(row["views"])
        if row["matched_category"]:
            category_counter[row["matched_category"]] += int(row["views"])

    write_csv_dicts(
        SEO_ANALYSIS_DIR / "ga_top_pages.csv",
        rows,
        ["page_title", "views", "variants", "theme", "matched_category", "matched_url"],
    )
    theme_rows = [{"theme": theme, "views": views} for theme, views in theme_counter.most_common()]
    category_rows = [{"category": category, "views": views} for category, views in category_counter.most_common()]
    write_csv_dicts(SEO_ANALYSIS_DIR / "ga_theme_trends.csv", theme_rows, ["theme", "views"])
    write_csv_dicts(SEO_ANALYSIS_DIR / "ga_category_trends.csv", category_rows, ["category", "views"])

    result = {
        "status": "ok",
        "source_file": str(ga_path),
        "page_title_count": len(rows),
        "top_pages": rows[:20],
        "theme_trends": theme_rows,
        "category_trends": category_rows,
        "content_marketing_notes": build_content_marketing_notes(theme_counter),
    }
    write_json(SEO_ANALYSIS_DIR / "ga_content_insights.json", result)
    write_markdown(SEO_ANALYSIS_DIR / "ga_content_insights.md", render_ga_insights(result))
    return result


def first_ga_file():
    candidates = sorted(GA_DIR.glob("*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No GA CSV files found in {GA_DIR}")
    return candidates[0]


def extract_page_title_rows(sections) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        if section.header[:2] != ["ページ タイトルとスクリーン クラス", "表示回数"]:
            continue
        for row in section.rows:
            if len(row) < 2:
                continue
            rows.append({"title": row[0], "views": to_int(row[1])})
    return rows


def clean_page_title(title: str) -> str:
    cleaned = title.split("|", 1)[0].strip()
    return " ".join(cleaned.split())


def build_category_lookup(posted_articles: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "title": row.get("title", ""),
            "category": row.get("category", ""),
            "url": row.get("url", ""),
        }
        for row in posted_articles
        if row.get("title")
    ]


def nearest_category(title: str, lookup: list[dict[str, str]]) -> tuple[str, str]:
    best_ratio = 0.0
    best_category = ""
    best_url = ""
    for item in lookup:
        ratio = SequenceMatcher(None, normalize(title), normalize(item["title"])).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_category = item["category"]
            best_url = item["url"]
    if best_ratio < 0.62:
        return "", ""
    return best_category, best_url


def classify_theme(title: str) -> str:
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in title for keyword in keywords):
            return theme
    return "その他"


def normalize(text: str) -> str:
    return "".join(text.lower().split())


def build_content_marketing_notes(theme_counter: Counter[str]) -> list[str]:
    notes = []
    top_themes = [theme for theme, _ in theme_counter.most_common(5)]
    if "社会保険" in top_themes:
        notes.append("社会保険・扶養・健康保険系の記事は既存流入が強く、関連記事や更新記事の候補になりやすい。")
    if "雇用保険" in top_themes:
        notes.append("雇用保険・教育訓練給付系も検索流入との相性が良い。制度改正や対象者整理の記事に向く。")
    if "有給休暇" in top_themes or "労働時間・休憩" in top_themes:
        notes.append("休暇・休憩・労働時間は実務トラブルに直結し、中小企業向け解説と相性が良い。")
    if "年金" in top_themes:
        notes.append("年金系は個人向け検索も混ざるため、事業主向け文脈の整理が必要。")
    if not notes:
        notes.append("上位テーマを定期的に確認し、GSCクエリと組み合わせて新規記事・リライトを判断する。")
    return notes


def render_ga_insights(result: dict[str, Any]) -> str:
    lines = [
        "# GAコンテンツ傾向レポート",
        "",
        f"- 入力ファイル: {result['source_file']}",
        f"- 集計ページタイトル数: {result['page_title_count']}",
        "",
        "## 表示回数上位ページ",
        "",
    ]
    for row in result["top_pages"][:15]:
        lines.append(
            f"- {row['page_title']}: {row['views']} views / theme={row['theme']} / category={row['matched_category'] or '未照合'}"
        )

    lines.extend(["", "## テーマ傾向", ""])
    for row in result["theme_trends"][:10]:
        lines.append(f"- {row['theme']}: {row['views']} views")

    lines.extend(["", "## カテゴリ傾向", ""])
    for row in result["category_trends"][:10]:
        lines.append(f"- {row['category']}: {row['views']} views")

    lines.extend(["", "## コンテンツマーケティング上の示唆", ""])
    lines.extend(f"- {note}" for note in result["content_marketing_notes"])
    return "\n".join(lines)
