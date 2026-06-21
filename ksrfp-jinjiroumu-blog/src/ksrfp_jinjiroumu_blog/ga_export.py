from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .io_utils import read_text, to_int


@dataclass
class GASection:
    title: str
    start_date: str | None
    end_date: str | None
    header: list[str]
    rows: list[list[str]]


def parse_ga_sections(path: Path) -> list[GASection]:
    lines = read_text(path).splitlines()
    sections: list[GASection] = []
    pending_title = ""
    pending_start: str | None = None
    pending_end: str | None = None
    header: list[str] | None = None
    rows: list[list[str]] = []

    def flush() -> None:
        nonlocal header, rows, pending_title, pending_start, pending_end
        if header:
            sections.append(
                GASection(
                    title=pending_title or header[0],
                    start_date=pending_start,
                    end_date=pending_end,
                    header=header,
                    rows=rows,
                )
            )
        header = None
        rows = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            if header:
                flush()
            comment = line.lstrip("#").strip()
            if comment.startswith("開始日:"):
                pending_start = comment.split(":", 1)[1].strip()
            elif comment.startswith("終了日:"):
                pending_end = comment.split(":", 1)[1].strip()
            elif comment and set(comment) != {"-"}:
                pending_title = comment
            continue

        parsed = next(csv.reader([raw_line]))
        if header is None:
            header = parsed
        else:
            rows.append(parsed)

    flush()
    return sections


def summarize_ga_sections(path: Path) -> dict[str, object]:
    sections = parse_ga_sections(path)
    section_summaries: list[dict[str, object]] = []
    for section in sections:
        summary: dict[str, object] = {
            "title": section.title,
            "start_date": section.start_date,
            "end_date": section.end_date,
            "header": section.header,
            "row_count": len(section.rows),
        }
        if len(section.header) >= 2 and section.rows:
            metric_name = section.header[-1]
            numeric_values = [to_int(row[-1]) for row in section.rows if row]
            if numeric_values:
                summary.update(
                    {
                        "metric": metric_name,
                        "total": sum(numeric_values),
                        "max": max(numeric_values),
                        "min": min(numeric_values),
                    }
                )
        section_summaries.append(summary)
    return {"section_count": len(sections), "sections": section_summaries}

