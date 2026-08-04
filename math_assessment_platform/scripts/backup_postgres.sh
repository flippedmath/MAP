#!/bin/bash
# Daily Postgres dump for production (map.flippedmath.com Droplet).
# Do NOT install on local Mac — server only.
#
# Cron (server, idempotent marker):
#   5 3 * * * /usr/local/bin/map-backup-db.sh # MAP:backup_postgres
#
# Env: reads /var/www/map/.env (DB_ACTUAL_NAME, SECRET_DB_USER, DB_USER_PASSWORD, DB_HOST, DB_PORT).

set -euo pipefail

MAP_ROOT="${MAP_ROOT:-/var/www/map}"
ENV_FILE="${MAP_ROOT}/.env"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/map}"
LOG_FILE="${LOG_FILE:-/var/log/map-db-backup.log}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "${BACKUP_DIR}"
touch "${LOG_FILE}"

log() {
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ===== $*" >> "${LOG_FILE}"
}

if [[ ! -f "${ENV_FILE}" ]]; then
  log "ERROR: missing ${ENV_FILE}"
  exit 1
fi

# shellcheck disable=SC1090
set -a
# Strip surrounding single quotes from python-decouple style .env values
eval "$(
  python3 - "${ENV_FILE}" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
wanted = {
    "DB_ACTUAL_NAME",
    "SECRET_DB_USER",
    "DB_USER_PASSWORD",
    "DB_HOST",
    "DB_PORT",
}
for line in path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k not in wanted:
        continue
    v = v.strip().strip("'").strip('"')
    print(f"{k}={v!r}")
PY
)"
set +a

: "${DB_ACTUAL_NAME:?}"
: "${SECRET_DB_USER:?}"
: "${DB_USER_PASSWORD:?}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

STAMP="$(date '+%Y-%m-%d_%H%M%S')"
OUT="${BACKUP_DIR}/map_db_${STAMP}.sql.gz"

log "Starting dump to ${OUT}"

export PGPASSWORD="${DB_USER_PASSWORD}"
if pg_dump \
  --host="${DB_HOST}" \
  --port="${DB_PORT}" \
  --username="${SECRET_DB_USER}" \
  --dbname="${DB_ACTUAL_NAME}" \
  --no-owner \
  --no-acl \
  | gzip -c > "${OUT}.partial"
then
  mv "${OUT}.partial" "${OUT}"
  log "OK dump $(du -h "${OUT}" | awk '{print $1}')"
else
  rm -f "${OUT}.partial"
  log "ERROR pg_dump failed"
  exit 1
fi

# Prune old dumps
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'map_db_*.sql.gz' -mtime "+${KEEP_DAYS}" -print -delete \
  >> "${LOG_FILE}" 2>&1 || true

log "Done (retention ${KEEP_DAYS} days)"
