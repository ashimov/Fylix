#!/usr/bin/env bash
# Encrypted backup of Fylix state: Postgres + MinIO + master_key.
#
# Usage: ./scripts/backup.sh [output-dir]
#
# Prereqs:
#   - 'age' installed on host
#   - secrets/age-backup.pub exists (run age-keygen.sh once)
#   - Docker stack up
#
# Produces:
#   <out>/fylix-backup-<timestamp>.tar.age
#
# Content (encrypted):
#   - pgdump-<ts>.sql       (pg_dump -Fc)
#   - minio-<ts>.tar        (objects from 'transfers' bucket)
#   - master_key            (copy of secrets/master_key)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="${1:-$REPO_ROOT/backups}"
PUB_KEY="$REPO_ROOT/secrets/age-backup.pub"
MASTER_KEY="$REPO_ROOT/secrets/master_key"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

if ! command -v age >/dev/null 2>&1; then
  echo "ERROR: age not installed. See https://age-encryption.org" >&2
  exit 1
fi
if [[ ! -f "$PUB_KEY" ]]; then
  echo "ERROR: age public key not found at $PUB_KEY — run scripts/age-keygen.sh" >&2
  exit 1
fi
if [[ ! -f "$MASTER_KEY" ]]; then
  echo "ERROR: master key not found at $MASTER_KEY" >&2
  exit 1
fi

TS="$(date -u +%Y%m%d-%H%M%SZ)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "[1/4] Dumping Postgres..."
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-fylix}" -Fc "${POSTGRES_DB:-fylix}" \
  > "$STAGE/pgdump-$TS.sql"

echo "[2/4] Archiving MinIO 'transfers' bucket..."
docker compose exec -T minio mc alias set local http://localhost:9000 \
  "$(grep ^MINIO_ROOT_USER "$REPO_ROOT/.env" | cut -d= -f2)" \
  "$(grep ^MINIO_ROOT_PASSWORD "$REPO_ROOT/.env" | cut -d= -f2)" >/dev/null
MINIO_BUCKET="${MINIO_BUCKET:-transfers}"
docker compose exec -T minio mc mirror --overwrite "local/$MINIO_BUCKET" "/tmp/mirror-$TS" >/dev/null
docker compose cp "minio:/tmp/mirror-$TS" "$STAGE/minio-$TS"
docker compose exec -T minio rm -rf "/tmp/mirror-$TS"
tar -cf "$STAGE/minio-$TS.tar" -C "$STAGE" "minio-$TS"
rm -rf "$STAGE/minio-$TS"

echo "[3/4] Copying master_key..."
cp "$MASTER_KEY" "$STAGE/master_key"

echo "[4/4] Encrypting with age..."
tar -cf "$STAGE/fylix-backup-$TS.tar" -C "$STAGE" "pgdump-$TS.sql" "minio-$TS.tar" "master_key"
age -R "$PUB_KEY" -o "$OUT_DIR/fylix-backup-$TS.tar.age" "$STAGE/fylix-backup-$TS.tar"

# Shred intermediates (tmp dir cleaned by trap anyway, but belt-and-suspenders).
if command -v shred >/dev/null 2>&1; then
  find "$STAGE" -type f -exec shred -u {} \;
fi

SIZE=$(du -h "$OUT_DIR/fylix-backup-$TS.tar.age" | cut -f1)
echo ""
echo "=== BACKUP COMPLETE ==="
echo "File: $OUT_DIR/fylix-backup-$TS.tar.age ($SIZE)"
echo ""
echo "Rotate old backups and upload off-site (see docs/BACKUP.md)."
