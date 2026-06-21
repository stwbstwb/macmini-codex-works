from __future__ import annotations

import math
import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from random import Random

from .io_utils import read_csv_dicts, read_json, to_float, to_int, write_csv_dicts, write_markdown
from .paths import CANNIBALIZATION_DIR, SEO_ANALYSIS_DIR, STATE_DIR, TOPIC_SELECTION_DIR
from .state_manager import stable_key, used_topic_keys


STOPWORDS = {
    "について",
    "ため",
    "こと",
    "よう",
    "する",
    "ます",
    "です",
    "もの",
    "これ",
    "それ",
    "など",
    "および",
    "また",
    "から",
    "まで",
    "企業",
    "労働者",
}

PRACTICAL_KEYWORDS = {
    "義務": 3,
    "施行": 3,
    "改正": 3,
    "中小企業": 3,
    "就業規則": 3,
    "助成金": 3,
    "奨励金": 2,
    "ハラスメント": 3,
    "ストレスチェック": 3,
    "社会保険": 2,
    "雇用保険": 2,
    "労働時間": 2,
    "賃金": 2,
    "パート": 2,
    "有期": 2,
    "育児": 2,
    "介護": 2,
    "安全衛生": 2,
}

DOMAIN_PHRASES = [
    "同一労働同一賃金",
    "同一賃金ガイドライン",
    "女性活躍推進法",
    "一般事業主行動計画",
    "65歳超雇用推進助成金",
    "高年齢者評価制度",
    "パート",
    "有期",
    "人材開発支援助成金",
    "両立支援等助成金",
    "育児介護休業法",
    "カスタマーハラスメント",
    "カスハラ",
    "ストレスチェック",
    "労働時間",
    "働き方改革",
    "在職老齢年金",
    "現物給与",
    "障害者雇用率",
    "労働安全衛生法",
    "労働者死傷病報告",
]

LABEL_WEIGHTS = {
    "law_change": 5,
    "subsidy": 4,
    "labor_management": 4,
    "news": -3,
}

REGIONAL_TERMS = {
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
}

PREFERRED_SECTION_TERMS = (
    "最新・行政の動き",
    "助成金情報",
    "調査",
    "実務に役立つ",
    "身近な労働法",
    "今月の実務チェックポイント",
)

