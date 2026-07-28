#!/bin/zsh
# Daily purge of explorer Trash items older than 30 days.
# Invoked by cron — not by web request handlers.

set -euo pipefail

ROOT="/Users/benjaminraywalker/Documents/work/math_assessments/repository"
VENV_PYTHON="${ROOT}/.venv/bin/python"
MANAGE="${ROOT}/math_assessment_platform/manage.py"
LOG_DIR="${ROOT}/math_assessment_platform/logs"
LOG_FILE="${LOG_DIR}/purge_trashed_branch_groups.log"

mkdir -p "${LOG_DIR}"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  cd "${ROOT}/math_assessment_platform"
  "${VENV_PYTHON}" "${MANAGE}" purge_trashed_branch_groups
} >> "${LOG_FILE}" 2>&1
