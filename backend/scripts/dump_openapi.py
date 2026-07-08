"""Dump the Fylix OpenAPI spec to stdout as pretty JSON.

Production has ``openapi_url=None`` (no public `/openapi.json` endpoint)
so downstream consumers — admin SPA, internal integrations, test-client
generation — need a committed snapshot. CI invokes this script to
refresh ``docs/openapi.json`` on every merge to master:

    python -m scripts.dump_openapi > docs/openapi.json

Run locally:

    cd backend
    set -a && . ../.env && set +a
    MASTER_KEY_PATH=/tmp/fake-key .venv/bin/python -m scripts.dump_openapi \
        > ../docs/openapi.json

(Any dummy master-key path works — this script never reads the key; the
``load_master_key`` call is skipped because we don't enter lifespan.)
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    # Import lazily so ``python -m scripts.dump_openapi --help`` etc. is fast.
    from app.main import app

    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
