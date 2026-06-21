from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .io_utils import read_json, read_text, write_csv_dicts, write_json, write_markdown
from .paths import CONFIG_DIR, GENERATED_DIR, STATE_DIR


COMMON_SOURCE_CANDIDATES = [
    "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000148322.html",
    "https://www.mhlw.go.jp/hatarakikata/",
]


LEGAL_PATTERNS = [
    "労働基準法",
    "労働安全衛生法",
    "働き方改革関連法",
    "パートタイム・有期雇用労働法",
    "育児・介護休業法",
    "育児介護休業法",
    "産後パパ育休",
    "出生時育児休業給付金",
    "育児休業給付金",
    "障害者雇用促進法",
    "労働契約法",
    "無期転換ルール",
    "労働条件明示",
    "トライアル雇用助成金",
    "一般トライアルコース",
    "65歳超雇用推進助成金",
    "高年齢者評価制度等雇用管理改善コース",
    "雇用管理整備計画",
    "人材開発支援助成金",
    "事業展開等リスキリング支援コース",
    "女性活躍推進法",
    "一般事業主行動計画",
    "男女間賃金差異",
    "同一労働同一賃金ガイドライン",
    "同一労働同一賃金",
    "子ども・子育て支援金制度",
    "子ども・子育て支援金",
    "ストレスチェック",
    "高年齢者の労働災害防止",
    "36協定",
    "時間外労働の上限規制",
    "特別条項",
    "年5日取得義務",
    "月45時間",
    "年360時間",
]

SOURCE_HINTS = {
    "労働基準法": "厚生労働省、e-Gov法令検索",
    "労働安全衛生法": "厚生労働省、e-Gov法令検索",
    "働き方改革関連法": "厚生労働省",
    "労働契約法": "e-Gov法令検索、厚生労働省",
    "無期転換ルール": "厚生労働省",
    "労働条件明示": "厚生労働省",
    "トライアル雇用助成金": "厚生労働省",
    "一般トライアルコース": "厚生労働省",
    "65歳超雇用推進助成金": "高齢・障害・求職者雇用支援機構",
    "高年齢者評価制度等雇用管理改善コース": "高齢・障害・求職者雇用支援機構",
    "雇用管理整備計画": "高齢・障害・求職者雇用支援機構",
    "人材開発支援助成金": "厚生労働省",
    "事業展開等リスキリング支援コース": "厚生労働省",
    "女性活躍推進法": "厚生労働省",
    "一般事業主行動計画": "厚生労働省",
    "男女間賃金差異": "厚生労働省",
    "同一労働同一賃金ガイドライン": "厚生労働省",
    "同一労働同一賃金": "厚生労働省",
    "子ども・子育て支援金制度": "こども家庭庁",
    "子ども・子育て支援金": "こども家庭庁",
    "ストレスチェック": "厚生労働省",
    "高年齢者の労働災害防止": "厚生労働省、e-Gov法令検索",
    "時間外労働の上限規制": "厚生労働省",
    "36協定": "厚生労働省、36協定届等作成支援ツール",
    "特別条項": "厚生労働省、36協定届等作成支援ツール",
    "年5日取得義務": "厚生労働省 年次有給休暇取得義務関連資料",
    "月45時間": "厚生労働省 時間外労働の上限規制資料",
    "年360時間": "厚生労働省 時間外労働の上限規制資料",
}

