from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .io_utils import read_text, write_json, write_markdown
from .paths import GENERATED_DIR, LOGS_DIR
from .quality_check import measure_heading_body_lengths


SAFE_SUPPORT_PARAGRAPHS = [
    "{heading}のうち「{subheading}」は、制度名だけで判断せず、対象者、担当部署、確認資料、保存場所を社内でそろえることが大切です。口頭確認だけで終えると担当者ごとに対応が分かれやすいため、判断した日付、確認した資料、次に見直す時期を簡単な記録として残しておくと、後日の説明や引き継ぎにも使いやすくなります。",
    "実務では、{subheading}に関係する書類と現場運用が一致しているかを確認します。就業規則、雇用契約書、勤怠・賃金関係の資料、社内周知文などを別々に見るのではなく、同じ基準で説明できる状態にしておくと、{heading}の見直しを一度きりの作業で終わらせず継続管理につなげやすくなります。",
    "{subheading}を確認するときは、担当者だけで抱え込まず、経営者、管理職、給与・勤怠担当者の役割を分けることも重要です。誰が対象者を確認し、誰が資料を更新し、誰が従業員へ説明するのかを決めておけば、{heading}に関する対応漏れや説明不足を減らしやすくなります。",
]

BANNED_SENTENCE_PATTERNS = [
    "人事労務だより",
    "出典PDF",
    "掲載されていた",
    "掲載されていました",
    "取り上げられていた",
    "取り上げられていました",
    "柏谷横浜社労士事務所では",
    "ご相談を承っています",
    "ご相談ください",
    "お問い合わせください",
    "お気軽にご相談",
    "社労士に相談した方がよいケース",
]


def repair_current_article(
    quality: dict[str, Any] | None = None,
    item_index: int | None = None,
    attempt: int = 1,
    run_key: str | None = None,
) -> dict[str, Any]:
    """Deterministically repair machine-detected article issues without adding new facts."""
    article_path = GENERATED_DIR / "articles" / "article_draft_latest.md"
    if not article_path.exists():
        return write_repair_log(
            {
                "status": "no_article",
                "changed": False,
                "item_index": item_index,
                "attempt": attempt,
                "reason": "article_draft_latest.md not found",
            },
            run_key,
        )

    before = read_text(article_path)
    repaired = before
    actions: list[dict[str, Any]] = []

    repaired, removed = remove_banned_sentences(repaired)
    if removed:
        actions.append({"action": "remove_banned_sentences", "count": removed})

    repaired, renamed = rename_generic_headings(repaired)
    if renamed:
        actions.append({"action": "rename_generic_headings", "count": renamed})

    repaired, expanded = expand_short_heading_blocks(repaired, quality or {})
    if expanded:
        actions.append({"action": "expand_short_heading_blocks", "count": expanded})

    repaired, deduped = remove_excess_repeated_paragraphs(repaired)
    if deduped:
        actions.append({"action": "remove_excess_repeated_paragraphs", "count": deduped})

    changed = repaired != before
    if changed:
        write_markdown(article_path, repaired)

    return write_repair_log(
        {
            "status": "repaired" if changed else "no_change",
            "changed": changed,
            "item_index": item_index,
            "attempt": attempt,
            "actions": actions,
            "before_characters": len(before),
            "after_characters": len(repaired),
        },
        run_key,
    )


def remove_banned_sentences(markdown: str) -> tuple[str, int]:
    removed = 0
    lines: list[str] = []
    for paragraph in markdown.split("\n\n"):
        if paragraph.startswith("#"):
            lines.append(paragraph)
            continue
        sentences = split_japanese_sentences(paragraph)
        kept = []
        for sentence in sentences:
            if any(pattern in sentence for pattern in BANNED_SENTENCE_PATTERNS):
                removed += 1
                continue
            kept.append(sentence)
        lines.append("".join(kept).strip())
    cleaned = "\n\n".join(part for part in lines if part.strip())
    return cleaned.rstrip() + "\n", removed


def split_japanese_sentences(paragraph: str) -> list[str]:
    if not paragraph.strip():
        return []
    parts = re.findall(r"[^。！？!?]+[。！？!?]?", paragraph, flags=re.DOTALL)
    return [part.strip() for part in parts if part.strip()]


