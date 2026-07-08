# CI / Security pipeline

Two GitHub Actions workflows live in `.github/workflows/`:

- `ci.yml` — lint + typecheck, unit tests, integration tests (full docker-compose stack),
  and frontend build + typecheck for both SPAs.
- `security.yml` — runs on every push, pull request, and weekly cron (Mondays 03:00 UTC):
  bandit, pip-audit, semgrep, trivy.

---

## Workflows in detail

### `ci.yml`

| Job | What it does |
|-----|-------------|
| `lint` | `ruff check` (linting) + `ruff format --check` (formatting) + `mypy` (type-checking) against `backend/app/` |
| `unit` | `pytest tests/unit` — runs without Docker; uses env-var stubs for DB/MinIO creds |
| `integration` | Generates a fresh master key + self-signed TLS cert, starts the full docker-compose stack, waits for `/healthz`, runs `alembic upgrade head`, then `pytest tests/integration -m integration` |
| `frontend` | Matrix over `frontend` and `admin-frontend`: `npm ci`, `npm run typecheck`, `npm run build` |

### `security.yml`

| Job | Tool | What it checks |
|-----|------|---------------|
| `bandit` | [Bandit](https://bandit.readthedocs.io/) | Python static analysis — shell injection, insecure hash algorithms, pickle usage, hardcoded secrets, etc. Configured via `[tool.bandit]` in `backend/pyproject.toml`. |
| `pip-audit` | [pip-audit](https://pypi.org/project/pip-audit/) | Known CVEs in pinned production dependencies. Uses `uv export --no-dev` so dev-only packages (pytest, mypy, ruff) are not scanned in the prod context. `--strict` fails the build on any finding. |
| `semgrep` | [Semgrep](https://semgrep.dev/) | OWASP Top 10 + Python + security-audit rulesets. Outputs a SARIF artefact for optional Security tab integration. |
| `trivy` | [Trivy](https://aquasecurity.github.io/trivy/) | Scans the three built container images (`fylix-api:prod`, `fylix-frontend:prod`, `fylix-admin-frontend:prod`) for HIGH/CRITICAL vulnerabilities in the base layer and installed packages. `ignore-unfixed: true` suppresses noise from unfixable distro CVEs. |

---

## Running locally

### Lint + typecheck (fast, no Docker)

```bash
make lint
# Equivalent to:
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

### Format (auto-fix)

```bash
make fmt
```

### Unit tests

```bash
make test
# Equivalent to:
cd backend && uv run pytest tests/unit -v
```

### Integration tests (requires running stack)

```bash
make up          # start docker-compose stack
make migrate     # apply migrations
make test-integration
# Equivalent to:
docker compose exec -T api /opt/venv/bin/pytest tests/integration -v -m integration
```

### Dependency CVE audit

```bash
make audit
# Equivalent to:
cd backend && uv export --frozen --no-dev > /tmp/requirements-frozen.txt
pip-audit -r /tmp/requirements-frozen.txt --strict
```

Requires `pip-audit` installed on the host: `pip install pip-audit`.

### Source static analysis + container scan

```bash
make scan
# Runs bandit on backend/app/ (HIGH/CRITICAL + high-confidence findings)
# Then builds fylix-api:local and runs trivy with --severity HIGH,CRITICAL
```

Requires `bandit` and `trivy` installed on the host:

```bash
pip install "bandit[toml]>=1.7"
# trivy: https://aquasecurity.github.io/trivy/latest/getting-started/installation/
brew install trivy   # macOS
```

---

## Fail-open policy

Security scanners are tuned to fail the build on **HIGH or CRITICAL** issues only.
MEDIUM and below are surfaced as warnings in artefact logs but do not block merges —
this keeps the queue moving while genuine risks get attention.

Bandit is invoked with `-ll -i` in local/CI mode:
- `-ll` = LOW severity and above (all findings shown in output)
- `-i`  = HIGH confidence only (suppresses speculative findings)

The net effect: LOW/MEDIUM findings appear in the log for human review but only
HIGH severity + HIGH confidence issues fail the job.

---

## Handling false positives

If a scanner produces a false positive, add a targeted ignore with an explanation:

**Bandit**

```python
return request.client.host if request.client else "0.0.0.0"  # nosec B104 — fallback string for logging, not socket binding
```

**Semgrep**

```python
result = subprocess.run(cmd, ...)  # nosemgrep: python.lang.security.audit.subprocess-without-shell-equals-true
```

**pip-audit**

```bash
pip-audit -r requirements-frozen.txt --strict --ignore-vuln GHSA-xxxx-yyyy-zzzz
# Document the reason in a comment in the Makefile/workflow file.
```

Every ignore must include a comment explaining why the finding is a false positive or
why the risk is accepted.

---

## SARIF integration

Semgrep outputs a SARIF file (`semgrep.sarif`) uploaded as a workflow artefact (kept
90 days). For GitHub Security tab integration, add the following step after the semgrep
scan step in `security.yml`:

```yaml
- name: Upload SARIF to GitHub Security tab
  uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: semgrep.sarif
```

This requires either a public repository or a GitHub Advanced Security licence on
a private repository.

---

## Artefacts produced

| Artefact | Kept for | Contents |
|----------|----------|----------|
| `bandit-report` | 90 days (default) | `bandit-report.json` — full JSON report of all findings |
| `semgrep-sarif` | 90 days (default) | `semgrep.sarif` — SARIF format, importable into any SARIF viewer |
