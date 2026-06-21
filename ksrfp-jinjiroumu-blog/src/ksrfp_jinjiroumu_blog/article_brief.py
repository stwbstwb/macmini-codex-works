from __future__ import annotations

from datetime import datetime
import re

from .io_utils import read_csv_dicts, read_json, write_json, write_markdown
from .paths import GENERATED_DIR, TOPIC_SELECTION_DIR


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


def select_recommended_topic(rows: list[dict[str, str]]) -> dict[str, str] | None:
    topics = select_recommended_topics(rows, limit=1)
    return topics[0] if topics else None


def select_current_or_recommended_topic(rows: list[dict[str, str]]) -> dict[str, str] | None:
    current = selected_topic_from_current_brief()
    if current and cannibalization_allows_selection(current) and is_editorially_fit(current):
        return current
    return select_recommended_topic(rows)


def select_recommended_topics(rows: list[dict[str, str]], limit: int = 3) -> list[dict[str, str]]:
    latest_period = latest_pdf_period(rows)
    latest_viable = [
        row
        for row in rows
        if pdf_period(row.get("pdf_name", "")) == latest_period
        and cannibalization_allows_selection(row)
        and int(row.get("history_penalty") or 0) < 20
        and is_editorially_fit(row)
        and selection_priority_score(row) >= 10
    ]
    latest_viable.sort(key=selection_priority_score, reverse=True)
    selected: list[dict[str, str]] = []
    used_keys: set[str] = set()
    used_sections: set[str] = set()
    used_families: set[str] = set()

    def add(row: dict[str, str], reason: str) -> None:
        if len(selected) >= limit:
            return
        key = row.get("topic_key") or f"{row.get('pdf_name')}|{row.get('section_group')}|{row.get('topic_title')}"
        if key in used_keys:
            return
        copied = dict(row)
        copied["selection_reason"] = reason
        selected.append(copied)
        used_keys.add(key)
        if copied.get("section_group"):
            used_sections.add(str(copied.get("section_group")))
        family = topic_family_key(copied)
        if family:
            used_families.add(family)

    for row in latest_viable:
        section = str(row.get("section_group") or "")
        if section and section in used_sections:
            continue
        family = topic_family_key(row)
        if family and family in used_families:
            continue
        add(row, "latest_pdf_viable_topic_diverse_section")

    for row in latest_viable:
        family = topic_family_key(row)
        if family and family in used_families:
            continue
        add(row, "latest_pdf_viable_topic")

    for row in rows:
        history_penalty = int(row.get("history_penalty") or 0)
        if cannibalization_allows_selection(row) and history_penalty < 20 and is_editorially_fit(row) and selection_priority_score(row) >= 8:
            family = topic_family_key(row)
            if family and family in used_families:
                continue
            add(row, "past_or_alternative_viable_topic")

    for row in rows:
        history_penalty = int(row.get("history_penalty") or 0)
        if cannibalization_allows_selection(row) and history_penalty < 20 and is_editorially_fit(row):
            add(row, "strict_fallback_topic")
    return selected[:limit]


def topic_family_key(row: dict[str, str]) -> str:
    text = " ".join(str(row.get(key) or "") for key in ("topic_title", "section_group", "labels", "excerpt"))
    family_rules = [
        ("human_resource_development_subsidy", ("人材開発支援助成金", "人材開発助成金", "リスキリング", "教育訓練休暇", "人への投資促進")),
        ("trial_employment_subsidy", ("トライアル雇用", "一般トライアル")),
        ("senior_employment_subsidy", ("65歳超雇用推進助成金", "高年齢者評価制度")),
        ("childcare_support_contribution", ("子ども・子育て支援金",)),
        ("childcare_leave_benefit", ("出生時育児休業給付金", "産後パパ育休", "育児休業給付")),
        ("equal_pay", ("同一労働同一賃金", "同一賃金ガイドライン", "パート・有期")),
        ("women_action_plan", ("女性活躍推進法", "一般事業主行動計画", "男女間賃金差異")),
        ("fixed_term_conversion", ("無期転換", "有期労働契約")),
        ("working_hours", ("労働時間", "36協定", "働き方改革")),
        ("mental_health", ("ストレスチェック", "メンタルヘルス")),
        ("occupational_safety", ("労働災害", "安全衛生", "高年齢者")),
        ("payroll_housing", ("社宅", "現物給与")),
    ]
    for family, keywords in family_rules:
        if any(keyword in text for keyword in keywords):
            return family
    return ""


