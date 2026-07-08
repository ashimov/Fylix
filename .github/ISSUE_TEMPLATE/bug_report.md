---
name: Bug report
about: Report unexpected behavior in Fylix
title: "[Bug] "
labels: bug
assignees: ""
---

## Describe the bug

A clear, concise description of what the bug is.

## Steps to reproduce

1. Go to '...'
2. Run '...'
3. See error

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Include error messages, stack traces, or logs (`make logs` /
`docker compose logs <service>`) — please redact secrets (passwords, master key hex, tokens).

## Screenshots

If applicable, add screenshots to help explain the problem.

## Environment

- Fylix version / commit: `git rev-parse HEAD`
- Deployment mode: docker-compose / Kubernetes / other
- `APP_ENV`: development / production
- OS: (e.g. macOS 14, Ubuntu 22.04)
- Docker version: `docker --version`
- Docker Compose version: `docker compose version`
- Browser (if UI-related): (e.g. Chrome 126)

## Additional context

Add any other context about the problem here (e.g. was this working before an upgrade, is it
reproducible on a clean `./setup.sh`, etc.).

---

**Note:** if this is a security vulnerability, please do **not** open a public issue — see
[docs/SECURITY.md](../../docs/SECURITY.md) for the responsible-disclosure process.
