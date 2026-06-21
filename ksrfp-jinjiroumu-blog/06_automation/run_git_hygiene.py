#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ksrfp_jinjiroumu_blog.io_utils import write_json, write_markdown  # noqa: E402
from ksrfp_jinjiroumu_blog.paths import LOGS_DIR  # noqa: E402


GENERATED_PREFIXES = (
    "00_project/backups/",
    "01_inputs/newsletters/drive-downloads/",
    "02_analysis/cannibalization/",
    "02_analysis/seo/",
    "02_analysis/topic-selection/",
    "03_generated/articles/",
    "03_generated/images/",
    "03_generated/outlines/",
    "03_generated/review-texts/",
    "03_generated/wordpress-payloads/",
    "04_wordpress/",
    "05_drive/",
    "07_logs/",
    "08_state/",
    "config/secrets/",
    ".playwright/",
)

ALLOWED_GENERATED_PATHS = {
    "01_inputs/newsletters/drive-downloads/.gitkeep",
    "02_analysis/cannibalization/README.md",
    "02_analysis/seo/README.md",
    "02_analysis/topic-selection/README.md",
    "03_generated/articles/.gitkeep",
    "03_generated/images/.gitkeep",
    "03_generated/outlines/.gitkeep",
    "03_generated/review-texts/.gitkeep",
    "03_generated/wordpress-payloads/.gitkeep",
    "04_wordpress/README.md",
    "05_drive/README.md",
    "07_logs/.gitkeep",
    "07_logs/README.md",
    "08_state/.gitkeep",
    "08_state/README.md",
    "config/secrets/README.md",
}

SECRET_PREFIXES = (
    "config/secrets/",
    ".env",
)


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def git_root() -> Path:
    result = run_git(["rev-parse", "--show-toplevel"], PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git rev-parse failed")
    return Path(result.stdout.strip())


def project_arg(root: Path) -> str:
    return str(PROJECT_ROOT.relative_to(root))


def to_project_relative(path_from_root: str, project: str) -> str:
    prefix = f"{project}/"
    if path_from_root == project:
        return ""
    if path_from_root.startswith(prefix):
        return path_from_root[len(prefix) :]
    return path_from_root


def tracked_files(root: Path, project: str) -> list[str]:
    result = run_git(["ls-files", "--", project], root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return [
        to_project_relative(line.strip(), project)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def untracked_files(root: Path, project: str) -> list[str]:
    result = run_git(["ls-files", "--others", "--exclude-standard", "--", project], root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files --others failed")
    return [
        to_project_relative(line.strip(), project)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def status_entries(root: Path, project: str) -> list[dict[str, str]]:
    result = run_git(["status", "--porcelain=v1", "--untracked-files=all", "--", project], root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    entries: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        raw_path = line[3:] if len(line) > 3 else ""
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[1]
        entries.append(
            {
                "status": status,
                "path": to_project_relative(raw_path.strip(), project),
            }
        )
    return entries


def is_generated_path(path: str) -> bool:
    if path in ALLOWED_GENERATED_PATHS:
        return False
    return any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)


def is_secret_path(path: str) -> bool:
    if path == "config/secrets/README.md":
        return False
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in SECRET_PREFIXES)


def build_payload() -> dict[str, Any]:
    root = git_root()
    project = project_arg(root)
    tracked = tracked_files(root, project)
    untracked = untracked_files(root, project)
    status = status_entries(root, project)
    tracked_generated = sorted(path for path in tracked if is_generated_path(path))
    tracked_secrets = sorted(path for path in tracked if is_secret_path(path))
    unsafe_status = [
        entry
        for entry in status
        if is_generated_path(entry["path"]) and entry["status"].strip() not in {"D"}
    ]
    failed_checks = []
    if tracked_generated:
        failed_checks.append("tracked_generated_outputs")
    if tracked_secrets:
        failed_checks.append("tracked_secret_paths")
    if untracked:
        failed_checks.append("untracked_not_ignored")
    if unsafe_status:
        failed_checks.append("generated_outputs_still_dirty")
    return {
        "status": "ok" if not failed_checks else "partial",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_root": str(root),
        "project_root": str(PROJECT_ROOT),
        "project_path": project,
        "failed_checks": failed_checks,
        "tracked_generated_outputs": tracked_generated,
        "tracked_secret_paths": tracked_secrets,
        "untracked_not_ignored": untracked,
        "generated_output_status_entries": unsafe_status,
        "status_entries": status,
        "summary": {
            "tracked_generated_output_count": len(tracked_generated),
            "tracked_secret_path_count": len(tracked_secrets),
            "untracked_not_ignored_count": len(untracked),
            "generated_output_status_entry_count": len(unsafe_status),
            "status_entry_count": len(status),
        },
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Git衛生チェック",
        "",
        f"- ステータス: {payload.get('status')}",
        f"- 生成日時: {payload.get('generated_at')}",
        f"- Gitルート: {payload.get('git_root')}",
        f"- 対象: {payload.get('project_path')}",
        "",
        "## 失敗チェック",
        "",
    ]
    failed = payload.get("failed_checks")
    if isinstance(failed, list) and failed:
        lines.extend(f"- {item}" for item in failed)
    else:
        lines.append("- なし")
    sections = [
        ("Git追跡中の生成物", "tracked_generated_outputs"),
        ("Git追跡中の秘密情報パス", "tracked_secret_paths"),
        ("無視されていない未追跡ファイル", "untracked_not_ignored"),
    ]
    for title, key in sections:
        lines.extend(["", f"## {title}", ""])
        values = payload.get(key)
        if isinstance(values, list) and values:
            lines.extend(f"- `{value}`" for value in values)
        else:
            lines.append("- なし")
    return "\n".join(lines).rstrip() + "\n"


def write_logs(payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(LOGS_DIR / "git_hygiene_latest.json", payload)
    write_json(LOGS_DIR / f"git-hygiene-{timestamp}.json", payload)
    write_markdown(LOGS_DIR / "git_hygiene_latest.md", render_report(payload))


def main() -> int:
    try:
        payload = build_payload()
    except Exception as exc:
        payload = {
            "status": "error",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    write_logs(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