OUT_OF_SCOPE_TERMS = {
    "法人税",
    "消費税",
    "地方消費税",
    "法人事業税",
    "戸籍",
    "振り仮名",
    "ふりがな",
    "特定技能",
    "今月の業務スケジュール",
    "業務スケジュール",
    "システム整備",
    "医療保険者等",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def extract_terms(text: str) -> list[str]:
    terms = re.findall(r"[一-龥ぁ-んァ-ヶA-Za-z0-9ー]{2,}", text)
    normalized: list[str] = []
    for term in terms:
        cleaned = term.strip().lower()
        if cleaned in STOPWORDS:
            continue
        if len(cleaned) < 2:
            continue
        normalized.append(cleaned)
    return list(dict.fromkeys(normalized))


def keyword_overlap_score(source_terms: list[str], target_text: str) -> int:
    target = normalize(target_text)
    score = 0
    for term in source_terms:
        if len(term) >= 3 and normalize(term) in target:
            score += 1
    return score


def estimate_freshness(pdf_name: str) -> int:
    match = re.search(r"(\d{4})\.(\d{1,2})", pdf_name)
    if not match:
        return 0
    year = int(match.group(1))
    month = int(match.group(2))
    return (year - 2024) * 12 + month


def domain_phrase_similarity(candidate_text: str, article_title: str) -> float:
    candidate = normalize(candidate_text)
    title = normalize(article_title)
    matches = [phrase for phrase in DOMAIN_PHRASES if normalize(phrase) in candidate and normalize(phrase) in title]
    if not matches:
        return 0.0
    strong_matches = [phrase for phrase in matches if len(phrase) >= 6]
    if strong_matches:
        return min(0.82, 0.55 + 0.12 * len(strong_matches))
    return min(0.48, 0.22 * len(matches))


def find_nearest_article(candidate_text: str, posted_articles: list[dict[str, str]]) -> tuple[str, str, float]:
    candidate_norm = normalize(candidate_text)
    best_title = ""
    best_url = ""
    best_ratio = 0.0
    for article in posted_articles:
        title = article.get("title") or article.get("Title") or ""
        url = article.get("url") or article.get("URL") or ""
        text_ratio = SequenceMatcher(None, candidate_norm, normalize(title)).ratio()
        phrase_ratio = domain_phrase_similarity(candidate_text, title)
        ratio = max(text_ratio, phrase_ratio)
        if ratio > best_ratio:
            best_title = title
            best_url = url
            best_ratio = ratio
    return best_title, best_url, best_ratio


def gsc_demand_score(terms: list[str], gsc_queries: list[dict[str, str]]) -> tuple[int, int, int, str]:
    matched_queries: list[tuple[str, int, int]] = []
    for row in gsc_queries:
        query = row.get("dimension") or row.get("上位のクエリ") or ""
        overlap = keyword_overlap_score(terms, query)
        if overlap <= 0:
            continue
        impressions = to_int(row.get("impressions") or row.get("表示回数"))
        clicks = to_int(row.get("clicks") or row.get("クリック数"))
        if impressions <= 0:
            continue
        matched_queries.append((query, impressions, clicks))

    matched_queries.sort(key=lambda item: item[1], reverse=True)
    total_impressions = sum(item[1] for item in matched_queries[:20])
    total_clicks = sum(item[2] for item in matched_queries[:20])
    score = int(min(12, math.log10(total_impressions + 1) * 3)) if total_impressions else 0
    sample = " / ".join(item[0] for item in matched_queries[:5])
    return score, total_impressions, total_clicks, sample


def practical_score(text: str, labels: str) -> int:
    score = 0
    for label in labels.split(","):
        score += LABEL_WEIGHTS.get(label.strip(), 0)
    for keyword, weight in PRACTICAL_KEYWORDS.items():
        if keyword in text:
            score += weight
    return score


def editorial_policy_score(candidate: dict[str, str], labels: str) -> tuple[int, bool, str]:
    section = str(candidate.get("section_group") or "")
    title = str(candidate.get("topic_title") or "")
    excerpt = str(candidate.get("excerpt") or "")
    text = f"{section} {title} {excerpt}"
    reasons: list[str] = []
    penalty = 0

    if "ニュース" in section:
        penalty += 60
        reasons.append("ニュース区分のため原則除外")

    if "調査" in section and "調査" in text:
        penalty += 14
        reasons.append("調査数値の一次情報確認負荷が高いため法制度テーマを優先")

    if title.startswith("") or title.startswith("・"):
        penalty += 40
        reasons.append("PDF抽出断片のため記事タイトル化に不向き")

    if "不正受給" in title and "news" in {label.strip() for label in labels.split(",") if label.strip()}:
        penalty += 18
        reasons.append("ニュース性が強く既存助成金記事との重複懸念")

    regional_hits = [term for term in REGIONAL_TERMS if term in text]
    labor_bureau_hits = re.findall(r"[一-龥]{2,6}労働局|[一-龥]{2,6}労基署", text)
    if regional_hits or labor_bureau_hits:
        penalty += 45
        hit = "、".join((regional_hits + labor_bureau_hits)[:3])
        reasons.append(f"地域限定性が強い素材（{hit}）")

    if "news" in {label.strip() for label in labels.split(",") if label.strip()} and not any(
        term in section for term in PREFERRED_SECTION_TERMS
    ):
        penalty += 8
        reasons.append("ニュース性が強くSEO記事化の優先度を下げる")

    out_of_scope_hits = [term for term in OUT_OF_SCOPE_TERMS if term in text]
    if out_of_scope_hits:
        penalty += 50
        reasons.append(f"人事労務SEOの主軸から外れる素材（{'、'.join(out_of_scope_hits[:3])}）")

    seo_fit = penalty < 40
    if not reasons:
        reasons.append("SEO記事化しやすい実務テーマ")
    return penalty, seo_fit, " / ".join(reasons)


def cannibalization_penalty(candidate_text: str, posted_articles: list[dict[str, str]]) -> tuple[int, str, str, float]:
    nearest_title, nearest_url, similarity = find_nearest_article(candidate_text, posted_articles)
    if similarity >= 0.62:
        return 12, nearest_title, nearest_url, similarity
    if similarity >= 0.48:
        return 7, nearest_title, nearest_url, similarity
    if similarity >= 0.36:
        return 3, nearest_title, nearest_url, similarity
    return 0, nearest_title, nearest_url, similarity


def cannibalization_allows_selection(row: dict[str, object]) -> bool:
    penalty = int(row.get("cannibalization_penalty") or 0)
    if penalty < 12:
        return True
    if penalty == 12 and is_policy_change_topic(row):
        return True
    return False


def is_policy_change_topic(row: dict[str, object]) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("topic_title", "section_group", "labels", "excerpt"))
    return any(
        term in text
        for term in (
            "同一賃金ガイドライン",
            "同一労働同一賃金ガイドライン",
            "女性活躍推進法",
            "一般事業主行動計画",
            "65歳超雇用推進助成金",
            "65 歳超雇用推進助成金",
            "高年齢者評価制度",
        )
    )


