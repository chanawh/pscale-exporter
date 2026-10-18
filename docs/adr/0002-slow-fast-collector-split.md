# ADR 0002: Slow/fast collector split with event cardinality guard

Status: accepted (v1.2.0)
Date: 2026-10-14

## Context

Not all OneFS endpoints cost the same. Hot metrics (capacity, node/drive
health, performance stats) are cheap and operators want them every 30s. But
v1.2 added expensive endpoints — events, snapshots, storage pools, hardware
sensors, dedupe, CloudPools — and v3 added SyncIQ, quotas, and protocol
details. Some of these are slow on large clusters, and one family is
dangerous: the events API returns an *unbounded* list, and naively turning
each event into a labeled series is a cardinality bomb that can OOM both the
exporter and Prometheus.

## Decision

Two scrape cadences in the same process (`exporter/main.py`):

- **Fast loop** every `SCRAPE_INTERVAL` (default 30s): capacity, nodes,
  drives, perf stats — the hot path, untouched by slow-collector latency.
- **Slow collectors** on `SLOW_SCRAPE_INTERVAL` (default 300s), tracked per
  `ClusterScraper` via `last_slow_run`: events, snapshots, pools, sensors,
  dedupe, CloudPools, SyncIQ, quotas, NFS/SMB.

Event cardinality is guarded in two places:

1. `parse_events()` (`exporter/collectors.py`) truncates to `MAX_EVENTS`
   (default 50) newest-first — the series count is bounded by config, not by
   whatever the cluster returns.
2. `scrape_slow()` expires stale series: events that aged out of the API
   window are removed via `EVENT_INFO.remove(*stale)` / `EVENT_TS.remove(*stale)`
   using the scraper's `known_events` set, so deleted events don't leave
   orphaned series behind forever.

## Consequences

- **Positive:** a slow OneFS API can never block the 30s hot path; series
  cardinality is bounded by configuration (`MAX_EVENTS`), not by cluster
  behavior; both knobs are env-tunable (`SLOW_SCRAPE_INTERVAL`,
  `MAX_EVENTS`) without redeploying.
- **Negative:** slow metrics can be up to 5 minutes stale by default —
  acceptable for snapshots/quotas/sensors, documented in the README metrics
  table; operators chasing fresher data tune one env var.
- **Neutral:** two cadences means two things to reason about when debugging
  "why is this metric stale" — the `/metrics/` output and the README call
  out which families are slow.
