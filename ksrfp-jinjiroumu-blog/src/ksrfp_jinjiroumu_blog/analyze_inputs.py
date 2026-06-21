from __future__ import annotations

from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from shutil import copy2
import hashlib
import re
import unicodedata
from urllib.parse import urlparse

from .ga_export import summarize_ga_sections
from .ga_insights import build_ga_insights
from .article_brief import build_article_brief, select_recommended_topics
from .article_writer import build_article_draft
from .io_utils import read_csv_dicts, read_json, read_text, to_float, to_int, write_csv_dicts, write_json, write_markdown
from .newsletter import summarize_pdf
from .outline_builder import build_outline
from .posted_article_topics import classify_posted_article_topics
from .source_plan import build_source_plan
from .quality_check import run_quality_check
from .quality_check import detect_intra_article_repetition
from .fact_check import build_fact_check_items
from .article_repair import repair_current_article
from .image_source_generator import ensure_fresh_image_source_from_plan
from .state_manager import completed_pdf_names, ensure_state_files, period_key, update_automation_status
from .wordpress_payload import build_wordpress_payload
from .drive_client import build_drive_status
from .wordpress_client import build_wordpress_status
from .image_plan import build_featured_image_plan
from .paths import (
    CANNIBALIZATION_DIR,
    GA_DIR,
    GENERATED_DIR,
    GSC_DIR,
    DRIVE_NEWSLETTER_DIR,
    LOCAL_NEWSLETTER_DIR,
    POSTED_ARTICLES_DIR,
    PROMPTS_DIR,
    SEO_ANALYSIS_DIR,
    TOPIC_SELECTION_DIR,
    WORDPRESS_PAYLOAD_DIR,
    ensure_output_dirs,
    PROJECT_ROOT,
)
from .review_text import build_review_text_file
from .topic_selector import score_topics


def _first_existing(directory: Path, names: list[str]) -> Path:
    for name in names:
        path = directory / name
        if path.exists():
            return path
    matches = sorted(directory.glob("*"))
    if not matches:
        raise FileNotFoundError(f"No files found in {directory}")
    return matches[0]


def _gsc_row(row: dict[str, str], dimension_key: str) -> dict[str, object]:
    return {
        "dimension": row.get(dimension_key, ""),
        "clicks": to_int(row.get("クリック数")),
        "impressions": to_int(row.get("表示回数")),
        "ctr_percent": to_float(row.get("CTR")),
        "position": round(to_float(row.get("掲載順位")), 2),
    }


def analyze_gsc() -> dict[str, object]:
    query_path = _first_existing(GSC_DIR, ["クエリ.csv"])
    page_path = _first_existing(GSC_DIR, ["ページ.csv", "ページ.csv"])

    queries = [_gsc_row(row, "上位のクエリ") for row in read_csv_dicts(query_path)]
    pages = [_gsc_row(row, "上位のページ") for row in read_csv_dicts(page_path)]

    queries.sort(key=lambda row: int(row["clicks"]), reverse=True)
    pages.sort(key=lambda row: int(row["clicks"]), reverse=True)

    query_opportunities = [
        row
        for row in queries
        if int(row["impressions"]) >= 300 and float(row["position"]) <= 20 and float(row["ctr_percent"]) < 5
    ]
    query_opportunities.sort(key=lambda row: (float(row["position"]), -int(row["impressions"])))

    page_opportunities = [
        row
        for row in pages
        if int(row["impressions"]) >= 1000 and float(row["position"]) <= 20 and float(row["ctr_percent"]) < 4
    ]
    page_opportunities.sort(key=lambda row: (float(row["position"]), -int(row["impressions"])))

    fields = ["dimension", "clicks", "impressions", "ctr_percent", "position"]
    write_csv_dicts(SEO_ANALYSIS_DIR / "gsc_top_queries.csv", queries[:100], fields)
    write_csv_dicts(SEO_ANALYSIS_DIR / "gsc_top_pages.csv", pages[:100], fields)
    write_csv_dicts(SEO_ANALYSIS_DIR / "gsc_query_opportunities.csv", query_opportunities[:100], fields)
    write_csv_dicts(SEO_ANALYSIS_DIR / "gsc_page_opportunities.csv", page_opportunities[:100], fields)

    return {
        "query_file": str(query_path),
        "page_file": str(page_path),
        "query_count": len(queries),
        "page_count": len(pages),
        "top_queries": queries[:10],
        "top_pages": pages[:10],
        "query_opportunity_count": len(query_opportunities),
        "page_opportunity_count": len(page_opportunities),
    }


def analyze_posted_articles() -> dict[str, object]:
    path = _first_existing(POSTED_ARTICLES_DIR, ["export-all-urls-811885.csv"])
    rows = read_csv_dicts(path)
    inventory: list[dict[str, object]] = []
    category_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()

    for row in rows:
        title = row.get("Title", "").strip()
        url = row.get("URL", "").strip()
        category = row.get("Categories", "").strip()
        published = row.get("Published Date", "").strip()
        parsed_url = urlparse(url)
        path_parts = [part for part in parsed_url.path.split("/") if part]
        slug_or_id = path_parts[-1] if path_parts else ""
        year = published[:4] if len(published) >= 4 else ""
        category_counter[category] += 1
        if year:
            year_counter[year] += 1
        inventory.append(
            {
                "post_id": row.get("Post ID", ""),
                "title": title,
                "url": url,
                "category": category,
                "published_date": published,
                "modified_date": row.get("Modified Date", ""),
                "path": parsed_url.path,
                "slug_or_id": slug_or_id,
            }
        )

    write_csv_dicts(
        CANNIBALIZATION_DIR / "posted_articles_inventory.csv",
        inventory,
        ["post_id", "title", "url", "category", "published_date", "modified_date", "path", "slug_or_id"],
    )
    write_csv_dicts(
        CANNIBALIZATION_DIR / "posted_articles_category_summary.csv",
        [{"category": category, "count": count} for category, count in category_counter.most_common()],
        ["category", "count"],
    )

    return {
        "file": str(path),
        "article_count": len(inventory),
        "category_summary": category_counter.most_common(),
        "year_summary": sorted(year_counter.items()),
        "latest_articles": sorted(inventory, key=lambda row: str(row["published_date"]), reverse=True)[:10],
    }