def is_editorially_fit(row: dict[str, str]) -> bool:
    return not source_policy_violations(row)


def source_policy_violations(row: dict[str, str]) -> list[str]:
    violations: list[str] = []
    if str(row.get("seo_article_fit", "")).lower() == "false":
        violations.append("seo_article_fit=false")
    if int(row.get("editorial_policy_penalty") or 0) >= 40:
        violations.append("editorial_policy_penalty>=40")
    section = str(row.get("section_group") or "")
    if "ニュース" in section:
        violations.append("news_section")
    text = " ".join(str(row.get(key) or "") for key in ("topic_title", "section_group", "labels", "excerpt"))
    regional_hits = sorted(term for term in REGIONAL_TERMS if term in text)
    labor_bureau_hits = re.findall(r"[一-龥]{2,6}労働局|[一-龥]{2,6}労基署", text)
    if regional_hits or labor_bureau_hits:
        violations.append(
            "regional_or_local_labor_office:"
            + "、".join((regional_hits + labor_bureau_hits)[:3])
        )
    out_of_scope_hits = sorted(term for term in OUT_OF_SCOPE_TERMS if term in text)
    if out_of_scope_hits:
        violations.append("out_of_scope:" + "、".join(out_of_scope_hits[:3]))
    return violations


def cannibalization_allows_selection(row: dict[str, str]) -> bool:
    penalty = int(row.get("cannibalization_penalty") or 0)
    if penalty < 12:
        return True
    if penalty == 12 and is_policy_change_topic(row):
        return True
    return False


def is_policy_change_topic(row: dict[str, str]) -> bool:
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


def selection_priority_score(row: dict[str, str]) -> int:
    return int(row.get("final_score") or 0) + int(row.get("history_penalty") or 0)


def latest_pdf_period(rows: list[dict[str, str]]) -> str:
    periods = [pdf_period(row.get("pdf_name", "")) for row in rows]
    return max(periods) if periods else "0000-00"


def pdf_period(name: str) -> str:
    match = re.search(r"(20\d{2})\.(\d{1,2})", name)
    if not match:
        return "0000-00"
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def selected_topic_from_current_brief() -> dict[str, str] | None:
    brief = read_json(GENERATED_DIR / "outlines" / "article_brief_latest.json", {}) or {}
    if not isinstance(brief, dict):
        return None
    selected = brief.get("selected")
    return selected if isinstance(selected, dict) else None


def build_article_brief(
    selected_topic: dict[str, str] | None = None,
    alternatives: list[dict[str, str]] | None = None,
    item_index: int | None = None,
    item_total: int | None = None,
) -> dict[str, object]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    rows = read_csv_dicts(TOPIC_SELECTION_DIR / "topic_selection_scores.csv")
    selected = dict(selected_topic) if selected_topic else select_recommended_topic(rows)
    if selected is None:
        result: dict[str, object] = {"status": "no_topic", "generated_at": generated_at}
        write_json(GENERATED_DIR / "outlines" / "article_brief_latest.json", result)
        write_markdown(GENERATED_DIR / "outlines" / "article_brief_latest.md", "# 記事作成ブリーフ\n\n候補テーマがありません。")
        return result

    alternative_rows = alternatives if alternatives is not None else rows[:5]
    result = {
        "status": "ok",
        "generated_at": generated_at,
        "selected": selected,
        "alternatives": alternative_rows,
        "item_index": item_index,
        "item_total": item_total,
    }
    write_json(GENERATED_DIR / "outlines" / "article_brief_latest.json", result)
    write_markdown(
        GENERATED_DIR / "outlines" / "article_brief_latest.md",
        render_brief(selected, alternative_rows, item_index=item_index, item_total=item_total),
    )
    return result


