#!/bin/zsh
# Daily purge of unused Quill/content images (candidates + Sunday full sweep).
# Invoked by cron — not by web request handlers.
# Marker: MAP:purge_unused_content_images

set -euo pipefail

ROOT="/Users/benjaminraywalker/Documents/work/math_assessments/repository"
VENV_PYTHON="${ROOT}/.venv/bin/python"
MANAGE="${ROOT}/math_assessment_platform/manage.py"
LOG_DIR="${ROOT}/math_assessment_platform/logs"
LOG_FILE="${LOG_DIR}/purge_unused_content_images.log"

mkdir -p "${LOG_DIR}"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  cd "${ROOT}/math_assessment_platform"
  "${VENV_PYTHON}" "${MANAGE}" purge_unused_content_images
} >> "${LOG_FILE}" 2>&1
