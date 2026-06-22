from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .io_utils import to_int


DATE_PATTERNS = [
    re.compile(r"(20\d{2}|令和[0-9元]+)\s*年?"),
    re.compile(r"\d{1,2}\s*月"),
    re.compile(r"\d{1,2}\s*日"),
]


def select_rewrite_candidate(
    items: list[dict[str, Any]],
    settings: dict[str, Any],
    *,
    rewrite_history_post_ids: set[int] | None = None,
    ignore_history: bool = False,
) -> dict[str, Any]:
    selection_settings = settings.get("candidate_selection", {}) if isinstance(settings.get("candidate_selection"), dict) else {}
    timezone = ZoneInfo(str(settings.get("timezone") or "Asia/Tokyo"))
    now = datetime.now(timezone)

    total_views_values = [to_int(item.get("views_total")) for item in items]
    recent_views_values = [to_int(item.get("views_recent")) for item in items]
    low_percentile = to_int(selection_settings.get("low_views_percentile")) or 35
    total_views_cutoff = percentile(total_views_values, low_percentile)
    recent_views_cutoff = percentile(recent_views_values, low_percentile)

    scored_items = []
    excluded_items = []
    history_post_ids = rewrite_history_post_ids or set()

    for item in items:
        candidate = score_item(
            item,
            settings=selection_settings,
            now=now,
            timezone=timezone,
            total_views_cutoff=total_views_cutoff,
            recent_views_cutoff=recent_views_cutoff,
            rewrite_history_post_ids=history_post_ids,
            ignore_history=ignore_history,
        )
        if candidate["excluded"]:
            excluded_items.append(candidate)
        else:
            scored_items.append(candidate)

    scored_items.sort(key=lambda item: (-float(item["score"]), to_int(item["views_total"]), to_int(item["views_recent"])))

    top_n = to_int(selection_settings.get("top_n_report")) or 20
    selected = scored_items[0] if scored_items else None

    return {
        "status": "ok" if selected else "no_candidate",
        "generated_at": now.isoformat(timespec="seconds"),
        "settings": {
            "minimum_age_days": to_int(selection_settings.get("minimum_age_days")) or 90,
            "target_character_count": to_int(selection_settings.get("target_character_count")) or 3500,
            "minimum_h2_count": to_int(selection_settings.get("minimum_h2_count")) or 4,
            "minimum_h3_count": to_int(selection_settings.get("minimum_h3_count")) or 4,
            "low_views_percentile": low_percentile,
            "total_views_cutoff": total_views_cutoff,
            "recent_views_cutoff": recent_views_cutoff,
            "rewrite_history_enabled": not ignore_history,
            "rewrite_history_excluded_post_count": len(history_post_ids) if not ignore_history else 0,
        },
        "counts": {
            "input_items": len(items),
            "eligible_items": len(scored_items),
            "excluded_items": len(excluded_items),
        },
        "selected": selected,
        "top_candidates": scored_items[:top_n],
        "excluded_summary": summarize_exclusions(excluded_items),
        "excluded_items": excluded_items[:top_n],
    }


