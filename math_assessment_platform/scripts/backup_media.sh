#!/bin/bash
# Daily archive of media + private_files for production (map.flippedmath.com Droplet).
# Do NOT install on local Mac — server only.
#
# Cron (server, idempotent marker):
#   10 3 * * * /usr/local/bin/map-backup-media.sh # MAP:backup_media
#
# Archives:
#   math_assessment_platform/media/
#   math_assessment_platform/private_files/

set -euo pipefail

MAP_ROOT="${MAP_ROOT:-/var/www/map}"
APP_DIR="${MAP_ROOT}/math_assessment_platform"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/map}"
LOG_FILE="${LOG_FILE:-/var/log/map-media-backup.log}"
KEEP_DAYS="${KEEP_DAYS:-14}"

MEDIA_DIR="${APP_DIR}/media"
PRIVATE_DIR="${APP_DIR}/private_files"

mkdir -p "${BACKUP_DIR}"
touch "${LOG_FILE}"

log() {
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ===== $*" >> "${LOG_FILE}"
}

STAMP="$(date '+%Y-%m-%d_%H%M%S')"
OUT="${BACKUP_DIR}/map_media_${STAMP}.tar.gz"

log "Starting media archive to ${OUT}"

if [[ ! -d "${MEDIA_DIR}" && ! -d "${PRIVATE_DIR}" ]]; then
  log "ERROR: neither ${MEDIA_DIR} nor ${PRIVATE_DIR} exists"
  exit 1
fi

# Build tar args for paths that exist (relative to APP_DIR)
TAR_PATHS=()
[[ -d "${MEDIA_DIR}" ]] && TAR_PATHS+=("media")
[[ -d "${PRIVATE_DIR}" ]] && TAR_PATHS+=("private_files")

if [[ ${#TAR_PATHS[@]} -eq 0 ]]; then
  log "ERROR: no media directories to archive"
  exit 1
fi

if tar -C "${APP_DIR}" -czf "${OUT}.partial" "${TAR_PATHS[@]}"; then
  mv "${OUT}.partial" "${OUT}"
  log "OK archive $(du -h "${OUT}" | awk '{print $1}') paths=${TAR_PATHS[*]}"
else
  rm -f "${OUT}.partial"
  log "ERROR tar failed"
  exit 1
fi

find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'map_media_*.tar.gz' -mtime "+${KEEP_DAYS}" -print -delete \
  >> "${LOG_FILE}" 2>&1 || true

log "Done (retention ${KEEP_DAYS} days)"
