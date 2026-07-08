#!/usr/bin/env bash
# Orchestrate master-key rotation end-to-end.
#
# 1. Backup first (safety net)
# 2. Generate new key into secrets/master_key.new
# 3a. Stop worker to prevent concurrent encrypt tasks wrapping keys with OLD key
# 3b. Stop api to prevent new transfers being created during rotation window
# 4. Run rotation in a one-shot container (no live api needed)
# 5. Swap secrets/master_key <- secrets/master_key.new (after success)
# 6. Archive old key to secrets/master_key.old.<timestamp>
# 7. Restart api + worker with new key
# 8. Smoke test healthz
#
# NOTE: Steps 3b/3a ensure no transfers can be created or encrypted between
# the point we start rewrapping and the point we swap the key file. Any admin
# actions that write wrapped_key directly (sender-delete, etc.) are extremely
# rare during this window and are accepted as an edge case; document in runbook.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRETS_DIR="$REPO_ROOT/secrets"

TS="$(date -u +%Y%m%d-%H%M%SZ)"

echo "*** MASTER KEY ROTATION ***"
echo "This will rewrap ALL per-transfer keys and TOTP secrets in the database."
read -r -p "Type 'ROTATE' to continue: " confirm
[[ "$confirm" == "ROTATE" ]] || { echo "Aborted."; exit 1; }

echo ""
echo "[1/8] Backup before rotation..."
"$SCRIPT_DIR/backup.sh" "$REPO_ROOT/backups"

echo ""
echo "[2/8] Generating new master key..."
if [[ -f "$SECRETS_DIR/master_key.new" ]]; then
  echo "ERROR: $SECRETS_DIR/master_key.new already exists. Delete it first." >&2
  exit 1
fi
openssl rand 32 > "$SECRETS_DIR/master_key.new"
chmod 400 "$SECRETS_DIR/master_key.new"
echo "  new key hex: $(xxd -p -c 64 "$SECRETS_DIR/master_key.new")"
echo "  (WRITE THIS DOWN — paper, safe)"
read -r -p "  Press Enter once recorded..."

echo ""
echo "[3a/8] Stopping worker to prevent concurrent encrypt tasks..."
docker compose stop worker

echo ""
echo "[3b/8] Stopping api to prevent new transfers during rotation window..."
docker compose stop api

echo ""
echo "[4/8] Running rotation migration in a one-shot container..."
docker compose run --rm -T \
  -v "$SECRETS_DIR/master_key.new:/tmp/new_master_key:ro" \
  api /opt/venv/bin/python scripts/rotate_master_key.py --new-key /tmp/new_master_key

echo ""
echo "[5/8] Swapping master key files..."
mv "$SECRETS_DIR/master_key" "$SECRETS_DIR/master_key.old.$TS"
mv "$SECRETS_DIR/master_key.new" "$SECRETS_DIR/master_key"
chmod 400 "$SECRETS_DIR/master_key.old.$TS"
chmod 400 "$SECRETS_DIR/master_key"

echo ""
echo "[6/8] Archiving old key..."
echo "  Old key preserved at: $SECRETS_DIR/master_key.old.$TS"
echo "  Store it sealed for 30 days, then secure-delete."

echo ""
echo "[7/8] Restarting api and worker with new master key..."
docker compose start api worker
sleep 8

echo ""
echo "[8/8] Smoke test..."
curl -k -s https://localhost/healthz && echo

echo ""
echo "=== ROTATION COMPLETE ==="
echo "Old key archived at: $SECRETS_DIR/master_key.old.$TS"
echo "Store it sealed for 30 days, then secure-delete."
echo ""
echo "Verify by: download a pre-rotation transfer via curl, login as an admin."