def score_item(
    item: dict[str, Any],
    *,
    settings: dict[str, Any],
    now: datetime,
    timezone: ZoneInfo,
    total_views_cutoff: int,
    recent_views_cutoff: int,
    rewrite_history_post_ids: set[int],
    ignore_history: bool,
) -> dict[str, Any]:
    published_at = parse_datetime(item.get("published_date"), timezone)
    age_days = (now - published_at).days if published_at else None
    minimum_age_days = to_int(settings.get("minimum_age_days")) or 90
    text_for_exclusion = build_exclusion_text(item)
    time_sensitive_reasons = find_time_sensitive_reasons(text_for_exclusion, settings)

    exclusion_reasons = []
    post_id = to_int(item.get("post_id"))
    if not ignore_history and post_id in rewrite_history_post_ids:
        exclusion_reasons.append("rewrite_history:already_rewritten_or_in_progress")

    if age_days is None:
        exclusion_reasons.append("published_date_missing")
    elif age_days < minimum_age_days:
        exclusion_reasons.append(f"too_recent:{age_days}d<{minimum_age_days}d")

    if time_sensitive_reasons:
        exclusion_reasons.extend(time_sensitive_reasons)

    if item.get("views_source_available") is False:
        exclusion_reasons.append("views_source_unavailable")

    weights = settings.get("score_weights", {}) if isinstance(settings.get("score_weights"), dict) else {}
    components = build_score_components(
        item,
        settings=settings,
        total_views_cutoff=total_views_cutoff,
        recent_views_cutoff=recent_views_cutoff,
        weights={
            "total_views": float(weights.get("total_views", 40)),
            "recent_views": float(weights.get("recent_views", 25)),
            "short_content": float(weights.get("short_content", 20)),
            "thin_structure": float(weights.get("thin_structure", 15)),
        },
    )
    score = round(sum(components.values()), 2)

    reasons = build_positive_reasons(item, settings, total_views_cutoff, recent_views_cutoff)

    return {
        "post_id": post_id,
        "title": str(item.get("title") or ""),
        "url": item.get("url"),
        "published_date": item.get("published_date"),
        "age_days": age_days,
        "views_total": to_int(item.get("views_total")),
        "views_recent": to_int(item.get("views_recent")),
        "views_recent_days": to_int(item.get("views_recent_days")),
        "computed_character_count": to_int(item.get("computed_character_count")),
        "wp_statistics_word_count": item.get("wp_statistics_word_count"),
        "h2_count": to_int(item.get("h2_count")),
        "h3_count": to_int(item.get("h3_count")),
        "category_names": item.get("category_names") or [],
        "tag_names": item.get("tag_names") or [],
        "excerpt": item.get("excerpt"),
        "score": score,
        "score_components": components,
        "reasons": reasons,
        "excluded": bool(exclusion_reasons),
        "exclusion_reasons": exclusion_reasons,
    }


def build_score_components(
    item: dict[str, Any],
    *,
    settings: dict[str, Any],
    total_views_cutoff: int,
    recent_views_cutoff: int,
    weights: dict[str, float],
) -> dict[str, float]:
    total_views = to_int(item.get("views_total"))
    recent_views = to_int(item.get("views_recent"))
    character_count = to_int(item.get("computed_character_count"))
    h2_count = to_int(item.get("h2_count"))
    h3_count = to_int(item.get("h3_count"))

    target_chars = to_int(settings.get("target_character_count")) or 3500
    minimum_h2 = to_int(settings.get("minimum_h2_count")) or 4
    minimum_h3 = to_int(settings.get("minimum_h3_count")) or 4

    return {
        "total_views": round(low_metric_score(total_views, total_views_cutoff, weights["total_views"]), 2),
        "recent_views": round(low_metric_score(recent_views, recent_views_cutoff, weights["recent_views"]), 2),
        "short_content": round(deficit_score(character_count, target_chars, weights["short_content"]), 2),
        "thin_structure": round(
            weights["thin_structure"]
            * (
                0.55 * deficit_ratio(h2_count, minimum_h2)
                + 0.45 * deficit_ratio(h3_count, minimum_h3)
            ),
            2,
        ),
    }


def low_metric_score(value: int, cutoff: int, weight: float) -> float:
    cutoff = max(0, cutoff)
    if value > cutoff:
        return 0.0
    return weight * ((cutoff - value + 1) / (cutoff + 1))


def deficit_score(value: int, target: int, weight: float) -> float:
    return weight * deficit_ratio(value, target)


def deficit_ratio(value: int, target: int) -> float:
    target = max(1, target)
    return max(0.0, min(1.0, (target - value) / target))


def percentile(values: list[int], percentile_value: int) -> int:
    if not values:
        return 0
    values = sorted(values)
    if len(values) == 1:
        return values[0]

    percentile_value = max(0, min(100, percentile_value))
    if percentile_value == 0:
        return values[0]
    if percentile_value == 100:
        return values[-1]

    index = round((percentile_value / 100) * (len(values) - 1))
    return values[index]