def score_topics() -> dict[str, object]:
    candidates = read_csv_dicts(TOPIC_SELECTION_DIR / "newsletter_topic_candidates.csv")
    posted_articles = read_csv_dicts(CANNIBALIZATION_DIR / "posted_articles_inventory.csv")
    gsc_queries = read_csv_dicts(SEO_ANALYSIS_DIR / "gsc_top_queries.csv")
    topic_history = read_json(STATE_DIR / "topic_history.json", {"items": []}) or {"items": []}
    used_keys = used_topic_keys(topic_history)

    rows: list[dict[str, object]] = []
    for candidate in candidates:
        text = f"{candidate.get('topic_title', '')} {candidate.get('excerpt', '')}"
        labels = candidate.get("labels", "")
        terms = extract_terms(text)
        demand_score, impressions, clicks, matched_queries = gsc_demand_score(terms, gsc_queries)
        impact_score = practical_score(text, labels)
        freshness = min(8, max(0, estimate_freshness(candidate.get("pdf_name", "")) - 12))
        base_score = to_int(candidate.get("score"))
        penalty, nearest_title, nearest_url, similarity = cannibalization_penalty(text, posted_articles)
        editorial_penalty, seo_article_fit, editorial_reason = editorial_policy_score(candidate, labels)
        topic_key = stable_key(candidate.get("pdf_name"), candidate.get("section_group"), candidate.get("topic_title"))
        history_penalty = 20 if topic_key in used_keys else 0
        final_score = base_score + demand_score + impact_score + freshness - penalty - history_penalty - editorial_penalty

        rows.append(
            {
                "topic_key": topic_key,
                "final_score": final_score,
                "base_pdf_score": base_score,
                "seo_demand_score": demand_score,
                "practical_impact_score": impact_score,
                "freshness_score": freshness,
                "cannibalization_penalty": penalty,
                "history_penalty": history_penalty,
                "editorial_policy_penalty": editorial_penalty,
                "seo_article_fit": str(seo_article_fit).lower(),
                "editorial_policy_reason": editorial_reason,
                "nearest_similarity": round(similarity, 3),
                "nearest_article_title": nearest_title,
                "nearest_article_url": nearest_url,
                "matched_gsc_impressions": impressions,
                "matched_gsc_clicks": clicks,
                "matched_gsc_queries": matched_queries,
                "pdf_name": candidate.get("pdf_name", ""),
                "section_group": candidate.get("section_group", ""),
                "topic_title": candidate.get("topic_title", ""),
                "labels": labels,
                "date_mentions": candidate.get("date_mentions", ""),
                "excerpt": candidate.get("excerpt", ""),
            }
        )

    rows.sort(key=lambda row: int(row["final_score"]), reverse=True)
    fields = [
        "final_score",
        "topic_key",
        "base_pdf_score",
        "seo_demand_score",
        "practical_impact_score",
        "freshness_score",
        "cannibalization_penalty",
        "history_penalty",
        "editorial_policy_penalty",
        "seo_article_fit",
        "editorial_policy_reason",
        "nearest_similarity",
        "nearest_article_title",
        "nearest_article_url",
        "matched_gsc_impressions",
        "matched_gsc_clicks",
        "matched_gsc_queries",
        "pdf_name",
        "section_group",
        "topic_title",
        "labels",
        "date_mentions",
        "excerpt",
    ]
    write_csv_dicts(TOPIC_SELECTION_DIR / "topic_selection_scores.csv", rows, fields)
    write_markdown(TOPIC_SELECTION_DIR / "topic_selection_report.md", build_topic_selection_report(rows))

    return {
        "scored_topic_count": len(rows),
        "top_topics": rows[:10],
        "past_fallback_candidate": choose_past_fallback(rows),
    }


def choose_past_fallback(rows: list[dict[str, object]]) -> dict[str, object] | None:
    if not rows:
        return None
    latest_period = max(estimate_freshness(str(row.get("pdf_name", ""))) for row in rows)
    older = [
        row
        for row in rows
        if estimate_freshness(str(row.get("pdf_name", ""))) < latest_period
        and cannibalization_allows_selection(row)
        and int(row.get("history_penalty") or 0) == 0
        and str(row.get("seo_article_fit", "")).lower() != "false"
    ]
    if not older:
        return None
    seed = int(date.today().strftime("%Y%m"))
    return Random(seed).choice(older[:20])


def build_topic_selection_report(rows: list[dict[str, object]]) -> str:
    lines = [
        "# テーマ選定スコアレポート",
        "",
        "PDF候補に、SEO需要・中小企業への実務影響・鮮度・過去記事との重複リスクを加味した初期スコアです。",
        "",
        "## 上位候補",
        "",
    ]
    for index, row in enumerate(rows[:10], 1):
        lines.extend(
            [
                f"### {index}. {row['topic_title']}",
                "",
                f"- 最終スコア: {row['final_score']}",
                f"- PDF: {row['pdf_name']} / {row['section_group']}",
                f"- ラベル: {row['labels']}",
                f"- 履歴減点: {row.get('history_penalty', 0)}",
                f"- 編集方針減点: {row.get('editorial_policy_penalty', 0)}",
                f"- SEO記事適性: {row.get('seo_article_fit', '')}",
                f"- 編集方針メモ: {row.get('editorial_policy_reason', '')}",
                f"- SEO一致クエリ: {row['matched_gsc_queries'] or 'なし'}",
                f"- 類似記事: {row['nearest_article_title'] or 'なし'}",
                f"- 類似度: {row['nearest_similarity']}",
                f"- 抜粋: {row['excerpt']}",
                "",
            ]
        )
    return "\n".join(lines)