def analyze_ga() -> dict[str, object]:
    path = _first_existing(GA_DIR, ["レポートのスナップショット.csv", "レポートのスナップショット.csv"])
    summary = summarize_ga_sections(path)
    summary["file"] = str(path)
    write_json(SEO_ANALYSIS_DIR / "ga_sections_summary.json", summary)
    return summary


def analyze_prompts() -> dict[str, object]:
    prompt_files = sorted(PROMPTS_DIR.glob("*.txt"))
    summaries: list[dict[str, object]] = []
    for path in prompt_files:
        text = read_text(path)
        summaries.append(
            {
                "file": path.name,
                "characters": len(text),
                "lines": len(text.splitlines()),
                "contains_target_keyword": "#ターゲットキーワード" in text,
                "contains_article_title": "#記事タイトル" in text,
                "contains_markdown_rule": "Markdown" in text,
            }
        )
    write_json(TOPIC_SELECTION_DIR / "prompt_inventory.json", {"prompts": summaries})
    return {"prompt_count": len(summaries), "prompts": summaries}


def analyze_newsletters(excluded_issue_names: set[str] | None = None) -> dict[str, object]:
    all_pdfs = newsletter_pdf_paths()
    selection = select_newsletter_issue_for_generation(all_pdfs, excluded_issue_names=excluded_issue_names)
    pdfs = selection["selected_paths"]
    results = [summarize_pdf(path) for path in pdfs]
    write_json(
        TOPIC_SELECTION_DIR / "newsletter_pdf_summaries.json",
        {
            "status": selection["status"],
            "issue_selection": render_issue_selection_for_json(selection),
            "pdfs": results,
        },
    )

    candidate_rows: list[dict[str, object]] = []
    for result in results:
        for topic in result["topics"][:20]:
            candidate_rows.append(
                {
                    "pdf_name": topic["pdf_name"],
                    "section_group": topic["section_group"],
                    "topic_title": topic["topic_title"],
                    "labels": ",".join(topic["labels"]),
                    "score": topic["score"],
                    "date_mentions": " / ".join(topic["date_mentions"]),
                    "excerpt": topic["excerpt"],
                }
            )
    candidate_rows.sort(key=lambda row: int(row["score"]), reverse=True)
    write_csv_dicts(
        TOPIC_SELECTION_DIR / "newsletter_topic_candidates.csv",
        candidate_rows,
        ["pdf_name", "section_group", "topic_title", "labels", "score", "date_mentions", "excerpt"],
    )
    return {
        "status": selection["status"],
        "pdf_count": len(results),
        "available_pdf_count": len(all_pdfs),
        "topic_candidate_count": len(candidate_rows),
        "top_candidates": candidate_rows[:10],
        "issue_selection": render_issue_selection_for_json(selection),
    }


def select_newsletter_issue_for_generation(
    pdfs: list[Path],
    excluded_issue_names: set[str] | None = None,
) -> dict[str, object]:
    state = ensure_state_files()
    completed = completed_pdf_names(state.get("processed_pdfs", {}))
    excluded_issue_names = excluded_issue_names or set()
    ordered = sorted(
        pdfs,
        key=lambda path: (period_key(path.name), normalized_filename_key(path.name)),
        reverse=True,
    )
    skipped = []
    for path in ordered:
        if path.name in completed:
            skipped.append(
                {
                    "pdf_name": path.name,
                    "period_key": period_key(path.name),
                    "reason": "already_created_from_issue",
                }
            )
            continue
        if path.name in excluded_issue_names:
            skipped.append(
                {
                    "pdf_name": path.name,
                    "period_key": period_key(path.name),
                    "reason": "insufficient_viable_topics_in_issue",
                }
            )
            continue
        return {
            "status": "ok",
            "selected_paths": [path],
            "selected_pdf_name": path.name,
            "selected_period_key": period_key(path.name),
            "skipped_completed_issues": skipped,
            "all_pdf_names": [path.name for path in ordered],
        }
    return {
        "status": "all_issues_completed",
        "selected_paths": [],
        "selected_pdf_name": None,
        "selected_period_key": None,
        "skipped_completed_issues": skipped,
        "all_pdf_names": [path.name for path in ordered],
    }


def render_issue_selection_for_json(selection: dict[str, object]) -> dict[str, object]:
    return {
        "status": selection.get("status"),
        "selected_pdf_name": selection.get("selected_pdf_name"),
        "selected_period_key": selection.get("selected_period_key"),
        "skipped_completed_issues": selection.get("skipped_completed_issues", []),
        "all_pdf_names": selection.get("all_pdf_names", []),
    }


def newsletter_pdf_paths() -> list[Path]:
    by_name: dict[str, Path] = {}
    for path in sorted(LOCAL_NEWSLETTER_DIR.glob("*.pdf")):
        by_name[normalized_filename_key(path.name)] = path
    for path in sorted(DRIVE_NEWSLETTER_DIR.glob("*.pdf")):
        by_name[normalized_filename_key(path.name)] = path
    return sorted(by_name.values(), key=lambda path: path.name)


