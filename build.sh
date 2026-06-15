#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
IMAGE="lizenztool"
VERSION=$(date +"%Y%m%d_%H%M")
ARCHIVE="${IMAGE}_${VERSION}.tar.gz"

# Deployment (optional) – override via argument or environment variable
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/lizenztool}"

# ── Helper functions ───────────────────────────────────────────────────────────
info()    { echo "▸ $*"; }
success() { echo "✓ $*"; }
die()     { echo "✗ $*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  -d, --deploy USER@HOST   Build image and deploy directly to server
  -p, --path PATH          Target path on the server (default: /opt/lizenztool)
  -h, --help               Show this help

Environment variables:
  DEPLOY_USER, DEPLOY_HOST, DEPLOY_PATH

Examples:
  $0                              Build locally only
  $0 --deploy root@myserver.com   Build and deploy
EOF
}

# ── Parse arguments ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    -d|--deploy)
      DEPLOY_USER="${2%%@*}"
      DEPLOY_HOST="${2##*@}"
      shift 2
      ;;
    -p|--path)
      DEPLOY_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage; exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

# ── Check Docker ───────────────────────────────────────────────────────────────
command -v docker &>/dev/null || die "Docker not found"

# ── Build image ────────────────────────────────────────────────────────────────
info "Building image '${IMAGE}:${VERSION}'…"
docker build --tag "${IMAGE}:${VERSION}" --tag "${IMAGE}:latest" .
success "Image built: ${IMAGE}:${VERSION}"

# ── Create archive ─────────────────────────────────────────────────────────────
info "Exporting image to '${ARCHIVE}'…"
docker save "${IMAGE}:${VERSION}" | gzip > "${ARCHIVE}"
SIZE=$(du -sh "${ARCHIVE}" | cut -f1)
success "Archive created: ${ARCHIVE} (${SIZE})"

# ── Deployment (optional) ──────────────────────────────────────────────────────
if [[ -z "$DEPLOY_HOST" ]]; then
  info "No deployment target specified – local archive created only."
  info "To deploy: $0 --deploy USER@HOST"
  exit 0
fi

REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"
info "Deploying to ${REMOTE}:${DEPLOY_PATH}…"

# Create directory and transfer files
ssh "${REMOTE}" "mkdir -p '${DEPLOY_PATH}'"
scp "${ARCHIVE}" docker-compose.yml Caddyfile "${REMOTE}:${DEPLOY_PATH}/"

# On the server: load and start
ssh "${REMOTE}" bash <<REMOTE_SCRIPT
set -euo pipefail
cd "${DEPLOY_PATH}"

echo "▸ Loading image…"
docker load < "${ARCHIVE}"

echo "▸ Starting container…"
docker compose up -d --remove-orphans

echo "▸ Cleaning up archive…"
rm -f "${ARCHIVE}"

echo "✓ Deployment complete on ${REMOTE}:${DEPLOY_PATH}"
REMOTE_SCRIPT

success "Deployment complete."
rm -f "${ARCHIVE}"
