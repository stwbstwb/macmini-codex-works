from __future__ import annotations

from datetime import datetime

from .io_utils import read_csv_dicts, write_json, write_markdown
from .paths import GENERATED_DIR, TOPIC_SELECTION_DIR
from .article_brief import select_current_or_recommended_topic


COMMON_OFFICIAL_SOURCES = [
    {
        "name": "厚生労働省「働き方改革」の実現に向けて",
        "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000148322.html",
        "why": "働き方改革の目的、支援策、関連資料の起点として確認する。",
    },
    {
        "name": "厚生労働省 働き方改革特設サイト",
        "url": "https://www.mhlw.go.jp/hatarakikata/",
        "why": "事業主向けの実務資料や支援情報を確認する。",
    },
    {
        "name": "36協定届等作成支援ツール",
        "url": "https://www.startup-roudou.mhlw.go.jp/",
        "why": "36協定や時間外労働上限規制の実務確認に使う。",
    },
    {
        "name": "働き方・休み方改善ポータルサイト",
        "url": "https://work-holiday.mhlw.go.jp/",
        "why": "労働時間、休暇、働き方改善の実務資料を確認する。",
    },
]


TOPIC_SOURCE_MAP = {
    "senior_employment_subsidy": [
        {
            "name": "高齢・障害・求職者雇用支援機構 65歳超雇用推進助成金（高年齢者評価制度等雇用管理改善コース）",
            "url": "https://www.jeed.go.jp/elderly/subsidy/subsidy_hyouka.html",
            "why": "制度概要、対象となる雇用管理整備措置、計画提出時期、支給申請の流れを確認する。",
        }
    ],
    "women_action_plan": [
        {
            "name": "厚生労働省 女性活躍推進法特集ページ",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000091025.html",
            "why": "一般事業主行動計画、対象企業、男女間賃金差異の情報公表、令和8年4月1日施行の改正を確認する。",
        }
    ],
    "equal_pay_guideline": [
        {
            "name": "厚生労働省 同一労働同一賃金特集ページ",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000144972.html",
            "why": "同一労働同一賃金ガイドライン、パートタイム・有期雇用労働法、令和8年10月1日施行・適用の改正を確認する。",
        }
    ],
    "trial_employment_subsidy": [
        {
            "name": "厚生労働省 トライアル雇用助成金（一般トライアルコース）",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/trial_koyou.html",
            "why": "制度概要、対象労働者、雇入れ条件、支給額を確認する。",
        }
    ],
    "childcare_support_contribution": [
        {
            "name": "こども家庭庁 子ども・子育て支援金制度について",
            "url": "https://www.cfa.go.jp/policies/kodomokosodateshienkinseido",
            "why": "令和8年度の支援金率、拠出開始時期、本人負担と事業主負担を確認する。",
        },
        {
            "name": "こども家庭庁 加速化プランによる子育て支援の拡充と子ども・子育て支援金",
            "url": "https://www.cfa.go.jp/policies/kodomokosodateshienkin",
            "why": "支援金制度の目的と充当される施策を確認する。",
        },
    ],
    "fixed_term_conversion": [
        {
            "name": "厚生労働省 有期契約労働者の無期転換サイト",
            "url": "https://muki.mhlw.go.jp/",
            "why": "無期転換ルール、通算5年、申込み、雇止め対応を確認する。",
        },
        {
            "name": "e-Gov法令検索 労働契約法",
            "url": "https://laws.e-gov.go.jp/law/419AC0000000128",
            "why": "労働契約法第18条の条文を確認する。",
        },
    ],
    "working_hours": [
        {
            "name": "厚生労働省「働き方改革」の実現に向けて 参考資料",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000148322.html#h2_free11",
            "why": "時間外労働の上限規制、労働時間の考え方、関連パンフレットを確認する。",
        },
        {
            "name": "厚生労働省 時間外労働の上限規制 特設ページ",
            "url": "https://www.mhlw.go.jp/hatarakikata/overtime.html",
            "why": "時間外労働の上限規制の説明と関連資料を確認する。",
        },
    ],
    "part_time": [
        {
            "name": "厚生労働省 パートタイム・有期雇用労働法",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000046152.html",
            "why": "パート・有期雇用、同一労働同一賃金、待遇説明義務を確認する。",
        }
    ],
    "subsidy": [
        {
            "name": "厚生労働省 人材開発支援助成金",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/kyufukin/d01-1.html",
            "why": "助成金の最新要件、申請期限、対象訓練を確認する。",
        }
    ],
    "mental_health": [
        {
            "name": "厚生労働省 ストレスチェック制度",
            "url": "https://www.mhlw.go.jp/bunya/roudoukijun/anzeneisei12/",
            "why": "ストレスチェック制度、実施体制、事業場規模別の取扱いを確認する。",
        }
    ],
    "harassment": [
        {
            "name": "厚生労働省 職場におけるハラスメント防止対策",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyoukintou/seisaku06/index.html",
            "why": "ハラスメント防止措置、企業対応、相談体制を確認する。",
        }
    ],
    "occupational_safety": [
        {
            "name": "厚生労働省 職場のあんぜんサイト",
            "url": "https://anzeninfo.mhlw.go.jp/",
            "why": "労働災害防止、安全衛生教育、災害事例統計の一次情報を確認する。",
        },
        {
            "name": "厚生労働省 高年齢労働者の安全衛生対策",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/anzen/newpage_00007.html",
            "why": "高年齢労働者の労働災害防止対策、エイジフレンドリーガイドラインを確認する。",
        },
    ],
    "payroll": [
        {
            "name": "日本年金機構 現物給与の価額",
            "url": "https://www.nenkin.go.jp/service/kounen/hokenryo/hoshu/20150511.html",
            "why": "社宅など現物給与の社会保険上の取扱いを確認する。",
        },
        {
            "name": "国税庁 タックスアンサー 給与課税",
            "url": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/gensen/gensen.htm",
            "why": "給与課税、現物給与、源泉所得税に関する一次情報を確認する。",
        },
    ],
    "pension": [
        {
            "name": "日本年金機構 在職老齢年金",
            "url": "https://www.nenkin.go.jp/service/jukyu/roureinenkin/zaishoku/index.html",
            "why": "在職老齢年金の制度概要、年金と報酬の関係を確認する。",
        },
        {
            "name": "日本年金機構 70歳以上被用者",
            "url": "https://www.nenkin.go.jp/service/kounen/tekiyo/hihokensha1/20150331.html",
            "why": "70歳到達時や70歳以上被用者に関する届出を確認する。",
        },
    ],
    "disability_employment": [
        {
            "name": "厚生労働省 障害者雇用対策",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/koyou/shougaishakoyou/index.html",
            "why": "障害者雇用率、対象者、雇用状況報告に関する一次情報を確認する。",
        }
    ],
    "childcare_care": [
        {
            "name": "厚生労働省 育児・介護休業法について",
            "url": "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000130583.html",
            "why": "育児・介護休業法、柔軟な働き方、事業主の措置義務を確認する。",
        }
    ],
}


