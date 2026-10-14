# PowerScale Alert Runbooks

Triage guides for every alert in `monitoring/prometheus/alert-rules.yml`.
Each alert links here from its `runbook_url` annotation.

General first steps for any alert: open the Grafana dashboard
**"PowerScale Cluster - Complete Monitoring"** and check the exporter's
`/healthz` (`active_stat_map` shows what API discovery found on the last
successful scrape).

---

## PowerScaleClusterDown

**Severity:** critical

**Fires when:** `isilon_cluster_health == 0` for 1 minute — the exporter
cannot reach the OneFS API or the cluster reports itself unhealthy.

1. Check the exporter: `curl <exporter>:8000/healthz`. If `scraper_alive`
   is false or the endpoint is down, treat as a monitoring problem first
   (see PowerScaleExporterDown).
2. From a node or the OneFS WebUI, run `isi status` — confirm whether the
   cluster itself is up.
3. Check network path and API credentials (wrong `ISILON_PASS` shows up as
   repeated API errors in the exporter logs, not as cluster-down).
4. If the cluster is genuinely down, follow your site's cluster-outage
   procedure — this is beyond exporter scope.

## PowerScaleNodeDown

**Severity:** critical

**Fires when:** `isilon_node_status == 0` for 2 minutes on a node.

1. Identify the node from the `node_id` label.
2. `isi status` / `isi nodes list -v` — is the node down, smartfailed, or
   in read-only?
3. Check hardware (iDRAC/iLO) and recent OneFS events for the node.
4. If the node was removed permanently, it will age out of metrics after
   `TOMBSTONE_TTL` (default 24h).

## PowerScaleDriveFailure

**Severity:** critical

**Fires when:** `isilon_drive_health == 0` for 1 minute.

1. Identify node and drive from the `node_id` / `drive_id` labels.
2. `isi devices drive list --node-lnn <n>` — confirm the failure and check
   whether SmartFail already started.
3. Open a hardware replacement case; OneFS will restripe the diskpool
   automatically once the replacement is inserted.
4. Watch `isilon_drive_health` return to 1 after rebuild completes.

## PowerScaleCriticalCPU

**Severity:** critical

**Fires when:** node CPU user % > 95 for 5 minutes.

1. Identify the hot node (`node_id`) and check whether it's a single node
   or cluster-wide (compare across `node_id` in Grafana).
2. Look for runaway client workloads: top talkers, backup windows, or
   antivirus scans landing on one node.
3. Short term: move workloads / rebalance via SmartConnect zones.
4. Sustained: capacity-plan a node addition.

## PowerScaleCriticalCapacity

**Severity:** critical

**Fires when:** used / total capacity > 95% for 15 minutes.

1. This is a stop-everything alert: writes will start failing near 100%.
2. Find the growth: snapshot usage (`isi snapshot usage list`),
   quota reports, or a runaway client share.
3. Immediate relief: expire old snapshots, enforce quotas, tier cold data
   via SmartPools/CloudPools.
4. Plan node additions — do not ride above 90% as normal.

## PowerScaleReplicationStalled

**Severity:** critical

**Fires when:** SyncIQ lag > 3600s for 5 minutes.

1. `isi sync policies list -v` and `isi sync jobs list` — is a job
   running, failed, or never starting?
2. Check the target cluster's health and the network path between
   source and target.
3. Look for worker exhaustion (too many concurrent policies) or a
   target-side capacity problem.
4. RPO is blown at this point — notify stakeholders per your DR plan.

## PowerScaleExporterDown

**Severity:** critical

**Fires when:** Prometheus can't scrape the exporter for 2 minutes.

1. This is a **monitoring** problem, not a cluster problem — the cluster
   may be perfectly healthy.
2. Kubernetes: `kubectl -n powerscale-monitoring get pods`,
   `kubectl logs deploy/powerscale-exporter`. Compose:
   `docker compose ps` / `docker compose logs exporter`.
3. Common causes: bad `ISILON_PASS` (fail-fast at startup — check logs),
   OOMKill (raise the memory limit), or the OneFS target being
   unreachable (then see PowerScaleClusterDown).

## PowerScaleClusterDegraded

**Severity:** warning

**Fires when:** the cluster is healthy but metric collection is failing
(exporter down or scrape duration > 30s).

1. Check `isilon_exporter_last_scrape_successful` and
   `isilon_exporter_api_errors_total{endpoint=~...}` to find the failing
   endpoint.
2. Partial API outages (e.g. statistics endpoint slow) are the usual
   cause — the cluster serves clients fine while telemetry lags.
3. If scrape duration is the issue, see PowerScaleExporterSlow.

## PowerScaleHighCPU

**Severity:** warning

**Fires when:** node CPU user % > 80 for 10 minutes. Early-warning version
of PowerScaleCriticalCPU — same triage, less urgency.

## PowerScaleHighCapacity

**Severity:** warning

**Fires when:** used / total capacity > 85% for 30 minutes. Start the
capacity plan now (snapshots, quotas, tiering, node orders) so the
critical alert never fires.

## PowerScaleHighDriveLatency

**Severity:** warning

**Fires when:** drive latency > 50ms for 20 minutes.

1. Identify the drive (`node_id` / `drive_id`). Sustained latency often
   precedes a SMART pre-failure — treat as a leading indicator.
2. Check `isilon_drive_health`, `isilon_drive_busy_pct`, and
   `isilon_drive_queue_depth` for the same drive.
3. If health is still 1 but latency persists, plan a proactive
   replacement during a maintenance window.

## PowerScaleHighDiskBusy

**Severity:** warning

**Fires when:** node disk busy % > 90 for 15 minutes.

1. Node-level I/O saturation — check whether it's driven by client
   workload, restripe/rebuild activity, or backup.
2. Correlate with `isilon_node_disk_iops_in/out` and network throughput.
3. Rebalance workloads or reschedule heavy jobs (backups, NDMP).

## PowerScaleReplicationLag

**Severity:** warning

**Fires when:** SyncIQ lag > 300s for 10 minutes. Early-warning version
of PowerScaleReplicationStalled — same triage, RPO still intact.

## PowerScaleExporterSlow

**Severity:** warning

**Fires when:** Prometheus scrape duration > 30s for 5 minutes.

1. The exporter is taking too long to collect — usually a slow OneFS
   API under cluster load, not an exporter bug.
2. Check `isilon_exporter_scrape_duration_seconds` (histogram) and
   exporter logs for per-endpoint timings.
3. Mitigations: raise `SCRAPE_INTERVAL`, raise `TIMEOUT`, or reduce
   scrape load (fewer expensive stat keys).
