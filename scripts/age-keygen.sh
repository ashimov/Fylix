#!/usr/bin/env bash
# Generate an age X25519 key pair for backup encryption.
#
# Usage: ./scripts/age-keygen.sh
#
# Produces:
#   secrets/age-backup.key       — private key (0o400, KEEP SAFE)
#   secrets/age-backup.pub       — public recipient (used by backup.sh)
#
# For multi-recipient setups (e.g., encrypt for both the ops team and
# off-site archive), append more `-r <recipient>` flags manually after
# running this once.

set -euo pipefail

if ! command -v age-keygen >/dev/null 2>&1; then
  echo "ERROR: age-keygen not found. Install 'age' (https://age-encryption.org)." >&2
  exit 1
fi

SECRETS_DIR="$(dirname "$0")/../secrets"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

KEY="$SECRETS_DIR/age-backup.key"
PUB="$SECRETS_DIR/age-backup.pub"

if [[ -f "$KEY" ]]; then
  echo "ERROR: $KEY already exists. Back it up and remove before regenerating." >&2
  exit 1
fi

age-keygen -o "$KEY" 2>/dev/null
chmod 400 "$KEY"
# Extract the public key line (second line of the age-keygen output file).
grep "^# public key:" "$KEY" | sed 's/# public key: //' > "$PUB"
chmod 444 "$PUB"

echo "Age backup key pair generated:"
echo "  private: $KEY  (0o400, KEEP SAFE — needed for restore)"
echo "  public : $PUB  (used by backup.sh)"
echo ""
echo "Public recipient: $(cat "$PUB")"
