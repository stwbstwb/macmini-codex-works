#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/ug/Desktop/codex_works"
LOG_FILE="$REPO_DIR/github_backup.log"

cd "$REPO_DIR"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting GitHub backup"

  if [ ! -d ".git" ]; then
    git init
    git branch -M main
  fi

  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "https://github.com/stwbstwb/macmini-codex-works.git"
  fi

  git add -A

  if git diff --cached --quiet; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No changes to commit"
  else
    git commit -m "Auto backup $(date '+%Y-%m-%d %H:%M:%S')"
  fi

  git push -u origin main
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup complete"
} >>"$LOG_FILE" 2>&1

