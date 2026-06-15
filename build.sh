#!/usr/bin/env bash
set -euo pipefail

# ── Konfiguration ─────────────────────────────────────────────────────────────
IMAGE="lizenztool"
VERSION=$(date +"%Y%m%d_%H%M")
ARCHIVE="${IMAGE}_${VERSION}.tar.gz"

# Deployment (optional) – per Argument oder Umgebungsvariable überschreibbar
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/lizenztool}"

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
info()    { echo "▸ $*"; }
success() { echo "✓ $*"; }
die()     { echo "✗ $*" >&2; exit 1; }

usage() {
  cat <<EOF
Verwendung: $0 [OPTIONEN]

Optionen:
  -d, --deploy USER@HOST   Image bauen und direkt auf Server deployen
  -p, --path PATH          Zielpfad auf dem Server (Standard: /opt/lizenztool)
  -h, --help               Diese Hilfe anzeigen

Umgebungsvariablen:
  DEPLOY_USER, DEPLOY_HOST, DEPLOY_PATH

Beispiele:
  $0                              Nur lokal bauen
  $0 --deploy root@meinserver.de  Bauen und deployen
EOF
}

# ── Argumente parsen ──────────────────────────────────────────────────────────
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
      die "Unbekannte Option: $1"
      ;;
  esac
done

# ── Docker prüfen ─────────────────────────────────────────────────────────────
command -v docker &>/dev/null || die "Docker nicht gefunden"

# ── Image bauen ───────────────────────────────────────────────────────────────
info "Baue Image '${IMAGE}:${VERSION}'…"
docker build --tag "${IMAGE}:${VERSION}" --tag "${IMAGE}:latest" .
success "Image gebaut: ${IMAGE}:${VERSION}"

# ── Archiv erstellen ──────────────────────────────────────────────────────────
info "Exportiere Image nach '${ARCHIVE}'…"
docker save "${IMAGE}:${VERSION}" | gzip > "${ARCHIVE}"
SIZE=$(du -sh "${ARCHIVE}" | cut -f1)
success "Archiv erstellt: ${ARCHIVE} (${SIZE})"

# ── Deployment (optional) ─────────────────────────────────────────────────────
if [[ -z "$DEPLOY_HOST" ]]; then
  info "Kein Deployment-Ziel angegeben – nur lokales Archiv erstellt."
  info "Zum Deployen: $0 --deploy USER@HOST"
  exit 0
fi

REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"
info "Deploye auf ${REMOTE}:${DEPLOY_PATH}…"

# Verzeichnis anlegen und Dateien übertragen
ssh "${REMOTE}" "mkdir -p '${DEPLOY_PATH}'"
scp "${ARCHIVE}" docker-compose.yml Caddyfile "${REMOTE}:${DEPLOY_PATH}/"

# Auf dem Server: laden und starten
ssh "${REMOTE}" bash <<REMOTE_SCRIPT
set -euo pipefail
cd "${DEPLOY_PATH}"

echo "▸ Lade Image…"
docker load < "${ARCHIVE}"

echo "▸ Starte Container…"
docker compose up -d --remove-orphans

echo "▸ Räume altes Archiv auf…"
rm -f "${ARCHIVE}"

echo "✓ Deployment abgeschlossen auf ${REMOTE}:${DEPLOY_PATH}"
REMOTE_SCRIPT

success "Deployment abgeschlossen."
rm -f "${ARCHIVE}"
