from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = PROJECT_ROOT / "config"
ANALYSIS_DIR = PROJECT_ROOT / "02_analysis"
GENERATED_DIR = PROJECT_ROOT / "03_generated"
LOGS_DIR = PROJECT_ROOT / "07_logs"
STATE_DIR = PROJECT_ROOT / "08_state"
NOTIFICATIONS_DIR = LOGS_DIR / "notifications"
REWRITE_CANDIDATE_DIR = ANALYSIS_DIR / "rewrite-candidates"
REWRITE_BRIEF_DIR = GENERATED_DIR / "rewrite-briefs"
OUTLINES_DIR = GENERATED_DIR / "outlines"
ARTICLES_DIR = GENERATED_DIR / "articles"
IMAGES_DIR = GENERATED_DIR / "images"
DRIVE_READY_DIR = GENERATED_DIR / "drive-ready"
REWRITE_HISTORY_PATH = STATE_DIR / "rewrite_history.json"


def ensure_output_dirs() -> None:
    for path in [
        REWRITE_CANDIDATE_DIR,
        REWRITE_BRIEF_DIR,
        OUTLINES_DIR,
        ARTICLES_DIR,
        IMAGES_DIR,
        DRIVE_READY_DIR,
        LOGS_DIR,
        STATE_DIR,
        NOTIFICATIONS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
