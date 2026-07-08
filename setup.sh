#!/usr/bin/env bash
set -euo pipefail

# Fylix — First-time setup
# Usage: ./setup.sh

echo "=== Fylix Setup ==="

# --- Check prerequisites ---
command -v docker >/dev/null 2>&1 || { echo "Error: docker is required (https://docs.docker.com/get-docker/)."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Error: Docker Compose v2 is required (docker compose ... not found)."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "Error: openssl is required."; exit 1; }

# --- Environment ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit it with your values (especially SMTP, HCAPTCHA, MAXMIND for prod)."
fi

# --- Master encryption key (32 raw bytes — NOT base64) ---
# Crypto-shredding note: every transfer's file key is wrapped with this key.
# If secrets/master_key is lost, ALL stored ciphertext becomes permanently
# unrecoverable (by design). Back up the hex value offline before relying on
# this instance for anything real — see docs/KEY_ROTATION.md.
if [ -f secrets/master_key ]; then
  echo "secrets/master_key already exists — skipping generation."
else
  echo "Generating master key (secrets/master_key, 32 raw bytes)..."
  ./scripts/gen_master_key.sh
fi

# --- Dev TLS certificate for https://localhost ---
if [ -f nginx/certs/fullchain.pem ]; then
  echo "nginx/certs already populated — skipping cert generation."
else
  echo "Generating self-signed dev TLS cert..."
  ./scripts/gen_dev_certs.sh
fi

# --- Runtime bind-mount dirs (must exist and be owned by you, not root) ---
# If docker creates these itself they end up root-owned and the api container
# (uid 1001) cannot write to the staging dir.
mkdir -p data/staging data/geoip

# --- Bring up the stack ---
echo "Building and starting the docker compose stack (dev profile)..."
docker compose --profile dev up -d --build

echo "Waiting for the API to become healthy..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -kfs https://localhost/healthz >/dev/null 2>&1; then
    echo "API is healthy."
    break
  fi
  sleep 3
done

echo "Applying database migrations..."
docker compose exec -T api alembic upgrade head

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your configuration (SMTP relay, hCaptcha, MaxMind GeoIP, Telegram alerts)."
echo "  2. Create the first admin:"
echo "       make admin-create email=admin@example.com pw='SomeStrongPassword!123'"
echo "  3. Open:"
echo "       https://localhost/        (public upload portal)"
echo "       https://localhost/admin/  (admin panel)"
echo "       http://localhost:8025/    (mailpit — dev email capture)"
echo "  4. Optional, for encrypted backups: make age-key"
echo "  5. Using Claude Code? CLAUDE.md has all the context."
