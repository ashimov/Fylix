#!/usr/bin/env bash
# Generate self-signed TLS cert for local development.
# For production, replace nginx/certs/{fullchain.pem,privkey.pem} with LE certs.

set -euo pipefail

CERT_DIR="$(dirname "$0")/../nginx/certs"
mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/fullchain.pem" ]]; then
  echo "ERROR: certs already exist in $CERT_DIR. Remove them first." >&2
  exit 1
fi

openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/CN=localhost/O=Fylix Dev" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

chmod 400 "$CERT_DIR/privkey.pem"
chmod 444 "$CERT_DIR/fullchain.pem"

echo "Dev TLS certs generated in $CERT_DIR"