def normalized_filename_key(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def build_markdown_report(results: dict[str, object]) -> str:
    gsc = results["gsc"]
    posted = results["posted_articles"]
    ga = results["ga"]
    newsletters = results["newsletters"]
    prompts = results["prompts"]
    topic_selection = results.get("topic_selection", {})
    ga_insights = results.get("ga_insights", {})
    article_draft = results.get("article_draft", {})
    quality_check = results.get("quality_check", {})
    fact_check = results.get("fact_check", {})
    wordpress_payload = results.get("wordpress_payload", {})
    drive_status = results.get("drive_status", {})
    wordpress_status = results.get("wordpress_status", {})
    image_plan = results.get("featured_image_plan", {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 初期データ解析レポート",
        "",
        f"生成日時: {now}",
        "",
        "## 入力データ",
        "",
        f"- GSCクエリ数: {gsc['query_count']}",
        f"- GSCページ数: {gsc['page_count']}",
        f"- GAセクション数: {ga['section_count']}",
        f"- GA集計ページタイトル数: {ga_insights.get('page_title_count', 0)}",
        f"- 投稿済み記事数: {posted['article_count']}",
        f"- プロンプト数: {prompts['prompt_count']}",
        f"- 人事労務だよりPDF数: {newsletters['pdf_count']}",
        f"- 利用可能PDF数: {newsletters.get('available_pdf_count', newsletters['pdf_count'])}",
        f"- 今回対象号: {newsletters.get('issue_selection', {}).get('selected_pdf_name') if isinstance(newsletters.get('issue_selection'), dict) else '未記録'}",
        f"- スコア済みテーマ候補数: {topic_selection.get('scored_topic_count', 0)}",
        f"- 記事本文ドラフト文字数: {article_draft.get('character_count', 0)}",
        f"- 下書き品質チェック: {'OK' if quality_check.get('draft_quality_passed') else '要確認'}",
        f"- 公開可能判定: {'OK' if quality_check.get('publication_ready') else '根拠確認待ち'}",
        f"- 未確認ファクト数: {fact_check.get('unverified_count', 0)}",
        f"- WordPress送信可能: {wordpress_payload.get('ready_to_send', False)}",
        f"- アイキャッチ画像計画: {image_plan.get('status', '未生成')}",
        f"- Google Drive連携状態: {drive_status.get('status', '未確認')}",
        f"- WordPress連携状態: {wordpress_status.get('status', '未確認')}",
        "",
        "## GSC上位クエリ",
        "",
    ]
    for row in gsc["top_queries"][:10]:
        lines.append(
            f"- {row['dimension']}: クリック {row['clicks']}, 表示 {row['impressions']}, CTR {row['ctr_percent']}%, 掲載順位 {row['position']}"
        )

    lines.extend(["", "## 投稿済み記事カテゴリ", ""])
    for category, count in posted["category_summary"]:
        lines.append(f"- {category}: {count}件")

    posted_themes = results.get("posted_article_topics", {})
    lines.extend(["", "## 投稿済み記事の主要テーマ", ""])
    for row in posted_themes.get("theme_summary", [])[:10]:
        lines.append(
            f"- {row['major_theme']}: {row['count']}件 / 最新: {row['latest_published_date'] or '不明'}"
        )

    lines.extend(["", "## GA表示回数上位テーマ", ""])
    for row in ga_insights.get("theme_trends", [])[:8]:
        lines.append(f"- {row['theme']}: {row['views']} views")

    lines.extend(["", "## PDFから抽出した記事候補", ""])
    issue_selection = newsletters.get("issue_selection", {}) if isinstance(newsletters.get("issue_selection"), dict) else {}
    if issue_selection:
        lines.extend(
            [
                f"- 号選定ステータス: {issue_selection.get('status')}",
                f"- 今回対象号: {issue_selection.get('selected_pdf_name') or 'なし'}",
                f"- 作成済みスキップ: {len(issue_selection.get('skipped_completed_issues', [])) if isinstance(issue_selection.get('skipped_completed_issues'), list) else 0}件",
                "",
            ]
        )
    for row in newsletters["top_candidates"][:10]:
        lines.append(
            f"- {row['topic_title']}（{row['section_group']} / {row['pdf_name']} / score {row['score']} / {row['labels']}）"
        )
    if not newsletters["top_candidates"]:
        lines.append("- 候補なし")

    lines.extend(["", "## テーマ選定スコア上位", ""])
    for row in topic_selection.get("top_topics", [])[:5]:
        lines.append(
            f"- {row['topic_title']}: 最終スコア {row['final_score']}, 類似度 {row['nearest_similarity']}"
        )

    lines.extend(
        [
            "",
            "## 生成ファイル",
            "",
            "- `02_analysis/seo/gsc_top_queries.csv`",
            "- `02_analysis/seo/gsc_top_pages.csv`",
            "- `02_analysis/seo/gsc_query_opportunities.csv`",
            "- `02_analysis/seo/gsc_page_opportunities.csv`",
            "- `02_analysis/seo/ga_sections_summary.json`",
            "- `02_analysis/seo/ga_content_insights.md`",
            "- `02_analysis/seo/ga_top_pages.csv`",
            "- `02_analysis/seo/ga_theme_trends.csv`",
            "- `02_analysis/seo/ga_category_trends.csv`",
            "- `02_analysis/cannibalization/posted_articles_inventory.csv`",
            "- `02_analysis/cannibalization/posted_articles_category_summary.csv`",
            "- `02_analysis/cannibalization/posted_articles_theme_inventory.csv`",
            "- `02_analysis/cannibalization/posted_articles_theme_summary.csv`",
            "- `02_analysis/cannibalization/posted_articles_theme_report.md`",
            "- `02_analysis/topic-selection/newsletter_pdf_summaries.json`",
            "- `02_analysis/topic-selection/newsletter_topic_candidates.csv`",
            "- `02_analysis/topic-selection/prompt_inventory.json`",
            "- `02_analysis/topic-selection/topic_selection_scores.csv`",
            "- `02_analysis/topic-selection/topic_selection_report.md`",
            "- `03_generated/outlines/article_brief_latest.md`",
            "- `03_generated/outlines/article_brief_latest.json`",
            "- `03_generated/outlines/source_check_plan_latest.md`",
            "- `03_generated/outlines/source_check_plan_latest.json`",
            "- `03_generated/outlines/article_outline_latest.md`",
            "- `03_generated/outlines/article_outline_latest.json`",
            "- `03_generated/articles/article_draft_latest.md`",
            "- `03_generated/articles/article_draft_latest.json`",
            "- `03_generated/articles/fact_check_items_latest.md`",
            "- `03_generated/articles/fact_check_items_latest.json`",
            "- `03_generated/articles/article_quality_check_latest.md`",
            "- `03_generated/articles/article_quality_check_latest.json`",
            "- `03_generated/images/featured_image_plan_latest.md`",
            "- `03_generated/images/featured_image_plan_latest.json`",
            "- `03_generated/review-texts/review_text_latest.txt`",
            "- `03_generated/review-texts/review_text_latest.json`",
            "- `03_generated/wordpress-payloads/schedule_plan_latest.md`",
            "- `03_generated/wordpress-payloads/schedule_plan_latest.json`",
            "- `03_generated/wordpress-payloads/post_payload_latest.md`",
            "- `03_generated/wordpress-payloads/post_payload_latest.json`",
            "- `05_drive/drive_status_latest.md`",
            "- `04_wordpress/wordpress_status_latest.md`",
            "- `08_state/state_summary.md`",
        ]
    )
    return "\n".join(lines)


LATEST_OUTPUTS = {
    "article_brief_json": GENERATED_DIR / "outlines" / "article_brief_latest.json",
    "article_brief_md": GENERATED_DIR / "outlines" / "article_brief_latest.md",
    "source_plan_json": GENERATED_DIR / "outlines" / "source_check_plan_latest.json",
    "source_plan_md": GENERATED_DIR / "outlines" / "source_check_plan_latest.md",
    "article_outline_json": GENERATED_DIR / "outlines" / "article_outline_latest.json",
    "article_outline_md": GENERATED_DIR / "outlines" / "article_outline_latest.md",
    "article_draft_json": GENERATED_DIR / "articles" / "article_draft_latest.json",
    "article_draft_md": GENERATED_DIR / "articles" / "article_draft_latest.md",
    "fact_check_json": GENERATED_DIR / "articles" / "fact_check_items_latest.json",
    "fact_check_md": GENERATED_DIR / "articles" / "fact_check_items_latest.md",
    "fact_check_csv": GENERATED_DIR / "articles" / "fact_check_items_latest.csv",
    "quality_check_json": GENERATED_DIR / "articles" / "article_quality_check_latest.json",
    "quality_check_md": GENERATED_DIR / "articles" / "article_quality_check_latest.md",
    "featured_image_plan_json": GENERATED_DIR / "images" / "featured_image_plan_latest.json",
    "featured_image_plan_md": GENERATED_DIR / "images" / "featured_image_plan_latest.md",
    "review_text_json": GENERATED_DIR / "review-texts" / "review_text_latest.json",
    "review_text_md": GENERATED_DIR / "review-texts" / "review_text_latest.md",
    "review_text_txt": GENERATED_DIR / "review-texts" / "review_text_latest.txt",
    "schedule_plan_json": WORDPRESS_PAYLOAD_DIR / "schedule_plan_latest.json",
    "schedule_plan_md": WORDPRESS_PAYLOAD_DIR / "schedule_plan_latest.md",
    "post_payload_json": WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json",
    "post_payload_md": WORDPRESS_PAYLOAD_DIR / "post_payload_latest.md",
    "post_content_html": WORDPRESS_PAYLOAD_DIR / "post_content_latest.html",
}


def build_article_batch(results: dict[str, object], article_count: int) -> dict[str, object]:
    rows = read_csv_dicts(TOPIC_SELECTION_DIR / "topic_selection_scores.csv")
    selected_topics = select_recommended_topics(rows, limit=article_count)
    if not selected_topics:
        write_no_topic_latest_outputs(results, article_count)
    items: list[dict[str, object]] = []
    total = len(selected_topics)

    for index, selected in enumerate(selected_topics, start=1):
        brief = build_article_brief(
            selected_topic=selected,
            alternatives=selected_topics,
            item_index=index,
            item_total=total,
        )
        source_plan = build_source_plan()
        outline = build_outline()
        draft = build_article_draft()
        fact_check = build_fact_check_items()
        quality = run_quality_check()
        repair_attempts: list[dict[str, object]] = []
        for repair_attempt in range(1, 4):
            if quality.get("draft_quality_passed"):
                break
            repair = repair_current_article(quality, item_index=index, attempt=repair_attempt)
            repair_attempts.append(repair)
            if not repair.get("changed"):
                break
            draft = refresh_current_article_draft_result(selected)
            fact_check = build_fact_check_items()
            quality = run_quality_check()
        image_plan = build_featured_image_plan()
        image_generation_attempts: list[dict[str, object]] = []
        for image_attempt in range(1, 4):
            if image_plan.get("wordpress_ready"):
                break
            generation = ensure_fresh_image_source_from_plan(image_plan, item_index=index)
            image_generation_attempts.append(generation)
            if generation.get("status") != "ok":
                break
            image_plan = build_featured_image_plan()
        wordpress_payload = build_wordpress_payload()
        review_text = build_review_text_file(upload=False)
        outputs = snapshot_latest_outputs(index)
        item = {
            "item_index": index,
            "status": "ok",
            "selected": selected,
            "article_brief": brief,
            "source_plan": source_plan,
            "article_outline": outline,
            "article_draft": draft,
            "fact_check": fact_check,
            "quality_check": quality,
            "article_repair": repair_attempts,
            "featured_image_plan": image_plan,
            "image_source_generation": image_generation_attempts,
            "wordpress_payload": wordpress_payload,
            "review_text": review_text,
            "outputs": outputs,
        }
        items.append(item)

    batch = {
        "status": "ok" if len(items) == article_count else "insufficient_topics" if items else "no_topic",
        "requested_count": article_count,
        "generated_count": len(items),
        "items": items,
    }
    batch["batch_quality"] = evaluate_article_batch_quality(items)
    batch["batch_quality"]["requested_count"] = article_count
    batch["batch_quality"]["requested_count_met"] = len(items) == article_count
    if len(items) != article_count:
        batch["batch_quality"]["passed"] = False
        batch["batch_quality"]["insufficient_topic_count"] = {
            "requested": article_count,
            "generated": len(items),
        }
    if items and len(items) == article_count and not batch["batch_quality"].get("passed", False):
        batch["status"] = "quality_warning"
    write_json(GENERATED_DIR / "articles" / "article_batch_latest.json", batch)
    write_markdown(GENERATED_DIR / "articles" / "article_batch_latest.md", render_article_batch(batch))
    write_json(GENERATED_DIR / "articles" / "article_batch_quality_latest.json", batch["batch_quality"])
    write_markdown(
        GENERATED_DIR / "articles" / "article_batch_quality_latest.md",
        render_article_batch_quality(batch["batch_quality"]),
    )
    write_json(WORDPRESS_PAYLOAD_DIR / "post_payloads_latest.json", {"items": [item["wordpress_payload"] for item in items]})
    return batch


def refresh_current_article_draft_result(selected: dict[str, object]) -> dict[str, object]:
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    article = read_text(article_path) if article_path.exists() else ""
    title = extract_article_title(article)
    result = {
        "status": "ok" if article else "no_article",
        "selected_topic": selected.get("topic_title", ""),
        "title": title,
        "character_count": len(article),
        "path": str(article_path),
        "repaired": True,
    }
    write_json(GENERATED_DIR / "articles" / "article_draft_latest.json", result)
    return result


def write_no_topic_latest_outputs(results: dict[str, object], article_count: int) -> None:
    newsletters = results.get("newsletters", {}) if isinstance(results.get("newsletters"), dict) else {}
    issue_selection = newsletters.get("issue_selection", {}) if isinstance(newsletters.get("issue_selection"), dict) else {}
    reason = (
        "all_newsletter_issues_completed"
        if issue_selection.get("status") == "all_issues_completed"
        else "no_viable_topic"
    )
    brief = {
        "status": "no_topic",
        "reason": reason,
        "requested_count": article_count,
        "issue_selection": issue_selection,
    }
    write_json(GENERATED_DIR / "outlines" / "article_brief_latest.json", brief)
    write_markdown(
        GENERATED_DIR / "outlines" / "article_brief_latest.md",
        "# 記事作成ブリーフ\n\n候補テーマがありません。\n\n"
        f"- 理由: {reason}\n"
        f"- 号選定ステータス: {issue_selection.get('status') or '未記録'}\n",
    )
    write_json(GENERATED_DIR / "articles" / "article_draft_latest.json", {"status": "no_topic", "reason": reason})
    write_markdown(GENERATED_DIR / "articles" / "article_draft_latest.md", "# 記事本文ドラフト\n\n候補テーマがありません。")
    write_json(GENERATED_DIR / "articles" / "fact_check_items_latest.json", {"status": "no_topic", "unverified_count": 0, "items": []})
    write_markdown(GENERATED_DIR / "articles" / "fact_check_items_latest.md", "# ファクトチェック\n\n候補テーマがありません。")
    write_json(
        GENERATED_DIR / "articles" / "article_quality_check_latest.json",
        {
            "status": "no_topic",
            "passed": False,
            "draft_quality_passed": False,
            "publication_ready": False,
            "reason": reason,
        },
    )
    write_markdown(GENERATED_DIR / "articles" / "article_quality_check_latest.md", "# 記事品質チェック\n\n候補テーマがありません。")
    write_json(GENERATED_DIR / "images" / "featured_image_plan_latest.json", {"status": "no_topic", "wordpress_ready": False, "reason": reason})
    write_markdown(GENERATED_DIR / "images" / "featured_image_plan_latest.md", "# アイキャッチ画像計画\n\n候補テーマがありません。")
    write_json(GENERATED_DIR / "review-texts" / "review_text_latest.json", {"status": "no_topic", "reason": reason})
    write_markdown(GENERATED_DIR / "review-texts" / "review_text_latest.md", "# 確認用テキスト\n\n候補テーマがありません。")
    write_json(WORDPRESS_PAYLOAD_DIR / "post_payload_latest.json", {"status": "no_topic", "ready_to_send": False, "reason": reason})
    write_markdown(WORDPRESS_PAYLOAD_DIR / "post_payload_latest.md", "# WordPress投稿ペイロード\n\n候補テーマがありません。")
    write_json(WORDPRESS_PAYLOAD_DIR / "post_payloads_latest.json", {"items": []})


def evaluate_article_batch_quality(items: list[dict[str, object]]) -> dict[str, object]:
    article_dir = GENERATED_DIR / "articles"
    article_records: list[dict[str, object]] = []
    image_records: list[dict[str, object]] = []
    repetition_records: list[dict[str, object]] = []
    for item in items:
        outputs = item.get("outputs", {}) if isinstance(item.get("outputs"), dict) else {}
        path_text = outputs.get("article_draft_md")
        if not path_text:
            continue
        path = PROJECT_ROOT / str(path_text)
        article = read_text(path) if path.exists() else ""
        article_records.append(
            {
                "item_index": item.get("item_index"),
                "title": extract_article_title(article),
                "intro": extract_h2_section(article, "はじめに"),
                "summary": extract_h2_section(article, "まとめ"),
                "h2s": re.findall(r"^## (.+)$", article, flags=re.MULTILINE),
                "h2_signature": " > ".join(re.findall(r"^## (.+)$", article, flags=re.MULTILINE)),
                "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() else str(path),
            }
        )
        repetition = detect_intra_article_repetition(article)
        repeated_paragraphs = repetition.get("repeated_paragraphs", [])
        repeated_openings = repetition.get("repeated_openings", [])
        has_repetition = bool(repeated_paragraphs or repeated_openings)
        repetition_records.append(
            {
                "item_index": item.get("item_index"),
                "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() else str(path),
                "has_repetition": has_repetition,
                "repeated_paragraphs": repeated_paragraphs[:5] if isinstance(repeated_paragraphs, list) else [],
                "repeated_openings": repeated_openings[:5] if isinstance(repeated_openings, list) else [],
            }
        )
        image_record = image_source_record(item)
        if image_record:
            image_records.append(image_record)

    comparisons: list[dict[str, object]] = []
    for index, left in enumerate(article_records):
        for right in article_records[index + 1 :]:
            comparisons.append(
                {
                    "left_item": left["item_index"],
                    "right_item": right["item_index"],
                    "intro_similarity": round(text_similarity(str(left["intro"]), str(right["intro"])), 3),
                    "summary_similarity": round(text_similarity(str(left["summary"]), str(right["summary"])), 3),
                    "h2_similarity": round(text_similarity(str(left["h2_signature"]), str(right["h2_signature"])), 3),
                }
            )

    max_intro = max((float(item["intro_similarity"]) for item in comparisons), default=0.0)
    max_summary = max((float(item["summary_similarity"]) for item in comparisons), default=0.0)
    max_h2 = max((float(item["h2_similarity"]) for item in comparisons), default=0.0)
    duplicate_photo_source_pairs = duplicate_image_source_pairs(image_records)
    image_backgrounds_unique = not duplicate_photo_source_pairs
    intra_article_repetition_ok = not any(bool(item.get("has_repetition")) for item in repetition_records)
    title_pattern_result = evaluate_title_pattern_diversity(article_records)
    structure_pattern_result = evaluate_structure_pattern_diversity(article_records)
    duplicate_title_result = evaluate_title_uniqueness(article_records)
    text_passed = max_intro < 0.72 and max_summary < 0.72 and max_h2 < 0.78
    passed = (
        text_passed
        and image_backgrounds_unique
        and intra_article_repetition_ok
        and bool(duplicate_title_result.get("passed"))
        and bool(title_pattern_result.get("passed"))
        and bool(structure_pattern_result.get("passed"))
    )
    return {
        "status": "ok" if article_records else "no_articles",
        "passed": passed if article_records else False,
        "article_count": len(article_records),
        "max_intro_similarity": max_intro,
        "max_summary_similarity": max_summary,
        "max_h2_similarity": max_h2,
        "image_backgrounds_unique": image_backgrounds_unique,
        "intra_article_repetition_ok": intra_article_repetition_ok,
        "title_uniqueness_ok": bool(duplicate_title_result.get("passed")),
        "title_pattern_diversity_ok": bool(title_pattern_result.get("passed")),
        "structure_pattern_diversity_ok": bool(structure_pattern_result.get("passed")),
        "title_uniqueness": duplicate_title_result,
        "title_pattern_diversity": title_pattern_result,
        "structure_pattern_diversity": structure_pattern_result,
        "duplicate_photo_source_pairs": duplicate_photo_source_pairs,
        "thresholds": {
            "intro_similarity_lt": 0.72,
            "summary_similarity_lt": 0.72,
            "h2_similarity_lt": 0.78,
            "image_backgrounds_unique": True,
            "intra_article_repetition_ok": True,
            "article_titles_unique": True,
            "all_titles_must_not_contain_chusho_kigyo": True,
            "all_penultimate_headings_must_not_be_checklists": True,
            "generic_template_heading_forbidden": [
                "導入前チェックリスト",
                "申請前のチェックリスト",
                "実務チェックリスト",
                "導入時のチェックリスト",
                "対応前チェックリスト",
                "確認チェックリスト",
            ],
        },
        "comparisons": comparisons,
        "articles": article_records,
        "image_sources": image_records,
        "intra_article_repetition": repetition_records,
    }


def evaluate_title_uniqueness(article_records: list[dict[str, object]]) -> dict[str, object]:
    titles = [str(record.get("title") or "") for record in article_records]
    counts = Counter(titles)
    duplicates = [title for title, count in counts.items() if title and count >= 2]
    return {
        "passed": not duplicates,
        "duplicates": duplicates,
        "titles": titles,
    }


def evaluate_title_pattern_diversity(article_records: list[dict[str, object]]) -> dict[str, object]:
    titles = [str(record.get("title") or "") for record in article_records]
    titles_with_chusho = [title for title in titles if "中小企業" in title]
    repeated_patterns = [
        title
        for title in titles
        if any(pattern in title for pattern in ("中小企業が確認したい", "中小企業が見直したい", "中小企業が押さえたい"))
    ]
    all_titles_contain_chusho = len(titles) >= 2 and len(titles_with_chusho) == len(titles)
    all_titles_use_repeated_pattern = len(titles) >= 2 and len(repeated_patterns) == len(titles)
    repeated_pattern_overused = len(titles) >= 3 and len(repeated_patterns) >= 2
    return {
        "passed": not all_titles_contain_chusho and not all_titles_use_repeated_pattern and not repeated_pattern_overused,
        "titles": titles,
        "titles_with_chusho_count": len(titles_with_chusho),
        "repeated_chusho_pattern_count": len(repeated_patterns),
        "all_titles_contain_chusho": all_titles_contain_chusho,
        "all_titles_use_repeated_pattern": all_titles_use_repeated_pattern,
        "repeated_pattern_overused": repeated_pattern_overused,
    }


def evaluate_structure_pattern_diversity(article_records: list[dict[str, object]]) -> dict[str, object]:
    generic_template_headings = {
        "導入前チェックリスト",
        "申請前のチェックリスト",
        "実務チェックリスト",
        "導入時のチェックリスト",
        "対応前チェックリスト",
        "確認チェックリスト",
    }
    generic_heading_records: list[dict[str, object]] = []
    penultimate_checklist_records: list[dict[str, object]] = []
    for record in article_records:
        h2s = record.get("h2s") if isinstance(record.get("h2s"), list) else []
        generic_headings = [heading for heading in h2s if str(heading) in generic_template_headings]
        if generic_headings:
            generic_heading_records.append(
                {
                    "item_index": record.get("item_index"),
                    "title": record.get("title"),
                    "headings": generic_headings,
                }
            )
        if len(h2s) >= 2 and str(h2s[-2]).endswith("チェックリスト"):
            penultimate_checklist_records.append(
                {
                    "item_index": record.get("item_index"),
                    "title": record.get("title"),
                    "heading": h2s[-2],
                }
            )
    all_penultimate_are_checklists = (
        len(article_records) >= 2 and len(penultimate_checklist_records) == len(article_records)
    )
    penultimate_checklists_overused = len(article_records) >= 3 and len(penultimate_checklist_records) >= 2
    return {
        "passed": not generic_heading_records and not all_penultimate_are_checklists and not penultimate_checklists_overused,
        "generic_heading_records": generic_heading_records,
        "penultimate_checklist_records": penultimate_checklist_records,
        "all_penultimate_are_checklists": all_penultimate_are_checklists,
        "penultimate_checklists_overused": penultimate_checklists_overused,
    }


def image_source_record(item: dict[str, object]) -> dict[str, object]:
    image_plan = item.get("featured_image_plan", {}) if isinstance(item.get("featured_image_plan"), dict) else {}
    base_image = image_plan.get("base_image", {}) if isinstance(image_plan.get("base_image"), dict) else {}
    source_path_text = base_image.get("source_path")
    if not isinstance(source_path_text, str) or not source_path_text.strip():
        return {}
    source_path = PROJECT_ROOT / source_path_text.strip()
    digest = ""
    if source_path.exists() and source_path.is_file():
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    return {
        "item_index": item.get("item_index"),
        "article_title": (
            item.get("wordpress_payload", {}).get("wordpress", {}).get("title")
            if isinstance(item.get("wordpress_payload"), dict)
            and isinstance(item.get("wordpress_payload", {}).get("wordpress"), dict)
            else None
        ),
        "source_path": source_path_text.strip(),
        "source_digest": digest,
        "base_status": base_image.get("status"),
    }


def duplicate_image_source_pairs(image_records: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: dict[str, dict[str, object]] = {}
    duplicates: list[dict[str, object]] = []
    for record in image_records:
        digest = str(record.get("source_digest") or "")
        if not digest:
            continue
        if digest in seen:
            duplicates.append(
                {
                    "left_item": seen[digest].get("item_index"),
                    "right_item": record.get("item_index"),
                    "left_source_path": seen[digest].get("source_path"),
                    "right_source_path": record.get("source_path"),
                    "source_digest": digest,
                }
            )
        else:
            seen[digest] = record
    return duplicates


def extract_article_title(markdown: str) -> str:
    match = re.search(r"^# (.+)$", markdown, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def extract_h2_section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", flags=re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""
    next_h2 = re.search(r"^## .+$", markdown[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_h2.start() if next_h2 else len(markdown)
    section = markdown[match.end() : end]
    return re.sub(r"\s+", " ", section).strip()


def text_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", "", left)
    right_norm = re.sub(r"\s+", "", right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def snapshot_latest_outputs(item_index: int) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for key, path in LATEST_OUTPUTS.items():
        if not path.exists():
            continue
        destination = path.with_name(path.name.replace("_latest", f"_item_{item_index}"))
        copy2(path, destination)
        outputs[key] = relative_path(destination)
    return outputs


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def render_article_batch(batch: dict[str, object]) -> str:
    lines = [
        "# 生成記事バッチ",
        "",
        f"- ステータス: {batch.get('status')}",
        f"- 要求件数: {batch.get('requested_count')}",
        f"- 生成件数: {batch.get('generated_count')}",
        "",
        "## バッチ品質",
        "",
    ]
    batch_quality = batch.get("batch_quality", {}) if isinstance(batch.get("batch_quality"), dict) else {}
    lines.extend(
        [
            f"- 3記事類似チェック: {'OK' if batch_quality.get('passed') else '要確認'}",
            f"- はじめに最大類似度: {batch_quality.get('max_intro_similarity')}",
            f"- まとめ最大類似度: {batch_quality.get('max_summary_similarity')}",
            f"- H2構成最大類似度: {batch_quality.get('max_h2_similarity')}",
            f"- アイキャッチ背景重複: {'なし' if batch_quality.get('image_backgrounds_unique') else 'あり'}",
            f"- タイトル重複: {'なし' if batch_quality.get('title_uniqueness_ok') else 'あり'}",
            f"- タイトル型の偏り: {'なし' if batch_quality.get('title_pattern_diversity_ok') else 'あり'}",
            f"- 構成型の偏り: {'なし' if batch_quality.get('structure_pattern_diversity_ok') else 'あり'}",
            "",
            "## 生成記事",
            "",
        ]
    )
    for item in batch.get("items", []):
        if not isinstance(item, dict):
            continue
        selected = item.get("selected", {}) if isinstance(item.get("selected"), dict) else {}
        quality = item.get("quality_check", {}) if isinstance(item.get("quality_check"), dict) else {}
        wordpress_payload = item.get("wordpress_payload", {}) if isinstance(item.get("wordpress_payload"), dict) else {}
        wordpress = wordpress_payload.get("wordpress", {}) if isinstance(wordpress_payload.get("wordpress"), dict) else {}
        review = item.get("review_text", {}) if isinstance(item.get("review_text"), dict) else {}
        lines.extend(
            [
                f"### {item.get('item_index')}件目",
                "",
                f"- テーマ: {selected.get('topic_title')}",
                f"- 人事労務だより: {selected.get('pdf_name')}",
                f"- 掲載箇所/分類: {selected.get('section_group')}",
                f"- 記事タイトル: {wordpress.get('title')}",
                f"- 下書き品質: {quality.get('draft_quality_passed')}",
                f"- 未確認ファクト: {quality.get('unverified_fact_count')}",
                f"- WordPress送信可能: {wordpress_payload.get('ready_to_send')}",
                f"- WordPress日付: {wordpress.get('date')}",
                f"- 確認用テキスト: {review.get('file_name')}",
                "",
            ]
        )
    return "\n".join(lines)


def render_article_batch_quality(result: dict[str, object]) -> str:
    lines = [
        "# 3記事バッチ品質チェック",
        "",
        f"- ステータス: {result.get('status')}",
        f"- 判定: {'OK' if result.get('passed') else '要確認'}",
        f"- 記事件数: {result.get('article_count')}",
        f"- はじめに最大類似度: {result.get('max_intro_similarity')}",
        f"- まとめ最大類似度: {result.get('max_summary_similarity')}",
        f"- H2構成最大類似度: {result.get('max_h2_similarity')}",
            f"- アイキャッチ背景重複: {'なし' if result.get('image_backgrounds_unique') else 'あり'}",
            f"- 同一記事内の段落反復: {'なし' if result.get('intra_article_repetition_ok') else 'あり'}",
            f"- タイトル重複: {'なし' if result.get('title_uniqueness_ok') else 'あり'}",
            f"- タイトル型の偏り: {'なし' if result.get('title_pattern_diversity_ok') else 'あり'}",
            f"- 構成型の偏り: {'なし' if result.get('structure_pattern_diversity_ok') else 'あり'}",
            "",
        "## 比較結果",
        "",
    ]
    for row in result.get("comparisons", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('left_item')}件目 vs {row.get('right_item')}件目: "
            f"intro {row.get('intro_similarity')}, summary {row.get('summary_similarity')}, h2 {row.get('h2_similarity')}"
        )
    duplicate_pairs = result.get("duplicate_photo_source_pairs", [])
    if duplicate_pairs:
        lines.extend(["", "## アイキャッチ背景重複", ""])
        for row in duplicate_pairs:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('left_item')}件目 vs {row.get('right_item')}件目: "
                f"{row.get('left_source_path')} / {row.get('right_source_path')}"
            )
    repetition_records = result.get("intra_article_repetition", [])
    bad_repetition_records = [
        row for row in repetition_records if isinstance(row, dict) and row.get("has_repetition")
    ] if isinstance(repetition_records, list) else []
    if bad_repetition_records:
        lines.extend(["", "## 同一記事内の段落反復", ""])
        for row in bad_repetition_records:
            lines.append(f"- {row.get('item_index')}件目: {row.get('path')}")
            repeated_paragraphs = (
                row.get("repeated_paragraphs", []) if isinstance(row.get("repeated_paragraphs"), list) else []
            )
            repeated_openings = (
                row.get("repeated_openings", []) if isinstance(row.get("repeated_openings"), list) else []
            )
            for item in repeated_paragraphs:
                if isinstance(item, dict):
                    lines.append(f"  - 段落 {item.get('count')}回: {item.get('sample')}")
            for item in repeated_openings:
                if isinstance(item, dict):
                    lines.append(f"  - 文頭 {item.get('count')}回: {item.get('opening')}")
    title_uniqueness = result.get("title_uniqueness") if isinstance(result.get("title_uniqueness"), dict) else {}
    if title_uniqueness and not title_uniqueness.get("passed"):
        lines.extend(["", "## タイトル重複", ""])
        for title in title_uniqueness.get("duplicates", []):
            lines.append(f"- {title}")
    title_pattern = result.get("title_pattern_diversity") if isinstance(result.get("title_pattern_diversity"), dict) else {}
    if title_pattern and not title_pattern.get("passed"):
        lines.extend(["", "## タイトル型の偏り", ""])
        lines.append(f"- 全タイトルに中小企業を含む: {title_pattern.get('all_titles_contain_chusho')}")
        lines.append(f"- 全タイトルが定型句を使う: {title_pattern.get('all_titles_use_repeated_pattern')}")
        lines.append(f"- 定型句が2件以上: {title_pattern.get('repeated_pattern_overused')}")
        for title in title_pattern.get("titles", []):
            lines.append(f"- {title}")
    structure_pattern = (
        result.get("structure_pattern_diversity")
        if isinstance(result.get("structure_pattern_diversity"), dict)
        else {}
    )
    if structure_pattern and not structure_pattern.get("passed"):
        lines.extend(["", "## 構成型の偏り", ""])
        if structure_pattern.get("generic_heading_records"):
            lines.append("- 汎用テンプレート見出しが含まれています。")
        if structure_pattern.get("all_penultimate_are_checklists"):
            lines.append("- 全記事で、まとめ直前のH2がチェックリスト型になっています。")
        if structure_pattern.get("penultimate_checklists_overused"):
            lines.append("- 3件中2件以上で、まとめ直前のH2がチェックリスト型になっています。")
        for row in structure_pattern.get("penultimate_checklist_records", []):
            if isinstance(row, dict):
                lines.append(f"- {row.get('item_index')}件目: {row.get('heading')}")
    return "\n".join(lines)


def run() -> dict[str, object]:
    ensure_output_dirs()
    ensure_state_files()
    drive_status = build_drive_status()
    settings_count = load_articles_per_run()
    results: dict[str, object] = {
        "gsc": analyze_gsc(),
        "posted_articles": analyze_posted_articles(),
        "ga": analyze_ga(),
        "prompts": analyze_prompts(),
        "drive_status": drive_status,
    }
    results["posted_article_topics"] = classify_posted_article_topics()
    results["ga_insights"] = build_ga_insights()
    results["newsletters"], results["topic_selection"] = select_newsletter_and_score_until_viable(
        required_count=settings_count
    )
    results["articles"] = build_article_batch(results, settings_count)
    first_item = next(
        (item for item in results["articles"].get("items", []) if isinstance(item, dict)),
        {},
    )
    for key in (
        "article_brief",
        "source_plan",
        "article_outline",
        "article_draft",
        "fact_check",
        "quality_check",
        "review_text",
        "featured_image_plan",
        "wordpress_payload",
    ):
        if isinstance(first_item, dict):
            results[key] = first_item.get(key, {})
    results["wordpress_status"] = build_wordpress_status()
    results["automation_status"] = update_automation_status(results)
    write_json(SEO_ANALYSIS_DIR / "initial_analysis_summary.json", results)
    write_markdown(SEO_ANALYSIS_DIR / "initial_analysis_report.md", build_markdown_report(results))
    return results


def load_articles_per_run() -> int:
    try:
        from .paths import CONFIG_DIR

        settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
        return max(1, int(settings.get("articles_per_run") or 3))
    except Exception:
        return 3


def select_newsletter_and_score_until_viable(required_count: int) -> tuple[dict[str, object], dict[str, object]]:
    excluded: set[str] = set()
    attempts: list[dict[str, object]] = []
    final_newsletters: dict[str, object] = {}
    final_topic_selection: dict[str, object] = {}

    while True:
        newsletters = analyze_newsletters(excluded_issue_names=excluded)
        topic_selection = score_topics()
        rows = read_csv_dicts(TOPIC_SELECTION_DIR / "topic_selection_scores.csv")
        selected_preview = select_recommended_topics(rows, limit=required_count)
        issue_selection = (
            newsletters.get("issue_selection", {}) if isinstance(newsletters.get("issue_selection"), dict) else {}
        )
        selected_pdf = str(issue_selection.get("selected_pdf_name") or "")
        attempt = {
            "pdf_name": selected_pdf or None,
            "period_key": issue_selection.get("selected_period_key"),
            "status": issue_selection.get("status"),
            "viable_topic_count": len(selected_preview),
            "required_count": required_count,
        }
        attempts.append(attempt)
        final_newsletters = newsletters
        final_topic_selection = topic_selection

        if issue_selection.get("status") == "all_issues_completed":
            break
        if len(selected_preview) >= required_count:
            break
        if not selected_pdf or selected_pdf in excluded:
            break
        excluded.add(selected_pdf)

    issue_selection = final_newsletters.get("issue_selection", {})
    if isinstance(issue_selection, dict):
        issue_selection["viability_attempts"] = attempts
        issue_selection["skipped_insufficient_issues"] = [
            item for item in attempts[:-1] if int(item.get("viable_topic_count") or 0) < required_count
        ]
    final_newsletters["issue_selection"] = issue_selection
    summaries_path = TOPIC_SELECTION_DIR / "newsletter_pdf_summaries.json"
    summaries = read_json(summaries_path, {}) or {}
    if isinstance(summaries, dict):
        summaries["issue_selection"] = issue_selection
        write_json(summaries_path, summaries)
    return final_newsletters, final_topic_selection