def rename_generic_headings(markdown: str) -> tuple[str, int]:
    replacements = {
        "## 導入前チェックリスト": "## 実務で確認しておきたいポイント",
        "## 申請前のチェックリスト": "## 申請前に整理したい資料と判断基準",
        "## 実務チェックリスト": "## 現場運用で確認したいポイント",
        "## 導入時のチェックリスト": "## 導入時に整えたい社内運用",
        "## 対応前チェックリスト": "## 対応前に整理したい社内情報",
        "## 確認チェックリスト": "## 確認時に見落としやすい論点",
        "## 社労士に相談した方がよいケース": "## 社内で判断に迷いやすい場面",
    }
    count = 0
    for before, after in replacements.items():
        if before in markdown:
            markdown = markdown.replace(before, after)
            count += 1
    return markdown, count


def expand_short_heading_blocks(markdown: str, quality: dict[str, Any]) -> tuple[str, int]:
    short_blocks = quality.get("short_heading_blocks")
    if not isinstance(short_blocks, list) or not short_blocks:
        short_blocks = [
            block
            for block in measure_heading_body_lengths(markdown)
            if int(block.get("body_length") or 0) < 220 and int(block.get("level") or 0) in {2, 3, 4}
        ]
    targets = {
        (int(block.get("level") or 0), str(block.get("heading") or ""))
        for block in short_blocks
        if isinstance(block, dict)
    }
    if not targets:
        return markdown, 0

    headings = list(re.finditer(r"^(#{2,4})\s+(.+)$", markdown, flags=re.MULTILINE))
    inserts: list[tuple[int, str]] = []
    expanded = 0
    for index, match in enumerate(headings):
        level = len(match.group(1))
        heading = match.group(2).strip()
        if (level, heading) not in targets:
            continue
        next_start = len(markdown)
        for next_match in headings[index + 1 :]:
            if len(next_match.group(1)) <= level:
                next_start = next_match.start()
                break
        parent_heading = nearest_parent_heading(headings, index, level) or heading
        support = support_paragraph(parent_heading, heading, expanded)
        if support in markdown[match.end() : next_start]:
            continue
        inserts.append((next_start, "\n\n" + support.rstrip() + "\n"))
        expanded += 1

    for position, text in sorted(inserts, key=lambda row: row[0], reverse=True):
        markdown = markdown[:position].rstrip() + text + markdown[position:]
    return markdown.rstrip() + "\n", expanded


def nearest_parent_heading(headings: list[re.Match[str]], index: int, level: int) -> str | None:
    if level <= 2:
        return None
    for previous in reversed(headings[:index]):
        if len(previous.group(1)) < level:
            return previous.group(2).strip()
    return None


def support_paragraph(heading: str, subheading: str, index: int) -> str:
    template = SAFE_SUPPORT_PARAGRAPHS[index % len(SAFE_SUPPORT_PARAGRAPHS)]
    return template.format(heading=heading, subheading=subheading)


def remove_excess_repeated_paragraphs(markdown: str) -> tuple[str, int]:
    paragraphs = markdown.split("\n\n")
    seen: dict[str, int] = {}
    output: list[str] = []
    removed = 0
    for paragraph in paragraphs:
        normalized = re.sub(r"\s+", "", paragraph)
        if len(normalized) < 45 or paragraph.startswith("#"):
            output.append(paragraph)
            continue
        count = seen.get(normalized, 0)
        seen[normalized] = count + 1
        if count >= 2:
            removed += 1
            continue
        output.append(paragraph)
    return "\n\n".join(output).rstrip() + "\n", removed


def write_repair_log(payload: dict[str, Any], run_key: str | None = None) -> dict[str, Any]:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(LOGS_DIR / "article_repair_latest.json", payload)
    write_json(LOGS_DIR / f"article-repair-{timestamp}.json", payload)
    if run_key:
        safe = "".join(char if char.isalnum() else "-" for char in run_key).strip("-") or timestamp
        run_dir = LOGS_DIR / "runs" / safe
        write_json(run_dir / f"article_repair_item_{payload.get('item_index') or 'latest'}_attempt_{payload.get('attempt')}.json", payload)
    return payload
