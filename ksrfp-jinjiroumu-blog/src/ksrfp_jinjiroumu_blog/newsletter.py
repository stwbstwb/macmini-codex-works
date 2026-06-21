from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

from pypdf import PdfReader


TOPIC_KEYWORDS = {
    "law_change": ["改正", "施行", "適用", "義務", "指針", "省令", "法"],
    "news": ["ニュース", "行政", "厚生労働省", "厚労省", "調査", "監督", "送検"],
    "subsidy": ["助成金", "奨励金", "補助金", "支給"],
    "labor_management": ["就業規則", "労働時間", "休業", "賃金", "ハラスメント", "社会保険", "雇用保険"],
}


@dataclass
class NewsletterTopic:
    pdf_name: str
    page_count: int
    section_group: str
    topic_title: str
    labels: list[str]
    score: int
    date_mentions: list[str]
    excerpt: str


def extract_pdf_text(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages), len(reader.pages)


def split_sections(text: str) -> list[tuple[str, str]]:
    normalized = re.sub(r"\r\n?", "\n", text)
    matches = list(re.finditer(r"^●(.+)$", normalized, flags=re.MULTILINE))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        title = match.group(1).strip()
        body = normalized[start:end].strip()
        if title and body:
            sections.append((title, body))
    if not sections and normalized.strip():
        sections.append(("全文", normalized.strip()))
    return sections


def _clean_pdf_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if re.fullmatch(r"[0-9０-９]+", line):
        return ""
    if re.match(r"人事労務だより\s+\d{4}（令和", line):
        return ""
    if line in {"発 行", "トピックス", "人事労務だより HR News"}:
        return ""
    if line.startswith("■"):
        return ""
    if line.startswith("〒231-0027") or line.startswith("電話:") or line.startswith("柏谷横浜社労士事務所"):
        return ""
    return line


def _is_heading_block(lines: list[str]) -> bool:
    text = " ".join(lines).strip()
    if not text:
        return False
    if len(lines) > 3 or len(text) > 95:
        return False
    if "。" in text or "です" in text or "ます" in text:
        return False
    if text.startswith(("【", "・", "※", "問", "答")):
        return False
    return True


def _looks_like_subtitle_line(line: str) -> bool:
    if not _is_heading_block([line]):
        return False
    if "は、" in line or "が、" in line or "を、" in line:
        return False
    source_markers = [
        "厚労省",
        "厚生労働省",
        "労働局",
        "労基署",
        "入管庁",
        "国交省",
        "内閣府",
        "山口県",
        "福島",
        "千葉",
        "福岡",
        "香川",
    ]
    if not any(marker in line for marker in source_markers):
        return False
    return True


def split_subtopics(section_title: str, body: str) -> list[tuple[str, str]]:
    lines = [_clean_pdf_line(line) for line in body.splitlines()]
    non_empty_lines = [line for line in lines if line]
    blocks: list[list[str]] = []
    current_block: list[str] = []
    for line in lines:
        if not line:
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue
        current_block.append(line)
    if current_block:
        blocks.append(current_block)

    topics: list[tuple[str, list[str]]] = []
    current_title = section_title
    current_body: list[str] = []
    found_heading = False

    for block in blocks:
        block_text = " ".join(block).strip()
        if _is_heading_block(block) and current_body:
            topics.append((current_title, current_body))
            current_title = block_text
            current_body = []
            found_heading = True
        elif _is_heading_block(block) and not current_body:
            current_title = block_text
            found_heading = True
        else:
            current_body.extend(block)

    if current_body:
        topics.append((current_title, current_body))

    if not found_heading or not topics:
        if len(non_empty_lines) > 2 and _is_heading_block([non_empty_lines[0]]):
            return [(non_empty_lines[0], "\n".join(non_empty_lines[1:]))]
        cleaned = "\n".join(non_empty_lines)
        return [(section_title, cleaned)] if cleaned else []

    merged: list[tuple[str, str]] = []
    for title, parts in topics:
        text = "\n".join(parts).strip()
        if not text:
            continue
        body_lines = [line for line in text.splitlines() if line.strip()]
        if title == section_title and len(body_lines) > 1 and _is_heading_block([body_lines[0]]):
            title = body_lines[0]
            text = "\n".join(body_lines[1:]).strip()
            body_lines = [line for line in text.splitlines() if line.strip()]
        if body_lines and len(title) < 25 and _looks_like_subtitle_line(body_lines[0]):
            title = f"{title} {body_lines[0]}".strip()
            text = "\n".join(body_lines[1:]).strip()
        merged.append((title, text))
    return merged or [(section_title, "\n".join(line for line in lines if line))]


def classify_topic(title: str, body: str) -> tuple[list[str], int]:
    target = f"{title}\n{body}"
    labels: list[str] = []
    score = 0
    for label, keywords in TOPIC_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in target)
        if hits:
            labels.append(label)
            score += hits
    if "中小企業" in target:
        score += 2
    if "厚生労働省" in target or "厚労省" in target:
        score += 2
    if "令和" in target or re.search(r"\d{4}年|\d+月\d+日", target):
        score += 1
    return labels, score


def extract_date_mentions(text: str) -> list[str]:
    patterns = [
        r"令和[0-9０-９]+年[0-9０-９]+月[0-9０-９]+日",
        r"令和[0-9０-９]+年[0-9０-９]+月",
        r"[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日",
        r"[0-9]{4}年[0-9]{1,2}月",
        r"[0-9]{1,2}月[0-9]{1,2}日",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text))
    deduped = list(dict.fromkeys(found))
    return deduped[:10]


def summarize_pdf(path: Path) -> dict[str, object]:
    text, page_count = extract_pdf_text(path)
    sections = split_sections(text)
    topics: list[NewsletterTopic] = []
    for section_title, body in sections:
        for topic_title, topic_body in split_subtopics(section_title, body):
            labels, score = classify_topic(topic_title, topic_body)
            excerpt = re.sub(r"\s+", " ", topic_body).strip()[:420]
            topics.append(
                NewsletterTopic(
                    pdf_name=path.name,
                    page_count=page_count,
                    section_group=section_title,
                    topic_title=topic_title,
                    labels=labels,
                    score=score,
                    date_mentions=extract_date_mentions(f"{topic_title}\n{topic_body}"),
                    excerpt=excerpt,
                )
            )
    topics.sort(key=lambda item: item.score, reverse=True)
    return {
        "pdf_name": path.name,
        "page_count": page_count,
        "character_count": len(text),
        "section_count": len(sections),
        "topics": [asdict(topic) for topic in topics],
    }
