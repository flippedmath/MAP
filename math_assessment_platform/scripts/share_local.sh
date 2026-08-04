#!/usr/bin/env bash
# Publish the local Django runserver to a temporary public HTTPS URL
# via Cloudflare's quick tunnel (*.trycloudflare.com). No account needed.
#
# Usage:
#   1. Start Django as usual (e.g. manage.py runserver)
#   2. In another terminal: ./scripts/share_local.sh
#   3. Share the printed https://….trycloudflare.com link
#   4. Ctrl+C stops the tunnel (link stops working)
#
# Optional: SHARE_PORT=8000 ./scripts/share_local.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN="$PLATFORM_DIR/bin/cloudflared"
PORT="${SHARE_PORT:-8000}"
LOCAL_URL="http://127.0.0.1:${PORT}"

download_cloudflared() {
  mkdir -p "$PLATFORM_DIR/bin"
  local arch
  arch="$(uname -m)"
  local asset
  case "$arch" in
    arm64|aarch64) asset="cloudflared-darwin-arm64.tgz" ;;
    x86_64) asset="cloudflared-darwin-amd64.tgz" ;;
    *)
      echo "Unsupported Mac architecture: $arch" >&2
      exit 1
      ;;
  esac
  echo "Downloading cloudflared ($asset)…"
  local tmp
  tmp="$(mktemp -t cloudflared.XXXXXX.tgz)"
  curl -fsSL -o "$tmp" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/${asset}"
  tar -xzf "$tmp" -C "$PLATFORM_DIR/bin"
  rm -f "$tmp"
  chmod +x "$BIN"
}

if [[ ! -x "$BIN" ]]; then
  download_cloudflared
fi

if ! curl -fsS --max-time 2 "$LOCAL_URL" >/dev/null 2>&1; then
  echo "Nothing is responding at $LOCAL_URL." >&2
  echo "Start Django first, e.g.:" >&2
  echo "  cd math_assessment_platform && python manage.py runserver" >&2
  exit 1
fi

echo "Tunneling $LOCAL_URL → temporary public URL (Ctrl+C to stop)…"
echo "Look for a line like: https://….trycloudflare.com"
echo

exec "$BIN" tunnel --url "$LOCAL_URL"
