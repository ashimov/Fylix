# Contributing to Fylix

Thanks for your interest in improving Fylix. This document covers how to set up a development
environment, run tests and linters, and submit changes.

## Development environment

### Prerequisites

- Docker 24+ and Docker Compose v2
- [`uv`](https://github.com/astral-sh/uv) — Python dependency management (backend)
- Node.js 22+ — for editing either SPA (`frontend/`, `admin-frontend/`)

### First-time setup

```bash
git clone https://github.com/ashimov/Fylix.git
cd Fylix
./setup.sh
```

`setup.sh` generates `secrets/master_key`, a dev TLS cert, `.env`, and brings up the full stack
(Postgres, Redis, MinIO, the API, worker, both SPAs, Nginx, mailpit). See [CLAUDE.md](CLAUDE.md)
for the full command reference.

### Backend (`backend/`)

```bash
cd backend
uv sync                      # install all deps (incl. dev group: pytest, ruff, mypy)
```

### Frontends (`frontend/`, `admin-frontend/`)

```bash
cd frontend        # or admin-frontend
npm install
npm run dev         # Vite dev server with hot reload
```

## Running tests

```bash
# Backend unit tests (no Docker required — set dummy infra env vars)
cd backend
POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
  MINIO_ROOT_USER=x MINIO_ROOT_PASSWORD=x \
  uv run pytest tests/unit -v

# Backend integration tests (requires the docker compose stack up)
docker compose exec api /opt/venv/bin/pytest tests/integration -v -m integration

# Frontend (public SPA only — admin-frontend has no unit test suite yet)
cd frontend
npm run test
npm run typecheck
npm run build
```

Or simply `make test` from the repo root for the backend unit suite.

## Linting & formatting

```bash
# Backend — ruff (lint + format) + mypy strict
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy app

# Auto-fix formatting
uv run ruff format .

# Or via Make
make lint
make fmt
```

Both frontends run type-checking via `npm run typecheck` (`vue-tsc --noEmit`); there is no
separate ESLint/Prettier config in this repo currently — please match the existing code style
(2-space indent, TypeScript strict mode as configured in `tsconfig.json`).

There is no `.pre-commit-config.yaml` in this repo; CI (`.github/workflows/ci.yml`) runs the
lint/typecheck/test/build steps above on every push and pull request — run them locally before
pushing to catch issues early.

## Code style notes

- **Backend**: `ruff` line length 100, target Python 3.12, rule set `E,F,I,B,UP,S,A,C4,SIM,PL`
  (see `backend/pyproject.toml`). `mypy --strict` on `app/`. Prefer explicit types on public
  function signatures.
- **Frontend**: TypeScript strict mode, Vue 3 `<script setup>` composition API, Pinia for state,
  vue-i18n for all user-facing strings (add keys to `ru.json`, `kk.json`, and `en.json` together).
- **Security-sensitive code** (anything under `backend/app/crypto/`, auth, or the admin routers)
  should include or update tests in `backend/tests/unit` — see `docs/THREAT_MODEL.md` and
  `docs/SECURITY.md` for the properties these areas must preserve.

## Branch & PR workflow

1. Fork the repository and create a feature branch off `master`: `git checkout -b feat/short-description`.
2. Make your changes with focused, logically-scoped commits.
3. Run the relevant tests and linters locally (see above) — CI will run the same checks.
4. Open a pull request against `master` using the PR template. Describe *why* the change is
   needed, not just what changed, and link any related issue.
5. Keep PRs small and focused; large refactors are easier to review split into steps.
6. A maintainer will review and may request changes before merging.

## Reporting issues

Use the GitHub issue templates:

- **Bug report** — for unexpected behavior, include steps to reproduce, expected vs. actual
  behavior, and environment details (OS, Docker version, `APP_ENV`).
- **Feature request** — for proposed enhancements, describe the problem it solves before
  proposing a solution.

**Security vulnerabilities**: please do **not** open a public issue. See
[docs/SECURITY.md](docs/SECURITY.md) for the responsible-disclosure process.

## Using Claude Code

This repository includes a [CLAUDE.md](CLAUDE.md) with a concise, accurate map of commands,
architecture, and key files. If you use [Claude Code](https://claude.com/claude-code), just run
`claude` from the repo root — it reads `CLAUDE.md` automatically and can help you navigate the
codebase, run tests, and understand the envelope-encryption flow before you make changes.