def classify_source_topic(topic: str, labels: str) -> str:
    if "65" in topic and "雇用推進助成金" in topic:
        return "senior_employment_subsidy"
    if "女性活躍推進法" in topic or "一般事業主行動計画" in topic:
        return "women_action_plan"
    if "同一賃金ガイドライン" in topic or "同一労働同一賃金ガイドライン" in topic:
        return "equal_pay_guideline"
    if "トライアル雇用" in topic:
        return "trial_employment_subsidy"
    if "子ども・子育て支援金" in topic:
        return "childcare_support_contribution"
    if "無期転換" in topic:
        return "fixed_term_conversion"
    if "労働時間" in topic or "働き方改革" in topic:
        return "working_hours"
    if "パート" in topic or "有期" in topic or "同一賃金" in topic:
        return "part_time"
    if "助成金" in topic:
        return "subsidy"
    if "メンタルヘルス" in topic or "ストレスチェック" in topic:
        return "mental_health"
    if "カスハラ" in topic or "ハラスメント" in topic:
        return "harassment"
    if "高年齢者" in topic or "労働災害" in topic or "安全衛生" in topic:
        return "occupational_safety"
    if "社宅" in topic or "現物給与" in topic or "賃金" in topic:
        return "payroll"
    if "在職老齢年金" in topic or "年金" in topic:
        return "pension"
    if "障害者雇用" in topic:
        return "disability_employment"
    if "育児" in topic or "介護" in topic or "柔軟な働き方" in topic:
        return "childcare_care"
    if "subsidy" in labels:
        return "subsidy"
    return "working_hours"


