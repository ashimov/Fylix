#!/usr/bin/env bash
# Restore from an age-encrypted backup archive.
#
# Usage: ./scripts/restore.sh <backup-file.tar.age>
#
# DESTRUCTIVE — overwrites current DB, MinIO bucket, and master_key.
# Stops the stack, restores, restarts. Asks for confirmation.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup-file.tar.age>" >&2
  exit 2
fi

BACKUP="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGE_KEY="$REPO_ROOT/secrets/age-backup.key"

if [[ ! -f "$BACKUP" ]]; then
  echo "ERROR: backup file not found: $BACKUP" >&2
  exit 1
fi
if [[ ! -f "$AGE_KEY" ]]; then
  echo "ERROR: age private key not found at $AGE_KEY" >&2
  exit 1
fi
if ! command -v age >/dev/null 2>&1; then
  echo "ERROR: age not installed." >&2
  exit 1
fi

echo "*** WARNING: RESTORE WILL OVERWRITE EXISTING STATE ***"
echo "Backup: $BACKUP"
read -r -p "Type 'RESTORE' to continue: " confirm
[[ "$confirm" == "RESTORE" ]] || { echo "Aborted."; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "[1/5] Decrypting..."
age -d -i "$AGE_KEY" -o "$STAGE/backup.tar" "$BACKUP"
tar -xf "$STAGE/backup.tar" -C "$STAGE"

PGDUMP=$(ls "$STAGE"/pgdump-*.sql 2>/dev/null | head -1)
MINIO_TAR=$(ls "$STAGE"/minio-*.tar 2>/dev/null | head -1)
MKEY="$STAGE/master_key"

if [[ -z "$PGDUMP" || -z "$MINIO_TAR" || ! -f "$MKEY" ]]; then
  echo "ERROR: archive missing expected files." >&2
  exit 1
fi

echo "[2/5] Restoring master_key..."
cp "$MKEY" "$REPO_ROOT/secrets/master_key"
chmod 400 "$REPO_ROOT/secrets/master_key"

echo "[3/5] Restoring Postgres..."
# Must wipe first — pg_restore -c is fine but clean slate is safer.
docker compose exec -T postgres dropdb -U "${POSTGRES_USER:-fylix}" --if-exists "${POSTGRES_DB:-fylix}"
docker compose exec -T postgres createdb -U "${POSTGRES_USER:-fylix}" "${POSTGRES_DB:-fylix}"
docker compose exec -T postgres pg_restore -U "${POSTGRES_USER:-fylix}" -d "${POSTGRES_DB:-fylix}" < "$PGDUMP"

echo "[4/5] Restoring MinIO..."
tar -xf "$MINIO_TAR" -C "$STAGE"
MINIO_DIR=$(ls -d "$STAGE"/minio-* 2>/dev/null | grep -v '\.tar$' | head -1)
docker compose cp "$MINIO_DIR" minio:/tmp/restore-staging
docker compose exec -T minio mc alias set local http://localhost:9000 \
  "$(grep ^MINIO_ROOT_USER "$REPO_ROOT/.env" | cut -d= -f2)" \
  "$(grep ^MINIO_ROOT_PASSWORD "$REPO_ROOT/.env" | cut -d= -f2)" >/dev/null
docker compose exec -T minio mc rb --force "local/${MINIO_BUCKET:-transfers}" 2>/dev/null || true
docker compose exec -T minio mc mb "local/${MINIO_BUCKET:-transfers}"
docker compose exec -T minio mc mirror /tmp/restore-staging "local/${MINIO_BUCKET:-transfers}"
docker compose exec -T minio rm -rf /tmp/restore-staging

echo "[5/5] Restarting api + worker..."
docker compose restart api worker
sleep 5

echo ""
echo "=== RESTORE COMPLETE ==="
echo "Smoke test: curl -k https://localhost/healthz"
