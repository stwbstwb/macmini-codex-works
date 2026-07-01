from __future__ import annotations

import re
import unicodedata


EXCLUDED_SUBSIDY_TOPIC_TERMS = ("助成金", "補助金", "奨励金")


def normalize_policy_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text)


def subsidy_topic_exclusion_hits(row: dict[str, object]) -> list[str]:
    text = " ".join(str(row.get(key) or "") for key in ("section_group", "topic_title", "excerpt"))
    normalized = normalize_policy_text(text)
    return [term for term in EXCLUDED_SUBSIDY_TOPIC_TERMS if term in normalized]


def subsidy_topic_exclusion_reason(row: dict[str, object]) -> str:
    hits = subsidy_topic_exclusion_hits(row)
    if not hits:
        return ""
    return f"柏谷横浜社労士事務所の取扱業務外（助成金・補助金等: {'、'.join(hits)}）"