def build_source_plan() -> dict[str, object]:
    rows = read_csv_dicts(TOPIC_SELECTION_DIR / "topic_selection_scores.csv")
    selected = select_current_or_recommended_topic(rows)
    if selected is None:
        result: dict[str, object] = {"status": "no_topic"}
        write_json(GENERATED_DIR / "outlines" / "source_check_plan_latest.json", result)
        write_markdown(GENERATED_DIR / "outlines" / "source_check_plan_latest.md", "# 一次情報確認計画\n\n候補テーマがありません。")
        return result

    topic_type = classify_source_topic(selected.get("topic_title", ""), selected.get("labels", ""))
    sources = TOPIC_SOURCE_MAP.get(topic_type, []) + COMMON_OFFICIAL_SOURCES
    checks = build_required_checks(topic_type)
    result = {
        "status": "ok",
        "selected_topic": selected.get("topic_title", ""),
        "topic_type": topic_type,
        "sources": sources,
        "required_checks": checks,
    }
    write_json(GENERATED_DIR / "outlines" / "source_check_plan_latest.json", result)
    write_markdown(GENERATED_DIR / "outlines" / "source_check_plan_latest.md", render_source_plan(result))
    return result


def build_required_checks(topic_type: str) -> list[str]:
    checks = [
        "出典PDFの記載日・対象期間・制度名を確認する",
        "厚生労働省など公的機関の最新ページで制度名と日付を確認する",
        "記事本文に入れる日付は西暦と必要に応じて和暦を併記する",
        "地域限定制度の場合は全国向け記事にしない",
        "確認できない数値や調査名は断定せず、PDF出典の紹介として扱う",
    ]
    if topic_type == "working_hours":
        checks.extend(
            [
                "時間外労働の上限規制の原則を確認する",
                "特別条項付き36協定の上限と健康確保措置を確認する",
                "建設業・運送業など適用時期や例外が絡む業種の扱いを確認する",
                "36協定、勤怠管理、就業規則、長時間労働者対応を実務チェックに含める",
            ]
        )
    elif topic_type == "senior_employment_subsidy":
        checks.extend(
            [
                "65歳超雇用推進助成金のコース名と対象措置を確認する",
                "雇用管理整備計画の提出時期と対象年齢を確認する",
                "就業規則・労働協約への規定、対象者への適用、運用記録の要否を確認する",
            ]
        )
    elif topic_type == "women_action_plan":
        checks.extend(
            [
                "一般事業主行動計画の策定・届出義務の対象企業規模を確認する",
                "令和8年4月1日施行の男女間賃金差異公表対象拡大を確認する",
                "状況把握、課題分析、届出、公表の実務手順を確認する",
            ]
        )
    elif topic_type == "equal_pay_guideline":
        checks.extend(
            [
                "令和8年10月1日施行・適用の省令・告示改正を確認する",
                "同一労働同一賃金ガイドラインの考え方と待遇差説明の範囲を確認する",
                "労働条件通知書、住宅手当などの待遇、説明資料の見直し事項を確認する",
            ]
        )
    elif topic_type == "part_time":
        checks.extend(
            [
                "パートタイム・有期雇用労働法の説明義務を確認する",
                "同一労働同一賃金ガイドラインの対象と考え方を確認する",
                "既存記事との重複が強い場合はリライト案へ切り替える",
            ]
        )
    elif topic_type == "subsidy":
        checks.extend(
            [
                "助成金の最新年度版の要件、対象事業主、対象労働者を確認する",
                "申請期限、計画届、必要書類、支給対象外要件を確認する",
                "予算や制度改定で受付停止していないか確認する",
            ]
        )
    elif topic_type == "trial_employment_subsidy":
        checks.extend(
            [
                "一般トライアルコースの対象労働者と雇入れ条件を確認する",
                "ハローワーク等の紹介、原則3か月の試行雇用、週所定労働時間の要件を確認する",
                "受給額、申請書類、雇用関係助成金共通要件を確認する",
            ]
        )
    elif topic_type == "childcare_support_contribution":
        checks.extend(
            [
                "令和8年度の支援金率と拠出開始時期を確認する",
                "被用者保険での本人負担と事業主負担の扱いを確認する",
                "給与計算・社会保険料控除・従業員説明に関係する事項を確認する",
            ]
        )
    elif topic_type == "fixed_term_conversion":
        checks.extend(
            [
                "労働契約法第18条と厚生労働省の無期転換ルール説明を確認する",
                "通算5年、申込権発生、クーリング期間、雇止め対応を確認する",
                "労働条件明示や更新上限の説明に関係する事項を確認する",
            ]
        )
    elif topic_type == "mental_health":
        checks.extend(
            [
                "ストレスチェック制度の対象事業場と義務化時期を確認する",
                "個人情報管理、実施者、面接指導、集団分析の扱いを確認する",
            ]
        )
    elif topic_type == "harassment":
        checks.extend(
            [
                "カスタマーハラスメント対策の最新指針・マニュアルを確認する",
                "職場のハラスメント防止措置との関係を確認する",
            ]
        )
    elif topic_type == "occupational_safety":
        checks.extend(
            [
                "労働安全衛生法上の事業者責任と安全配慮の考え方を確認する",
                "高年齢労働者の労働災害防止対策に関する公的資料を確認する",
            ]
        )
    elif topic_type == "payroll":
        checks.extend(
            [
                "社宅貸与が現物給与に当たる場合の社会保険上の扱いを確認する",
                "所得税・源泉徴収の扱いは国税庁資料で確認する",
            ]
        )
    elif topic_type == "pension":
        checks.extend(
            [
                "在職老齢年金の最新制度と支給停止調整額を日本年金機構で確認する",
                "70歳以上被用者に関する届出の対象と期限を確認する",
            ]
        )
    elif topic_type == "disability_employment":
        checks.extend(
            [
                "障害者雇用率、対象事業主、短時間労働者の算定方法を確認する",
                "雇用状況報告や合理的配慮の最新情報を確認する",
            ]
        )
    elif topic_type == "childcare_care":
        checks.extend(
            [
                "育児・介護休業法の施行日、事業主措置、個別周知義務を確認する",
                "就業規則・育児介護休業規程への反映事項を確認する",
            ]
        )
    return checks


def render_source_plan(result: dict[str, object]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 一次情報確認計画",
        "",
        f"生成日時: {generated_at}",
        "",
        f"対象テーマ: {result['selected_topic']}",
        f"テーマ種別: {result['topic_type']}",
        "",
        "## 確認すべき一次情報候補",
        "",
    ]
    for source in result["sources"]:
        lines.extend(
            [
                f"### {source['name']}",
                "",
                f"- URL: {source['url']}",
                f"- 確認目的: {source['why']}",
                "",
            ]
        )
    lines.extend(["## 確認チェック項目", ""])
    for check in result["required_checks"]:
        lines.append(f"- [ ] {check}")
    return "\n".join(lines)
