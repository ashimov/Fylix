# Fylix Service Level Objectives

Owner: Fylix platform team
Review cadence: quarterly
Last updated: 2026-04-20

## Why SLOs

Fylix is in the business-critical path for your organization's partner file
exchange. Outages block shipments, regulator submissions, and internal
approvals. SLOs give us explicit reliability targets that operators and
stakeholders can agree on — and error budgets that tell us when to
slow feature work.

---

## Service Level Indicators (SLIs)

All SLIs are derived from metrics in `/metrics` (Prometheus) or
OpenTelemetry spans (Jaeger). See `docs/DEPLOYMENT.md §10`.

| SLI | Definition | Source |
|---|---|---|
| **Upload success rate** | Share of `POST /api/transfers` requests that return 2xx out of all non-4xx attempts (4xx are user errors, excluded from denominator). | HawkAPI access logs → Prometheus counter to add |
| **Upload completion rate** | Share of transfers that reach `status='ready'` within 10 min of creation. | Audit log + Postgres query; export as histogram |
| **Download time-to-first-byte** | p99 latency between `GET /t/{token}/file/{id}` request start and the first streamed body byte. | OTel span `download_file` |
| **Crypto-shred freshness** | Seconds since last successful `worker:cleanup` tick. | `fylix_cleanup_last_run_timestamp` (existing) |
| **Availability** | Share of `GET /healthz` probes that return 200 from outside the admin CIDR. | External blackbox probe (Grafana Alloy or UptimeRobot) |

---

## SLO targets

| SLO | Target | Window | Error budget |
|---|---|---|---|
| Upload success rate | **≥ 99.5%** | 30-day rolling | 3.6 h of failed uploads per month |
| Upload completion rate | **≥ 99.0%** | 30-day rolling | 7.2 h of stuck transfers |
| Download TTFB p99 | **≤ 2.0 s** | 7-day rolling | 1% of downloads may exceed |
| Crypto-shred freshness | **age ≤ 10 min** always | — (burn-rate) | Any breach = pager |
| Availability (/healthz) | **≥ 99.9%** | 30-day rolling | 43 min/month downtime |

**Crypto-shred is a hard SLO, not a probabilistic one** — the moment
the heartbeat age exceeds 10 min, expired ciphertext lingers in MinIO
past its TTL with keys still unwrapped. That violates the
crypto-shred security claim documented in `SECURITY.md`.

---

## Alert rules (Prometheus)

### Hard alerts (page oncall immediately)

```promql
# Crypto-shred SLA violated
(time() - fylix_cleanup_last_run_timestamp) > 600

# DLQ backlog growing uncontrolled
sum(fylix_worker_queue_depth{queue=~".*:dlq"}) > 50

# api /metrics unreachable (proxy for api crash)
up{job="fylix-api"} == 0
```

### Burn-rate alerts (Google SRE multi-window multi-burn-rate)

Once per-request counters are added (`fylix_transfers_created_total`,
`fylix_upload_outcome_total{status}`), wire the standard
2%/5%/10%/14.4-hour window rules per
[sre.google/workbook/alerting-on-slos](https://sre.google/workbook/alerting-on-slos/).

---

## What to do when the budget burns

- **0%–50% consumed**: normal operations. Ship features.
- **50%–80%**: slow new features. Dedicate one engineer to reliability.
- **80%–100%**: feature freeze. Full team on reliability until budget
  recovers over the next window.
- **Exhausted**: incident. Follow `docs/INCIDENT_RESPONSE.md`. Post-mortem.

---

## Metrics we still need

Current `/metrics` only exposes the worker-queue gauge + cleanup
heartbeat. To measure the full SLO set, add counters/histograms
(tracked as a Phase-4 observability task — see
`observability/grafana/dashboards/fylix-traces-overview.json`
"What to add next" panel):

- `fylix_transfers_created_total{outcome}` — Counter in
  `POST /api/transfers` handler
- `fylix_upload_file_duration_seconds` — Histogram around TUS PATCH
  body write
- `fylix_download_ttfb_seconds` — Histogram in streaming-response
  builder before first yield
- `fylix_download_bytes_total` — Counter incremented per chunk
- `fylix_admin_login_attempts_total{outcome}` — already partially
  covered by audit log; surface as counter for alerting

---

## Review

Review targets every quarter with your security + ops teams. Raise the
bar as the platform stabilises; don't weaken targets without a
written risk acceptance from the product owner.
