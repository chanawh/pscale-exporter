# ADR 0001: Multi-cluster fan-out — one exporter scrapes N clusters

Status: accepted (v2.0.0)
Date: 2026-10-14

## Context

v1 was single-cluster: one exporter process scraped the cluster named by
`ISILON_HOST` / `ISILON_PASS`. Fleet operators run many PowerScale clusters,
and the naive scaling story — one exporter Deployment per cluster — multiplies
pods, Services, ServiceMonitors, and dashboard variables linearly. Meanwhile
every metric series the exporter emits already carried a `cluster_name` label,
so dashboards and alert rules were already fleet-capable; only the scrape
topology lagged behind.

## Decision

One exporter process scrapes many clusters (fan-out), configured opt-in:

- `ISILON_TARGETS`: JSON list of `{"name", "host", "port", "user", "password"}`.
- `ISILON_TARGETS_FILE`: path to a JSON (or YAML) file with the same list —
  designed for a Kubernetes Secret-mounted file (the Helm chart renders one
  from `clusters:` / `clusterPasswords:`).
- With neither set, the exporter runs single-cluster from
  `ISILON_HOST`/`ISILON_PASS` exactly like v1 (zero behavior change for
  existing deployments).

Each target gets its own `ClusterScraper` instance (`exporter/main.py`) holding
*all* per-cluster state: the OneFS client, discovered endpoints/stat keys,
timing state, and the slow-collector cadence clock. Prometheus gauges stay
module-global — safe because every series carries `cluster_name`.

Failure isolation is per target at every stage: a target that fails init is
skipped with a log line; discovery failures are caught per scraper; each
scrape iteration wraps `s.scrape()` in try/except, so one unreachable or
misbehaving cluster can never take down scraping for the rest. A target with
no password fails fast at startup (`load_targets` raises) rather than
half-scraping.

## Consequences

- **Positive:** one Deployment/Helm release serves the whole fleet;
  dashboards, recording rules, and alerts work unchanged across clusters
  because `cluster_name` was already on every series; demo compose ships two
  mock targets that exercise the multi-cluster path in CI.
- **Negative:** blast radius — if the exporter *process* dies, all clusters go
  dark at once (mitigated by the per-target isolation above plus the
  standard liveness probe on `/livez`); memory grows with cluster count since
  discovery state is per target (bounded: endpoint tuples and stat-key maps,
  not metric data).
- **Neutral:** target list is static at startup; adding a cluster requires a
  restart (acceptable — cluster fleets change rarely, and it keeps the
  hot loop free of config-reload races).