def build_positive_reasons(
    item: dict[str, Any],
    settings: dict[str, Any],
    total_views_cutoff: int,
    recent_views_cutoff: int,
) -> list[str]:
    reasons = []
    total_views = to_int(item.get("views_total"))
    recent_views = to_int(item.get("views_recent"))
    chars = to_int(item.get("computed_character_count"))
    h2_count = to_int(item.get("h2_count"))
    h3_count = to_int(item.get("h3_count"))
    target_chars = to_int(settings.get("target_character_count")) or 3500
    minimum_h2 = to_int(settings.get("minimum_h2_count")) or 4
    minimum_h3 = to_int(settings.get("minimum_h3_count")) or 4

    if total_views <= total_views_cutoff:
        reasons.append(f"views_total_low:{total_views}<={total_views_cutoff}")
    if recent_views <= recent_views_cutoff:
        reasons.append(f"views_recent_low:{recent_views}<={recent_views_cutoff}")
    if chars < target_chars:
        reasons.append(f"short_content:{chars}<{target_chars}")
    if h2_count < minimum_h2:
        reasons.append(f"few_h2:{h2_count}<{minimum_h2}")
    if h3_count < minimum_h3:
        reasons.append(f"few_h3:{h3_count}<{minimum_h3}")

    return reasons


def find_time_sensitive_reasons(text: str, settings: dict[str, Any]) -> list[str]:
    reasons = []
    keywords = settings.get("time_sensitive_keywords", [])

    if isinstance(keywords, list):
        for keyword in keywords:
            keyword_text = str(keyword).strip()
            if keyword_text and keyword_text in text:
                reasons.append(f"time_sensitive_keyword:{keyword_text}")

    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            reasons.append(f"time_sensitive_date:{match.group(0)}")

    return reasons


def build_exclusion_text(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("title") or ""),
        str(item.get("excerpt") or ""),
        " ".join(str(value) for value in item.get("category_names") or []),
        " ".join(str(value) for value in item.get("tag_names") or []),
    ]
    return " ".join(parts)


def parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None

    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def summarize_exclusions(excluded_items: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in excluded_items:
        item_keys = set()
        for reason in item.get("exclusion_reasons", []):
            key = str(reason).split(":", 1)[0]
            item_keys.add(key)
        for key in item_keys:
            summary[key] = summary.get(key, 0) + 1
    return dict(sorted(summary.items(), key=lambda pair: (-pair[1], pair[0])))


def render_candidate_report(payload: dict[str, Any]) -> str:
    selected = payload.get("selected") or {}
    lines = [
        "# リライト候補選定レポート",
        "",
        f"- 状態: {payload.get('status')}",
        f"- 生成日時: {payload.get('generated_at')}",
        f"- 入力記事数: {payload.get('counts', {}).get('input_items')}",
        f"- 候補対象記事数: {payload.get('counts', {}).get('eligible_items')}",
        f"- 除外記事数: {payload.get('counts', {}).get('excluded_items')}",
        f"- リライト履歴除外: {payload.get('settings', {}).get('rewrite_history_excluded_post_count')}",
        "",
        "## 選定記事",
        "",
    ]

    if selected:
        lines.extend(
            [
                f"- post_id: {selected.get('post_id')}",
                f"- title: {selected.get('title')}",
                f"- url: {selected.get('url')}",
                f"- score: {selected.get('score')}",
                f"- views_total: {selected.get('views_total')}",
                f"- views_recent: {selected.get('views_recent')}",
                f"- computed_character_count: {selected.get('computed_character_count')}",
                f"- h2_count: {selected.get('h2_count')}",
                f"- h3_count: {selected.get('h3_count')}",
                f"- reasons: {', '.join(selected.get('reasons') or [])}",
                "",
            ]
        )
    else:
        lines.extend(["候補記事はありません。", ""])

    lines.extend(
        [
            "## 上位候補",
            "",
            "| 順位 | score | post_id | title | views_total | views_recent | chars | h2 | h3 | reasons |",
            "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for index, item in enumerate(payload.get("top_candidates") or [], start=1):
        lines.append(
            "| {rank} | {score} | {post_id} | {title} | {views_total} | {views_recent} | {chars} | {h2} | {h3} | {reasons} |".format(
                rank=index,
                score=item.get("score"),
                post_id=item.get("post_id"),
                title=escape_table_text(str(item.get("title") or "")),
                views_total=item.get("views_total"),
                views_recent=item.get("views_recent"),
                chars=item.get("computed_character_count"),
                h2=item.get("h2_count"),
                h3=item.get("h3_count"),
                reasons=escape_table_text(", ".join(item.get("reasons") or [])),
            )
        )

    lines.extend(["", "## 除外理由サマリー", ""])

    excluded_summary = payload.get("excluded_summary") or {}
    if excluded_summary:
        for reason, count in excluded_summary.items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- なし")

    return "\n".join(lines)


def escape_table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
