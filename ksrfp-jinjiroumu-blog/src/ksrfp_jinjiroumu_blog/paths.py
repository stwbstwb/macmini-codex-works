from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUTS_DIR = PROJECT_ROOT / "01_inputs"
ANALYSIS_DIR = PROJECT_ROOT / "02_analysis"
GENERATED_DIR = PROJECT_ROOT / "03_generated"
LOGS_DIR = PROJECT_ROOT / "07_logs"
STATE_DIR = PROJECT_ROOT / "08_state"
DOCS_DIR = PROJECT_ROOT / "docs"
CONFIG_DIR = PROJECT_ROOT / "config"
DRIVE_DIR = PROJECT_ROOT / "05_drive"
WORDPRESS_DIR = PROJECT_ROOT / "04_wordpress"

GSC_DIR = INPUTS_DIR / "gsc"
GA_DIR = INPUTS_DIR / "ga"
POSTED_ARTICLES_DIR = INPUTS_DIR / "posted-articles"
PROMPTS_DIR = INPUTS_DIR / "prompts"
NEWSLETTERS_DIR = INPUTS_DIR / "newsletters"
LOCAL_NEWSLETTER_DIR = NEWSLETTERS_DIR / "local-samples"
DRIVE_NEWSLETTER_DIR = NEWSLETTERS_DIR / "drive-downloads"

SEO_ANALYSIS_DIR = ANALYSIS_DIR / "seo"
CANNIBALIZATION_DIR = ANALYSIS_DIR / "cannibalization"
TOPIC_SELECTION_DIR = ANALYSIS_DIR / "topic-selection"
WORDPRESS_PAYLOAD_DIR = GENERATED_DIR / "wordpress-payloads"


def ensure_output_dirs() -> None:
    for path in [
        SEO_ANALYSIS_DIR,
        CANNIBALIZATION_DIR,
        TOPIC_SELECTION_DIR,
        GENERATED_DIR / "articles",
        GENERATED_DIR / "outlines",
        GENERATED_DIR / "images",
        GENERATED_DIR / "review-texts",
        WORDPRESS_PAYLOAD_DIR,
        LOGS_DIR,
        STATE_DIR,
        DOCS_DIR,
        DRIVE_DIR,
        WORDPRESS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
