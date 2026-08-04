# Deploy MAP to a DigitalOcean Droplet (Ubuntu)

Target site: `https://map.flippedmath.com`

## Layout on the server

- App: `/var/www/map/` (git clone of this repo)
- Django project dir: `/var/www/map/math_assessment_platform/`
- Env file: `/var/www/map/.env` (never commit)
- Venv: `/var/www/map/.venv/`
- Gunicorn service: `map-gunicorn.service`
- Nginx site: `map.flippedmath.com`

## First-time install (summary)

1. Point DNS A record `map` → Droplet IPv4; wait for propagation.
2. Install packages: `python3-venv`, `postgresql`, `nginx`, `certbot`, `python3-certbot-nginx`, git, build tools.
3. Create Postgres database/role; write credentials into `/var/www/map/.env`.
4. `git clone` and checkout the deploy branch (`main` or `final_test_branch`).
5. Create venv, `pip install -r requirements.txt`.
6. Load schema / seed (see `db-promote.md`).
7. `collectstatic`, configure Gunicorn + Nginx, `certbot --nginx`.
8. Install cron jobs with MAP markers (see `.cursor/rules/scheduled-jobs-deploy.mdc`), including `MAP:backup_postgres` and `MAP:backup_media` (daily dumps under `/var/backups/map/`).

## Database backups (production)

- Script: `math_assessment_platform/scripts/backup_postgres.sh`
- Cron marker: `MAP:backup_postgres` (daily 03:05)
- Output: `/var/backups/map/map_db_YYYY-MM-DD_HHMMSS.sql.gz` (kept 14 days)
- Log: `/var/log/map-db-backup.log`

## Media backups (production)

- Script: `math_assessment_platform/scripts/backup_media.sh`
- Cron marker: `MAP:backup_media` (daily 03:10)
- Output: `/var/backups/map/map_media_YYYY-MM-DD_HHMMSS.tar.gz` (kept 14 days) — includes `media/` and `private_files/`
- Log: `/var/log/map-media-backup.log`
- This is **not** a full off-site copy; enable DigitalOcean Droplet backups and/or copy archives off the VPS periodically.

## Server `.env` keys

```
DEBUG=False
SECRET_KEY=...
ALLOWED_HOSTS=map.flippedmath.com
CSRF_TRUSTED_ORIGINS=https://map.flippedmath.com
PUBLIC_BASE_URL=https://map.flippedmath.com
DB_ACTUAL_NAME=...
SECRET_DB_USER=...
DB_USER_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=...
OUTGOING_SERVER_HOST=...
OUTGOING_SERVER_PORT_SMTP=465
EMAIL_USE_TLS=False
EMAIL_USE_SSL=True
```

## Pushing code updates

On the Droplet:

```bash
cd /var/www/map
git fetch origin
git checkout main   # or final_test_branch
git pull
source .venv/bin/activate
cd math_assessment_platform
pip install -r ../requirements.txt
python manage.py collectstatic --noinput
sudo systemctl restart map-gunicorn
```

## Useful commands

```bash
sudo systemctl status map-gunicorn
sudo journalctl -u map-gunicorn -f
sudo nginx -t && sudo systemctl reload nginx
```