SOURCE_CANDIDATES = {
    "労働基準法": [
        "https://laws.e-gov.go.jp/law/322AC0000000049",
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000148322.html",
    ],
    "労働安全衛生法": [
        "https://laws.e-gov.go.jp/",
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000148322.html",
    ],
    "働き方改革関連法": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000148322.html",
    ],
    "パートタイム・有期雇用労働法": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000046152.html",
    ],
    "育児・介護休業法": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html",
    ],
    "育児介護休業法": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html",
    ],
    "産後パパ育休": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html",
    ],
    "出生時育児休業給付金": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html",
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000158500.html",
    ],
    "育児休業給付金": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000158500.html",
    ],
    "障害者雇用促進法": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/shougaishakoyou/index.html",
    ],
    "労働契約法": [
        "https://laws.e-gov.go.jp/law/419AC0000000128",
        "https://muki.mhlw.go.jp/",
    ],
    "無期転換ルール": [
        "https://muki.mhlw.go.jp/",
        "https://laws.e-gov.go.jp/law/419AC0000000128",
    ],
    "労働条件明示": [
        "https://muki.mhlw.go.jp/",
        "https://www.mhlw.go.jp/stf/newpage_32105.html",
    ],
    "トライアル雇用助成金": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/trial_koyou.html",
    ],
    "一般トライアルコース": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/trial_koyou.html",
    ],
    "65歳超雇用推進助成金": [
        "https://www.jeed.go.jp/elderly/subsidy/subsidy_hyouka.html",
    ],
    "高年齢者評価制度等雇用管理改善コース": [
        "https://www.jeed.go.jp/elderly/subsidy/subsidy_hyouka.html",
    ],
    "雇用管理整備計画": [
        "https://www.jeed.go.jp/elderly/subsidy/subsidy_hyouka.html",
    ],
    "人材開発支援助成金": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
    ],
    "事業展開等リスキリング支援コース": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
    ],
    "女性活躍推進法": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000091025.html",
    ],
    "一般事業主行動計画": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000091025.html",
    ],
    "男女間賃金差異": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000091025.html",
    ],
    "同一労働同一賃金ガイドライン": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000144972.html",
    ],
    "同一労働同一賃金": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000144972.html",
    ],
    "子ども・子育て支援金制度": [
        "https://www.cfa.go.jp/policies/kodomokosodateshienkinseido",
    ],
    "子ども・子育て支援金": [
        "https://www.cfa.go.jp/policies/kodomokosodateshienkinseido",
        "https://www.cfa.go.jp/policies/kodomokosodateshienkin",
    ],
    "ストレスチェック": [
        "https://www.mhlw.go.jp/bunya/roudoukijun/anzeneisei12/",
    ],
    "高年齢者の労働災害防止": [
        "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/anzen/newpage_00007.html",
        "https://www.mhlw.go.jp/stf/newpage_10178.html",
    ],
    "36協定": [
        "https://www.mhlw.go.jp/hatarakikata/overtime.html",
        "https://www.startup-roudou.mhlw.go.jp/",
        "https://www.mhlw.go.jp/content/000350731.pdf",
    ],
    "時間外労働の上限規制": [
        "https://www.mhlw.go.jp/hatarakikata/overtime.html",
        "https://www.mhlw.go.jp/content/000350731.pdf",
    ],
    "特別条項": [
        "https://www.mhlw.go.jp/hatarakikata/overtime.html",
        "https://www.mhlw.go.jp/content/000350731.pdf",
    ],
    "年5日取得義務": [
        "https://www.mhlw.go.jp/content/000350327.pdf",
    ],
    "月45時間": [
        "https://www.mhlw.go.jp/hatarakikata/overtime.html",
        "https://www.mhlw.go.jp/content/000350731.pdf",
    ],
    "年360時間": [
        "https://www.mhlw.go.jp/hatarakikata/overtime.html",
        "https://www.mhlw.go.jp/content/000350731.pdf",
    ],
}


@dataclass
class FactCheckItem:
    item_type: str
    claim: str
    context: str
    required_source: str
    source_candidates: str
    status: str = "unverified"
    note: str = "投稿前に一次情報で確認する"
    verified_source_url: str = ""
    verified_at: str = ""
    verification_note: str = ""


def build_fact_check_items() -> dict[str, object]:
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    article = strip_html_comments(read_text(article_path)) if article_path.exists() else ""
    items = extract_fact_check_items(article)
    apply_fact_check_registry(items)
    unverified_count = sum(1 for item in items if item.status != "verified")
    payload = {
        "status": "ok" if article else "no_article",
        "article_path": str(article_path),
        "unverified_count": unverified_count,
        "verified_count": len(items) - unverified_count,
        "items": [asdict(item) for item in items],
        "publication_gate": "blocked_until_verified" if unverified_count else "verified" if items else "no_fact_items",
    }
    write_json(GENERATED_DIR / "articles" / "fact_check_items_latest.json", payload)
    write_csv_dicts(
        GENERATED_DIR / "articles" / "fact_check_items_latest.csv",
        [asdict(item) for item in items],
        [
            "item_type",
            "claim",
            "context",
            "required_source",
            "source_candidates",
            "status",
            "note",
            "verified_source_url",
            "verified_at",
            "verification_note",
        ],
    )
    write_markdown(GENERATED_DIR / "articles" / "fact_check_items_latest.md", render_fact_check_items(payload))
    return payload


def strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def extract_fact_check_items(article: str) -> list[FactCheckItem]:
    items: list[FactCheckItem] = []
    seen: set[tuple[str, str]] = set()
    protected_spans: list[tuple[int, int]] = []

    for pattern in LEGAL_PATTERNS:
        for match in re.finditer(re.escape(pattern), article):
            claim = match.group(0)
            protected_spans.append((match.start(), match.end()))
            key = ("legal_or制度", normalize_key(claim))
            if key in seen:
                continue
            seen.add(key)
            items.append(
                FactCheckItem(
                    item_type="legal_or制度",
                    claim=claim,
                    context=make_context(article, match.start(), match.end()),
                    required_source=SOURCE_HINTS.get(claim, "厚生労働省、e-Gov法令検索、所管官庁の一次情報"),
                    source_candidates=source_candidates_for(claim, "legal_or制度"),
                )
            )

    for match in re.finditer(r"(?:20\d{2}年|令和[0-9０-９]+年)[0-9０-９]*月?[0-9０-９]*日?|[0-9０-９]+月[0-9０-９]+日", article):
        claim = match.group(0)
        key = ("date", normalize_key(claim))
        protected_spans.append((match.start(), match.end()))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            FactCheckItem(
                item_type="date",
                claim=claim,
                context=make_context(article, match.start(), match.end()),
                required_source="厚生労働省、労働局、所管官庁、出典PDFの該当箇所",
                source_candidates=source_candidates_for(claim, "date"),
            )
        )

    for match in re.finditer(r"[0-9０-９]+(?:\.[0-9０-９]+)?\s*(?:社|人|件|％|%|時間|日|年|カ月|か月)", article):
        if overlaps(match.start(), match.end(), protected_spans):
            continue
        claim = normalize_spaces(match.group(0))
        key = ("number", normalize_key(claim))
        if key in seen:
            continue
        seen.add(key)
        items.append(
            FactCheckItem(
                item_type="number",
                claim=claim,
                context=make_context(article, match.start(), match.end()),
                required_source="厚生労働省、労働局、統計資料、出典PDFの該当箇所",
                source_candidates=source_candidates_for(claim, "number"),
            )
        )

    return items


def apply_fact_check_registry(items: list[FactCheckItem]) -> None:
    registry = read_json(STATE_DIR / "fact_check_registry.json", {"items": []}) or {"items": []}
    seed = read_json(CONFIG_DIR / "fact_check_verified_sources.json", {"items": []}) or {"items": []}
    verified_entries = {}
    for entry in [*seed.get("items", []), *registry.get("items", [])]:
        if entry.get("status") != "verified":
            continue
        key = (entry.get("item_type") or "", normalize_key(str(entry.get("claim") or "")))
        verified_entries[key] = entry

    for item in items:
        entry = verified_entries.get((item.item_type, normalize_key(item.claim)))
        if not entry:
            continue
        item.status = "verified"
        item.note = "一次情報確認済み"
        item.verified_source_url = str(entry.get("source_url") or "")
        item.verified_at = str(entry.get("verified_at") or "")
        item.verification_note = str(entry.get("memo") or "")


def overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def normalize_key(text: str) -> str:
    table = str.maketrans("０１２３４５６７８９％", "0123456789%")
    return normalize_spaces(text.translate(table)).replace(" ", "")


def source_candidates_for(claim: str, item_type: str) -> str:
    if claim in SOURCE_CANDIDATES:
        return " / ".join(SOURCE_CANDIDATES[claim])
    if item_type == "date":
        return " / ".join(
            [
                "出典PDFの該当箇所",
                "https://www.mhlw.go.jp/",
                "https://www.e-gov.go.jp/",
            ]
        )
    if item_type == "number":
        return " / ".join(
            [
                "出典PDFの該当箇所",
                "https://www.mhlw.go.jp/toukei/",
                "https://www.mhlw.go.jp/stf/houdou/",
            ]
        )
    return " / ".join(COMMON_SOURCE_CANDIDATES)


def make_context(text: str, start: int, end: int, width: int = 80) -> str:
    before = max(0, start - width)
    after = min(len(text), end + width)
    return normalize_spaces(text[before:after])


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def render_fact_check_items(payload: dict[str, object]) -> str:
    lines = [
        "# ファクトチェック項目",
        "",
        f"- 状態: {payload['status']}",
        f"- 未確認項目数: {payload['unverified_count']}",
        f"- 確認済み項目数: {payload['verified_count']}",
        f"- 公開ゲート: {payload['publication_gate']}",
        "",
        "## 運用ルール",
        "",
        "- 法律名、制度名、日付、数値は、投稿前に一次情報で確認する。",
        "- 各項目の候補URLは出発点であり、本文公開前に最新ページ・PDF・法令本文で内容を照合する。",
        "- 確認できない場合は、本文で断定しない。",
        "- 古い情報の可能性がある場合は、最新情報へ差し替える。",
        "- 出典PDF由来の数値でも、公的情報で確認できるものは公的情報を優先する。",
        "",
        "## 確認対象",
        "",
    ]
    for index, item in enumerate(payload["items"], 1):
        lines.extend(
            [
                f"### {index}. {item['claim']}",
                "",
                f"- 種別: {item['item_type']}",
                f"- 状態: {item['status']}",
                f"- 必要な根拠: {item['required_source']}",
                f"- 確認候補ソース: {item['source_candidates']}",
                f"- 確認済みソース: {item['verified_source_url'] or '未確認'}",
                f"- 確認日: {item['verified_at'] or '未確認'}",
                f"- 文脈: {item['context']}",
                "",
            ]
        )
    return "\n".join(lines)
