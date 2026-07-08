#!/usr/bin/env bash
# Generate a 32-byte master encryption key and write it to secrets/master_key.
# The key is printed as 64 hex chars in stdout so the operator can record it
# (paper in safe / Shamir SS) before the file is the only copy.

set -euo pipefail

SECRETS_DIR="$(dirname "$0")/../secrets"
KEY_FILE="$SECRETS_DIR/master_key"

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

if [[ -f "$KEY_FILE" ]]; then
  echo "ERROR: $KEY_FILE already exists. Refuse to overwrite." >&2
  exit 1
fi

# 32 random bytes → binary file; also hex for display
openssl rand 32 > "$KEY_FILE"
chmod 400 "$KEY_FILE"

echo "=== MASTER KEY GENERATED ==="
echo "File: $KEY_FILE"
echo "Hex : $(xxd -p -c 64 "$KEY_FILE")"
echo ""
echo "WRITE DOWN THE HEX VALUE NOW (paper, safe)."
echo "Losing this key = losing access to ALL existing ciphertext (crypto-shred)."