def render_brief(
    selected: dict[str, str],
    alternatives: list[dict[str, str]],
    item_index: int | None = None,
    item_total: int | None = None,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    topic = selected.get("topic_title", "")
    section = selected.get("section_group", "")
    pdf_name = selected.get("pdf_name", "")
    labels = selected.get("labels", "")
    matched_queries = selected.get("matched_gsc_queries", "") or "なし"
    nearest_title = selected.get("nearest_article_title", "") or "なし"
    nearest_url = selected.get("nearest_article_url", "") or "なし"
    similarity = selected.get("nearest_similarity", "")

    title_candidates = build_title_candidates(topic, labels)
    slug = build_slug(topic, labels)
    meta_description = build_meta_description(topic)

    lines = [
        "# 記事作成ブリーフ",
        "",
        f"生成日時: {generated_at}",
        "",
        "## 推奨テーマ",
        "",
        f"- テーマ: {topic}",
        f"- 出典PDF: {pdf_name}",
        f"- PDF内区分: {section}",
        f"- ラベル: {labels}",
        f"- 最終スコア: {selected.get('final_score', '')}",
        f"- カニバリ減点: {selected.get('cannibalization_penalty', '')}",
        f"- 履歴減点: {selected.get('history_penalty', '')}",
        f"- 編集方針減点: {selected.get('editorial_policy_penalty', '')}",
        f"- SEO記事適性: {selected.get('seo_article_fit', '')}",
        f"- 編集方針メモ: {selected.get('editorial_policy_reason', '')}",
        f"- 選定理由: {selected.get('selection_reason', '')}",
        f"- 類似記事: {nearest_title}",
        f"- 類似記事URL: {nearest_url}",
        f"- 類似度: {similarity}",
        f"- GSC一致クエリ: {matched_queries}",
        "",
        "## 記事化の狙い",
        "",
        "中小企業の経営者・人事労務担当者が、制度変更や行政動向を実務に落とし込むための解説記事にする。",
        "単なるニュース紹介ではなく、会社として確認すべき事項、就業規則・社内説明・手続きへの影響を整理する。",
        "ニュース区分や地域限定性が強い素材は原則として記事化候補から外し、全国の中小企業が検索する実務テーマを優先する。",
        "",
        "## 素材抜粋",
        "",
        selected.get("excerpt", ""),
        "",
        "## タイトル案",
        "",
    ]
    if item_index and item_total:
        lines[4:4] = [f"記事候補: {item_index}/{item_total}", ""]
    lines.extend(f"- {title}" for title in title_candidates)
    lines.extend(
        [
            "",
            "## メタ情報案",
            "",
            f"- スラッグ案: `{slug}`",
            f"- メタディスクリプション案: {meta_description}",
            "",
            "## 想定読者",
            "",
            "- 中小企業の経営者",
            "- 人事労務担当者",
            "- パート・有期雇用・労務管理・助成金・法改正対応に関心がある事業所",
            "",
            "## 一次情報確認チェック",
            "",
            "- 厚生労働省、労働局、自治体、年金機構などの公的情報を確認する",
            "- 施行日、適用日、申請期限、対象企業、対象労働者を確認する",
            "- PDF記載内容が最新情報と矛盾していないか確認する",
            "- 地域限定の制度は、全国向け記事にするか地域限定記事にするか判断する",
            "",
            "## カニバリ確認",
            "",
            f"- 最も近い既存記事: {nearest_title}",
            f"- URL: {nearest_url}",
            f"- 類似度: {similarity}",
            "- 類似度が高い場合は、新規記事ではなく既存記事のリライト候補に切り替える。",
            "",
            "## 上位代替候補",
            "",
        ]
    )
    for row in alternatives:
        lines.append(
            f"- {row.get('topic_title', '')}: score {row.get('final_score', '')}, "
            f"cannibalization {row.get('cannibalization_penalty', '')}, "
            f"editorial {row.get('editorial_policy_penalty', '')}, fit {row.get('seo_article_fit', '')}"
        )
    return "\n".join(lines)


def build_title_candidates(topic: str, labels: str) -> list[str]:
    if "65" in topic and "雇用推進助成金" in topic:
        return [
            "65歳超雇用推進助成金の高年齢者雇用管理と申請前の注意点",
            "高年齢者評価制度等雇用管理改善コースの基本と実務チェック",
            "再雇用者の評価・賃金・健康管理を見直す65歳超雇用推進助成金の実務",
        ]
    if "女性活躍推進法" in topic or "一般事業主行動計画" in topic:
        return [
            "女性活躍推進法の一般事業主行動計画で確認する実務ポイント",
            "101人以上の会社が準備したい女性活躍推進法の行動計画対応",
            "男女間賃金差異の公表拡大に向けた一般事業主行動計画の実務",
        ]
    if "同一賃金ガイドライン" in topic or "同一労働同一賃金ガイドライン" in topic:
        return [
            "同一労働同一賃金ガイドライン改正で見直す待遇説明の実務",
            "令和8年10月施行に向けたパート・有期雇用の待遇点検",
            "住宅手当などの待遇差を説明できる賃金制度見直しの実務",
        ]
    if "トライアル雇用" in topic:
        return [
            "トライアル雇用助成金を使う前に確認したい採用実務",
            "一般トライアルコースの基本と採用後の労務管理チェックポイント",
            "試行雇用から常用雇用へつなげるためのトライアル雇用助成金の実務",
        ]
    if "子ども・子育て支援金" in topic:
        return [
            "子ども・子育て支援金制度で確認したい給与計算と説明準備",
            "令和8年度の子ども・子育て支援金に向けた会社の実務チェック",
            "社会保険料とあわせて始まる子ども・子育て支援金の給与実務",
        ]
    if "無期転換" in topic:
        return [
            "無期転換ルールの5年通算で確認したい契約更新の実務",
            "有期契約の空白期間と無期転換申込権で会社が注意したいこと",
            "採用予定者がいる会社のための無期転換ルールと契約管理",
        ]
    if "労働時間現状維持希望" in topic or "働き方改革関連法施行後" in topic:
        return [
            "働き方改革関連法から5年。労働時間管理を見直す実務ポイント",
            "労働時間は「現状維持」でよい？残業・上限規制対応の再点検",
            "時間外労働の上限規制対応を再点検。中小企業の労務管理チェックポイント",
        ]
    if "パート" in topic and "有期" in topic and "同一賃金" in topic:
        return [
            "パート・有期雇用の待遇説明義務はどう変わる？実務対応の確認ポイント",
            "改正パート・有期労働法施行規則に向けた中小企業の準備ポイント",
            "同一労働同一賃金の説明対応を再確認。パート・有期雇用で注意すべきこと",
        ]
    if "メンタルヘルス" in topic or "ストレスチェック" in topic:
        return [
            "50人未満の事業場もストレスチェック義務化へ。中小企業が今から準備すべきこと",
            "小規模事業場のメンタルヘルス対策。ストレスチェック義務化を見据えた実務対応",
            "ストレスチェック義務化に向けた中小企業の準備と社内体制づくり",
        ]
    if "助成金" in topic:
        return [
            f"{topic}とは？対象者・要件・活用前の確認ポイント",
            f"中小企業向けに解説：{topic}の基本と申請前に確認すべきこと",
            f"{topic}を活用する前に押さえたい実務上の注意点",
        ]
    if "改正" in topic or "施行" in topic or "law_change" in labels:
        return [
            f"{topic}で会社が確認すべき実務対応",
            f"{topic}をわかりやすく解説。会社が準備すべきポイント",
            f"法改正対応で注意したい{topic}の実務チェックポイント",
        ]
    return [
        f"{topic}とは？人事労務担当者向けに実務を解説",
        f"{topic}から考える中小企業の労務管理ポイント",
        f"会社が押さえたい{topic}の実務対応",
    ]


def build_slug(topic: str, labels: str) -> str:
    if "65" in topic and "雇用推進助成金" in topic:
        return "senior-employment-subsidy"
    if "女性活躍推進法" in topic or "一般事業主行動計画" in topic:
        return "women-action-plan"
    if "同一賃金ガイドライン" in topic or "同一労働同一賃金ガイドライン" in topic:
        return "equal-pay-guideline"
    if "トライアル雇用" in topic:
        return "trial-employment-subsidy"
    if "子ども・子育て支援金" in topic:
        return "childcare-support-contribution"
    if "無期転換" in topic:
        return "fixed-term-contract-conversion"
    if "助成金" in topic:
        return "subsidy-practical-guide"
    if "労働時間" in topic or "働き方改革" in topic:
        return "working-hours-practical-guide"
    if "パート" in topic or "有期" in topic:
        return "part-time-fixed-term-employment"
    if "カスハラ" in topic or "ハラスメント" in topic:
        return "customer-harassment-guide"
    if "ストレスチェック" in topic or "メンタルヘルス" in topic:
        return "mental-health-stress-check"
    if "年金" in topic:
        return "pension-practical-guide"
    return "labor-management-update"


def build_meta_description(topic: str) -> str:
    if "65" in topic and "雇用推進助成金" in topic:
        return "65歳超雇用推進助成金の高年齢者評価制度等雇用管理改善コースについて、対象措置、計画、規程、記録管理の実務ポイントを解説します。"
    if "女性活躍推進法" in topic or "一般事業主行動計画" in topic:
        return "女性活躍推進法に基づく一般事業主行動計画について、対象企業、状況把握、届出、公表、男女間賃金差異への準備を解説します。"
    if "同一賃金ガイドライン" in topic or "同一労働同一賃金ガイドライン" in topic:
        return "同一労働同一賃金ガイドライン改正を踏まえ、パート・有期雇用の待遇差、住宅手当、労働条件通知書、説明資料の見直しを解説します。"
    if "トライアル雇用" in topic:
        return "トライアル雇用助成金の基本、対象者確認、ハローワーク等の紹介、雇入れ後の記録管理について中小企業向けに整理します。"
    if "子ども・子育て支援金" in topic:
        return "子ども・子育て支援金制度について、給与計算、社会保険料、従業員説明、スケジュール管理の実務ポイントを解説します。"
    if "無期転換" in topic:
        return "有期労働契約の無期転換ルールについて、5年通算、空白期間、契約更新、労働条件明示の実務ポイントを解説します。"
    if "労働時間現状維持希望" in topic or "働き方改革関連法施行後" in topic:
        return "働き方改革関連法の施行から一定期間が経過した今、会社が見直したい労働時間管理、残業対応、上限規制の実務ポイントを解説します。"
    if "パート" in topic and "有期" in topic and "同一賃金" in topic:
        return "パート・有期雇用の待遇説明や同一労働同一賃金対応について、中小企業が確認すべき実務ポイントをわかりやすく解説します。"
    if "メンタルヘルス" in topic or "ストレスチェック" in topic:
        return "ストレスチェック義務化を見据え、中小企業が準備したいメンタルヘルス対策と実務上の確認ポイントを解説します。"
    return f"{topic}について、中小企業の経営者・人事労務担当者が確認すべきポイントを、実務対応の観点からわかりやすく解説します。"
