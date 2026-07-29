#!/bin/zsh
# Close upcoming assessments whose auto-open window has ended.
# Production server cron only (every minute) — not for local Mac.
# Marker: MAP:close_expired_upcoming_assessments

set -euo pipefail

ROOT="/Users/benjaminraywalker/Documents/work/math_assessments/repository"
VENV_PYTHON="${ROOT}/.venv/bin/python"
MANAGE="${ROOT}/math_assessment_platform/manage.py"
LOG_DIR="${ROOT}/math_assessment_platform/logs"
LOG_FILE="${LOG_DIR}/close_expired_upcoming_assessments.log"

mkdir -p "${LOG_DIR}"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  cd "${ROOT}/math_assessment_platform"
  "${VENV_PYTHON}" "${MANAGE}" close_expired_upcoming_assessments
} >> "${LOG_FILE}" 2>&1
