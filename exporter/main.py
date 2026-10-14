import logging
import os
import threading
import time
from time import perf_counter

from collectors import (
    parse_cloudpools,
    parse_dedupe,
    parse_events,
    parse_sensors,
    parse_snapshots,
    parse_storagepools,
    parse_versions,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from scraper import OneFSClient
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --- Configuration ---
def _int_env(name, default):
    v = (os.getenv(name) or "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default


ISILON_HOST = os.getenv("ISILON_HOST", "127.0.0.1")
ISILON_PORT = _int_env("ISILON_PORT", 8080)
ISILON_USER = os.getenv("ISILON_USER", "root")
ISILON_PASS = os.getenv("ISILON_PASS", "")
SCRAPE_INTERVAL = _int_env("SCRAPE_INTERVAL", 30)
TOMBSTONE_TTL = _int_env("TOMBSTONE_TTL", 24 * 3600)
# v1.2: slow collectors (events, snapshots, pools, sensors, ...) run on a
# longer cadence; the fast loop keeps the hot path untouched.
SLOW_SCRAPE_INTERVAL = _int_env("SLOW_SCRAPE_INTERVAL", 300)
MAX_EVENTS = _int_env("MAX_EVENTS", 50)
METRICS_AUTH_TOKEN = os.getenv("METRICS_AUTH_TOKEN", "")
TLS_CERT_FILE = os.getenv("TLS_CERT_FILE", "")
TLS_KEY_FILE = os.getenv("TLS_KEY_FILE", "")


def load_targets() -> list[dict]:
    """v2: resolve the list of OneFS clusters to scrape.

    - ``ISILON_TARGETS``: JSON list of
      ``{"name", "host", "port", "user", "password"}`` objects.
    - ``ISILON_TARGETS_FILE``: path to a JSON file (or YAML if PyYAML is
      available) with the same list. Useful for k8s Secret-mounted files.
    - Fallback: single target from ``ISILON_HOST``/``PORT``/``USER``/``PASS``
      (v1 behavior).

    Every target needs a password -- fail fast otherwise.
    """
    import json

    raw = (os.getenv("ISILON_TARGETS", "") or "").strip()
    path = (os.getenv("ISILON_TARGETS_FILE", "") or "").strip()
    entries: list = []
    if path:
        with open(path) as f:
            text = f.read()
        try:
            entries = json.loads(text)
        except ValueError:
            try:
                import yaml  # optional; JSON always works

                entries = yaml.safe_load(text)
            except ImportError:
                raise RuntimeError(
                    f"{path} is not valid JSON and PyYAML is not installed"
                )
    elif raw:
        entries = json.loads(raw)
    else:
        password = (os.getenv("ISILON_PASS", "") or "").strip()
        if not password:
            raise RuntimeError(
                "ISILON_PASS is not set: refusing to start without a password"
            )
        return [
            {
                "name": ISILON_HOST,
                "host": ISILON_HOST,
                "port": ISILON_PORT,
                "user": ISILON_USER,
                "password": password,
            }
        ]

    if not isinstance(entries, list) or not entries:
        raise RuntimeError("No targets configured (empty target list)")
    targets = []
    for e in entries:
        if not isinstance(e, dict):
            raise TypeError(f"Invalid target entry (must be an object): {e!r}")
        host = e.get("host")
        pw = e.get("password", e.get("pass", ""))
        if not host or not pw:
            raise RuntimeError(f"Target missing host/password: {e!r}")
        targets.append(
            {
                "name": str(e.get("name") or host),
                "host": str(host),
                "port": int(e.get("port", 8080)),
                "user": str(e.get("user", "root")),
                "password": str(pw),
            }
        )
    return targets


TARGETS = load_targets()
logger.info(f"[*] Configured targets: {[t['name'] for t in TARGETS]}")

# --- Prometheus Metrics ---
CLUSTER_HEALTH = Gauge(
    "isilon_cluster_health", "Cluster health (1=OK, 0=Error)", ["cluster_name"]
)
NODE_STATUS = Gauge(
    "isilon_node_status", "Node status (1=OK, 0=Error)", ["cluster_name", "node_id"]
)
NODE_CPU = Gauge(
    "isilon_node_cpu_value",
    "CPU-related statistic value per node.",
    ["cluster_name", "node_id"],
)
QUOTA_COUNT = Gauge(
    "isilon_quota_total", "Total number of quotas defined.", ["cluster_name"]
)

# Typed CPU & disk gauges
NODE_CPU_USER = Gauge(
    "isilon_node_cpu_user_pct", "CPU user %", ["cluster_name", "node_id"]
)
NODE_CPU_SYS = Gauge(
    "isilon_node_cpu_sys_pct", "CPU sys %", ["cluster_name", "node_id"]
)
NODE_CPU_IDLE = Gauge(
    "isilon_node_cpu_idle_pct", "CPU idle %", ["cluster_name", "node_id"]
)
NODE_DISK_BUSY = Gauge(
    "isilon_node_disk_busy_pct", "Disk busy %", ["cluster_name", "node_id"]
)
NODE_DISK_IOPS_IN = Gauge(
    "isilon_node_disk_iops_in", "Disk IOPS in", ["cluster_name", "node_id"]
)
NODE_DISK_IOPS_OUT = Gauge(
    "isilon_node_disk_iops_out", "Disk IOPS out", ["cluster_name", "node_id"]
)
NODE_DISK_BW_IN = Gauge(
    "isilon_node_disk_bw_in_bytes", "Disk bytes/s in", ["cluster_name", "node_id"]
)
NODE_DISK_BW_OUT = Gauge(
    "isilon_node_disk_bw_out_bytes", "Disk bytes/s out", ["cluster_name", "node_id"]
)

# Per-node: net + memory (bytes, not percent)
NODE_NET_IN = Gauge(
    "isilon_node_net_bytes_in", "Network bytes in", ["cluster_name", "node_id"]
)
NODE_NET_OUT = Gauge(
    "isilon_node_net_bytes_out", "Network bytes out", ["cluster_name", "node_id"]
)
NODE_MEM_USED_BYTES = Gauge(
    "isilon_node_memory_used_bytes", "Memory used in bytes", ["cluster_name", "node_id"]
)
NODE_MEM_USED_GB = Gauge(
    "isilon_node_memory_used_gb", "Memory used in GB", ["cluster_name", "node_id"]
)

# Cluster-level
CLUSTER_CAP_TOTAL = Gauge(
    "isilon_cluster_capacity_bytes_total", "Total capacity (bytes)", ["cluster_name"]
)
CLUSTER_CAP_USED = Gauge(
    "isilon_cluster_capacity_bytes_used", "Used capacity (bytes)", ["cluster_name"]
)
NFS_EXPORT_COUNT = Gauge(
    "isilon_nfs_export_count", "Total NFS exports", ["cluster_name"]
)
SMB_SHARE_COUNT = Gauge("isilon_smb_share_count", "Total SMB shares", ["cluster_name"])

# Per-drive and replication
DRIVE_HEALTH = Gauge(
    "isilon_drive_health",
    "Drive health (1=ok, 0=degraded)",
    ["cluster_name", "node_id", "drive_id"],
)
DRIVE_BUSY = Gauge(
    "isilon_drive_busy_pct",
    "Drive busy percentage",
    ["cluster_name", "node_id", "drive_id"],
)
DRIVE_LATENCY = Gauge(
    "isilon_drive_latency_ms",
    "Drive access latency in milliseconds",
    ["cluster_name", "node_id", "drive_id"],
)
DRIVE_QUEUE = Gauge(
    "isilon_drive_queue_depth",
    "Drive I/O queue depth",
    ["cluster_name", "node_id", "drive_id"],
)
REPL_LAG = Gauge(
    "isilon_replication_lag_seconds", "SyncIQ lag in seconds", ["cluster_name"]
)

# Meta / self-observability
SCRAPE_DURATION = Histogram(
    "isilon_exporter_scrape_duration_seconds", "Duration of a full scrape loop (s)"
)
NODE_LAST_SEEN = Gauge(
    "isilon_node_last_seen_seconds", "Unix ts last seen", ["cluster_name", "node_id"]
)
STATPATTERN_MISS = Counter(
    "isilon_exporter_statpattern_miss_total",
    "Stat pattern not found",
    ["gauge_name", "prefix"],
)
SCRAPE_SUCCESS = Gauge(
    "isilon_exporter_last_scrape_successful",
    "1 if last scrape succeeded, 0 otherwise",
    ["cluster_name"],
)
API_ERROR_COUNTER = Counter(
    "isilon_exporter_api_errors_total", "Total failed API calls", ["endpoint"]
)

# v1.2 metric families
EVENT_INFO = Gauge(
    "isilon_cluster_event_info",
    "OneFS cluster event present (1)",
    ["cluster_name", "severity", "event_id", "node_id"],
)
EVENT_TS = Gauge(
    "isilon_cluster_event_timestamp_seconds",
    "Unix timestamp of OneFS cluster event",
    ["cluster_name", "severity", "event_id", "node_id"],
)
SNAPSHOT_COUNT = Gauge("isilon_snapshot_count", "Number of snapshots", ["cluster_name"])
SNAPSHOT_BYTES = Gauge(
    "isilon_snapshot_bytes_total",
    "Total bytes consumed by snapshots",
    ["cluster_name"],
)
POOL_TOTAL = Gauge(
    "isilon_storagepool_bytes_total",
    "Storage pool total bytes",
    ["cluster_name", "pool"],
)
POOL_USED = Gauge(
    "isilon_storagepool_bytes_used",
    "Storage pool used bytes",
    ["cluster_name", "pool"],
)
NODE_TEMP = Gauge(
    "isilon_node_temp_celsius",
    "Hardware temperature sensor (Celsius)",
    ["cluster_name", "node_id", "sensor"],
)
NODE_FAN = Gauge(
    "isilon_node_fan_rpm", "Fan speed (RPM)", ["cluster_name", "node_id", "sensor"]
)
NODE_PSU = Gauge(
    "isilon_node_psu_healthy",
    "PSU health (1=ok)",
    ["cluster_name", "node_id", "sensor"],
)
DEDUPE_SAVED = Gauge(
    "isilon_dedupe_saved_bytes",
    "Bytes saved by deduplication",
    ["cluster_name"],
)
DEDUPE_RATIO = Gauge("isilon_dedupe_ratio", "Deduplication ratio", ["cluster_name"])
CLOUDPOOL_USED = Gauge(
    "isilon_cloudpool_used_bytes",
    "Cloud pool used bytes",
    ["cluster_name", "pool"],
)
CLUSTER_VERSION = Gauge(
    "isilon_cluster_version_info",
    "Cluster OneFS version present (1)",
    ["cluster_name", "version"],
)
NODE_VERSION = Gauge(
    "isilon_node_version_info",
    "Node OneFS version present (1)",
    ["cluster_name", "node_id", "version"],
)
# v2: one series per configured target, visible even if the cluster is down
TARGET_INFO = Gauge(
    "isilon_exporter_target_info",
    "Configured scrape target present (1)",
    ["target", "host", "port"],
)

STAT_PATTERNS = [
    # --- CPU ---
    ("node.cpu.user.avg", NODE_CPU_USER),
    ("node.cpu.user", NODE_CPU_USER),
    ("node.cpu.sys.avg", NODE_CPU_SYS),
    ("node.cpu.sys", NODE_CPU_SYS),
    ("node.cpu.idle.avg", NODE_CPU_IDLE),
    ("node.cpu.idle", NODE_CPU_IDLE),
    # --- Disk ---
    ("node.disk.xfers.busy.avg", NODE_DISK_BUSY),
    ("node.disk.busy.avg", NODE_DISK_BUSY),
    ("node.disk.busy", NODE_DISK_BUSY),
    ("node.disk.xfers.in.rate", NODE_DISK_IOPS_IN),
    ("node.disk.iops.in", NODE_DISK_IOPS_IN),
    ("node.disk.xfers.out.rate", NODE_DISK_IOPS_OUT),
    ("node.disk.iops.out", NODE_DISK_IOPS_OUT),
    ("node.disk.bytes.in.rate", NODE_DISK_BW_IN),
    ("node.disk.xfer.size.in", NODE_DISK_BW_IN),
    ("node.disk.bytes.out.rate", NODE_DISK_BW_OUT),
    ("node.disk.xfer.size.out", NODE_DISK_BW_OUT),
    # --- Network ---
    ("node.net.ext.bytes.in.rate", NODE_NET_IN),
    ("node.net.bytes.in.rate", NODE_NET_IN),
    ("node.net.bytes.in", NODE_NET_IN),
    ("node.net.ext.bytes.out.rate", NODE_NET_OUT),
    ("node.net.bytes.out.rate", NODE_NET_OUT),
    ("node.net.bytes.out", NODE_NET_OUT),
    # --- Memory (bytes) ---
    ("node.mem.used.pct", NODE_MEM_USED_BYTES),
    ("node.memory.used.pct", NODE_MEM_USED_BYTES),
    ("node.mem.used", NODE_MEM_USED_BYTES),
    ("node.memory.used", NODE_MEM_USED_BYTES),
    ("node.mem.free", NODE_MEM_USED_BYTES),
    ("node.memory.free", NODE_MEM_USED_BYTES),
    ("node.mem.used.bytes", NODE_MEM_USED_BYTES),
    ("node.memory.used.bytes", NODE_MEM_USED_BYTES),
]

# --- App & Client Setup ---
app = FastAPI(title="PowerScale Exporter")
app.mount("/metrics", make_asgi_app())


class _MetricsAuthMiddleware(BaseHTTPMiddleware):
    """v1.2: optional bearer-token gate for /metrics/.

    Enabled only when METRICS_AUTH_TOKEN is set. Health and readiness
    endpoints stay open so k8s probes and load balancers keep working.
    """

    async def dispatch(self, request, call_next):
        if METRICS_AUTH_TOKEN and request.url.path.startswith("/metrics"):
            want = f"Bearer {METRICS_AUTH_TOKEN}"
            if request.headers.get("authorization", "") != want:
                return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)


app.add_middleware(_MetricsAuthMiddleware)


class ClusterScraper:
    """v2: per-cluster scrape state. One instance per entry in TARGETS.

    All discovery results, timing state, and the OneFS client live here so
    a single exporter process can scrape many clusters. Prometheus gauges
    stay module-global -- every metric already carries a ``cluster_name``
    label.
    """

    def __init__(self, target: dict):
        self.target = target
        self.name = target["name"]
        self.client = OneFSClient(
            target["host"], target["port"], target["user"], target["password"]
        )
        self.cpu_stat_key: str | None = None
        self.node_endpoint: tuple[str, str] | None = None
        self.active_stat_map: dict = {}
        self.cpu_core_count: int = 1
        self.known_nodes_last_seen: dict[str, float] = {}
        self.drive_endpoint: tuple[str, str] | None = None
        self.replication_lag_key: str | None = None
        self.cap_total_key: str | None = None
        self.cap_used_key: str | None = None
        self.events_endpoint: tuple[str, str] | None = None
        self.snapshots_endpoint: tuple[str, str] | None = None
        self.pools_endpoint: tuple[str, str] | None = None
        self.sensors_endpoint: tuple[str, str] | None = None
        self.dedupe_endpoint: tuple[str, str] | None = None
        self.cloudpools_endpoint: tuple[str, str] | None = None
        self.known_events: set[tuple] = set()
        self.last_slow_run: float = 0.0
        self.ready: bool = False
        self.cluster_name: str = "unknown_cluster"
        # v2: visible even when the cluster is unreachable
        TARGET_INFO.labels(
            target=self.name, host=target["host"], port=str(target["port"])
        ).set(1)

    def discover(self) -> None:
        """Run once at startup: probe the cluster for usable endpoints."""
        c = self.client
        log = logger.info
        log(f"[*] [{self.name}] discovering endpoints...")

        self.node_endpoint = _discover_node_endpoint(c)
        self.cpu_stat_key = _discover_cpu_key(c)
        self.cpu_core_count = _discover_cpu_core_count(c)
        self.active_stat_map = _discover_stat_map(c)
        all_keys = _fetch_all_registry_keys(c)
        self.cap_total_key, self.cap_used_key = _discover_capacity_keys(c, all_keys)
        self.drive_endpoint = _discover_drive_endpoint(c)
        self.replication_lag_key = _discover_replication_lag_key(c)
        self.events_endpoint = _discover_endpoint(c, [("3", "event/events")])
        self.snapshots_endpoint = _discover_endpoint(c, [("1", "snapshot/snapshots")])
        self.pools_endpoint = _discover_endpoint(c, [("3", "storagepool/storagepools")])
        self.sensors_endpoint = _discover_endpoint(c, [("3", "hardware/sensors")])
        self.dedupe_endpoint = _discover_endpoint(c, [("3", "dedupe/summary")])
        self.cloudpools_endpoint = _discover_endpoint(c, [("3", "cloud/pools")])
        log(f"[*] [{self.name}] discovery complete.")

    def scrape_slow(self, cluster_name: str) -> None:
        """v1.2: expensive / low-churn collectors, each in its own try block so
        one failing family cannot take down the others."""
        if self.events_endpoint:
            try:
                ver, ep = self.events_endpoint
                events = parse_events(
                    self.client._request("GET", ep, version=ver, params={"limit": 200}),
                    max_events=MAX_EVENTS,
                )
                seen = set()
                for e in events:
                    labels = (
                        cluster_name,
                        e["severity"],
                        e["event_id"],
                        e["node_id"],
                    )
                    seen.add(labels)
                    EVENT_INFO.labels(*labels).set(1)
                    if e["timestamp"]:
                        EVENT_TS.labels(*labels).set(e["timestamp"])
                # Expire events that aged out of the API window (cardinality guard)
                for stale in self.known_events - seen:
                    EVENT_INFO.remove(*stale)
                    EVENT_TS.remove(*stale)
                self.known_events = seen
            except Exception:
                logger.exception("[!] Events collection failed")

        if self.snapshots_endpoint:
            try:
                ver, ep = self.snapshots_endpoint
                count, total = parse_snapshots(
                    self.client._request("GET", ep, version=ver)
                )
                SNAPSHOT_COUNT.labels(cluster_name=cluster_name).set(count)
                if total is not None:
                    SNAPSHOT_BYTES.labels(cluster_name=cluster_name).set(total)
            except Exception:
                logger.exception("[!] Snapshots collection failed")

        if self.pools_endpoint:
            try:
                ver, ep = self.pools_endpoint
                for p in parse_storagepools(
                    self.client._request("GET", ep, version=ver)
                ):
                    if p["total"] is not None:
                        POOL_TOTAL.labels(
                            cluster_name=cluster_name, pool=p["pool"]
                        ).set(p["total"])
                    if p["used"] is not None:
                        POOL_USED.labels(cluster_name=cluster_name, pool=p["pool"]).set(
                            p["used"]
                        )
            except Exception:
                logger.exception("[!] Storage pools collection failed")

        if self.sensors_endpoint:
            try:
                ver, ep = self.sensors_endpoint
                for s in parse_sensors(self.client._request("GET", ep, version=ver)):
                    gauge = {"temp": NODE_TEMP, "fan": NODE_FAN, "psu": NODE_PSU}[
                        s["kind"]
                    ]
                    gauge.labels(
                        cluster_name=cluster_name,
                        node_id=s["node_id"],
                        sensor=s["sensor"],
                    ).set(s["value"])
            except Exception:
                logger.exception("[!] Hardware sensors collection failed")

        if self.dedupe_endpoint:
            try:
                ver, ep = self.dedupe_endpoint
                d = parse_dedupe(self.client._request("GET", ep, version=ver))
                if d:
                    if d["saved_bytes"] is not None:
                        DEDUPE_SAVED.labels(cluster_name=cluster_name).set(
                            d["saved_bytes"]
                        )
                    if d["ratio"] is not None:
                        DEDUPE_RATIO.labels(cluster_name=cluster_name).set(d["ratio"])
            except Exception:
                logger.exception("[!] Dedupe collection failed")

        if self.cloudpools_endpoint:
            try:
                ver, ep = self.cloudpools_endpoint
                for p in parse_cloudpools(self.client._request("GET", ep, version=ver)):
                    if p["used"] is not None:
                        CLOUDPOOL_USED.labels(
                            cluster_name=cluster_name, pool=p["pool"]
                        ).set(p["used"])
            except Exception:
                logger.exception("[!] Cloud pools collection failed")

    def scrape(self) -> None:
        """One fast scrape iteration for this target."""
        loop_start = perf_counter()
        cluster_name = "unknown_cluster"
        quotas: list = []
        try:
            ident = self.client.get_cluster_info()
            cluster_name = ident.get("name", "unknown_cluster")
            self.cluster_name = cluster_name
            total, ok = 0, 0
            node_ids: list[str] = []

            if self.node_endpoint:
                ver, ep = self.node_endpoint
                raw = self.client._request("GET", ep, version=ver)
                nodes: list = []
                if isinstance(raw, dict):
                    nodes = raw.get("nodes") or raw.get("items") or []
                elif isinstance(raw, list):
                    nodes = raw
                for n in nodes:
                    if not isinstance(n, dict):
                        continue
                    total += 1
                    nid = _node_id(n)
                    node_ids.append(nid)
                    healthy = 1 if _node_healthy(n) else 0
                    ok += healthy
                    NODE_STATUS.labels(cluster_name=cluster_name, node_id=nid).set(
                        healthy
                    )
                    now = time.time()
                    self.known_nodes_last_seen[nid] = now
                    NODE_LAST_SEEN.labels(cluster_name=cluster_name, node_id=nid).set(
                        now
                    )
                    # v1.2: per-node OneFS version (best-effort)
                    try:
                        _, nvers = parse_versions(None, [n])
                        for _, v in nvers:
                            NODE_VERSION.labels(
                                cluster_name=cluster_name, node_id=nid, version=v
                            ).set(1)
                    except Exception:
                        logger.debug("node version parse failed", exc_info=True)

            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(
                1 if (total > 0 and ok == total) else 0
            )

            # --- v1.2: cluster + node OneFS versions (no extra API calls:
            # identity was already fetched, nodes enumerated above) ---
            try:
                cluster_ver, _ = parse_versions(ident, [])
                if cluster_ver:
                    CLUSTER_VERSION.labels(
                        cluster_name=cluster_name, version=cluster_ver
                    ).set(1)
            except Exception:
                logger.debug("version parse failed", exc_info=True)

            # --- Per-node stats ---
            if self.active_stat_map:
                for nid in node_ids:
                    for g in set(self.active_stat_map.values()):
                        g.labels(cluster_name=cluster_name, node_id=nid).set(0.0)

                resp = self.client._request(
                    "GET",
                    "statistics/current",
                    version="1",
                    params={
                        "keys": ",".join(self.active_stat_map.keys()),
                        "devid": "all",
                    },
                )
                for stat in resp.get("stats", []):
                    key = stat.get("key", "")
                    devid = str(stat.get("devid", "0"))
                    raw_val = stat.get("value")
                    try:
                        val = float(raw_val) if raw_val is not None else 0.0
                    except (TypeError, ValueError):
                        val = 0.0

                    gauge = self.active_stat_map.get(key)

                    # OneFS reports sum of all per-core CPU ticks.
                    # A 4-core node at 50% idle returns 200 — divide by
                    # core count to get true 0-100%.  Values already under
                    # 100 (e.g. user/sys on a lightly loaded node) are left
                    # untouched because the API already averaged them.
                    if (
                        "cpu" in key.lower()
                        and "count" not in key.lower()
                        and val >= 100.0
                    ):
                        val = val / self.cpu_core_count

                    if "cpu" in key.lower() and "count" not in key:
                        NODE_CPU.labels(cluster_name=cluster_name, node_id=devid).set(
                            val
                        )

                    if gauge:
                        gauge.labels(cluster_name=cluster_name, node_id=devid).set(val)

                        # Set GB memory metric for memory gauges
                        if gauge == NODE_MEM_USED_BYTES:
                            gb_val = val / (1024**3)  # Convert bytes to GB
                            NODE_MEM_USED_GB.labels(
                                cluster_name=cluster_name, node_id=devid
                            ).set(gb_val)

            # --- Tombstone ---
            if self.known_nodes_last_seen:
                current = set(node_ids)
                now = time.time()
                for nid, ts in list(self.known_nodes_last_seen.items()):
                    if (now - ts) > TOMBSTONE_TTL:
                        self.known_nodes_last_seen.pop(nid, None)
                        continue
                    if nid not in current:
                        NODE_STATUS.labels(cluster_name=cluster_name, node_id=nid).set(
                            0
                        )
                        NODE_LAST_SEEN.labels(
                            cluster_name=cluster_name, node_id=nid
                        ).set(ts)

            # --- Cluster capacity ---
            if self.cap_total_key:
                try:
                    r = self.client._request(
                        "GET",
                        "statistics/current",
                        version="1",
                        params={"keys": self.cap_total_key},
                    )
                    s = r.get("stats", [])
                    if s:
                        CLUSTER_CAP_TOTAL.labels(cluster_name=cluster_name).set(
                            float(s[0].get("value") or 0.0)
                        )
                except Exception:
                    logger.exception("[!] Capacity total fetch failed")

            if self.cap_used_key:
                try:
                    r = self.client._request(
                        "GET",
                        "statistics/current",
                        version="1",
                        params={"keys": self.cap_used_key},
                    )
                    s = r.get("stats", [])
                    if s:
                        CLUSTER_CAP_USED.labels(cluster_name=cluster_name).set(
                            float(s[0].get("value") or 0.0)
                        )
                except Exception:
                    logger.exception("[!] Capacity used fetch failed")

            # --- SyncIQ replication lag ---
            if self.replication_lag_key:
                try:
                    r = self.client._request(
                        "GET",
                        "statistics/current",
                        version="1",
                        params={"keys": self.replication_lag_key},
                    )
                    s = r.get("stats", [])
                    if s:
                        REPL_LAG.labels(cluster_name=cluster_name).set(
                            max(float(s[0].get("value") or 0.0), 0.0)
                        )
                except Exception:
                    logger.exception("[!] Replication lag fetch failed")

            # --- Quota / NFS / SMB counts ---
            quotas = self.client.get_paginated("quota/quotas")
            QUOTA_COUNT.labels(cluster_name=cluster_name).set(len(quotas))

            try:
                exports = self.client.get_paginated("protocols/nfs/exports")
                NFS_EXPORT_COUNT.labels(cluster_name=cluster_name).set(len(exports))
            except Exception:
                logger.exception("[!] NFS export count failed")
                NFS_EXPORT_COUNT.labels(cluster_name=cluster_name).set(0)

            try:
                shares = self.client.get_paginated("protocols/smb/shares")
                SMB_SHARE_COUNT.labels(cluster_name=cluster_name).set(len(shares))
            except Exception:
                logger.exception("[!] SMB share count failed")
                SMB_SHARE_COUNT.labels(cluster_name=cluster_name).set(0)

            # --- Drive health + performance (independent try blocks) ---
            if self.drive_endpoint:

                try:
                    health_data = self.client._request(
                        "GET", "statistics/summary/drive", version="3"
                    )
                    logger.info(f"[DEBUG] Raw drive health response: {health_data}")

                    # Try multiple possible response structures
                    drives = []
                    if isinstance(health_data, dict):
                        # Try different field names that might contain drive data
                        for field_name in [
                            "drive",
                            "drives",
                            "items",
                            "drive_health",
                            "drive_status",
                        ]:
                            field_data = health_data.get(field_name)
                            if isinstance(field_data, list) and field_data:
                                drives = field_data
                                logger.info(
                                    f"[DEBUG] Found {len(drives)} drives in field '{field_name}'"
                                )
                                break
                            elif isinstance(field_data, dict):
                                # Some APIs return dict with nested arrays
                                for sub_field in ["data", "entries", "results"]:
                                    sub_data = field_data.get(sub_field)
                                    if isinstance(sub_data, list) and sub_data:
                                        drives = sub_data
                                        logger.info(
                                            f"[DEBUG] Found {len(drives)} drives in '{field_name}.{sub_field}'"
                                        )
                                        break
                    elif isinstance(health_data, list):
                        drives = health_data
                        logger.info(
                            f"[DEBUG] Response is list with {len(drives)} drives"
                        )

                    logger.info(f"[DEBUG] Total drives to process: {len(drives)}")

                    if not drives:
                        logger.warning(
                            "[DEBUG] No drives found in response - checking response structure"
                        )
                        if isinstance(health_data, dict):
                            logger.info(
                                f"[DEBUG] Available fields: {list(health_data.keys())}"
                            )
                            for key, value in health_data.items():
                                if isinstance(value, (list, dict)):
                                    logger.info(
                                        f"[DEBUG] Field '{key}' type: {type(value)}, size: {len(value) if hasattr(value, '__len__') else 'N/A'}"
                                    )

                    for i, d in enumerate(drives):
                        logger.debug(f"[DEBUG] Processing drive {i}: {d}")

                        # Extract drive_id from the response (format: "node:drive")
                        drive_id_raw = str(d.get("drive_id", ""))
                        if not drive_id_raw or drive_id_raw in ("", "none", "null"):
                            logger.debug(
                                f"[DEBUG] Drive {i}: missing drive_id '{drive_id_raw}', skipping"
                            )
                            continue

                        logger.debug(
                            f"[DEBUG] Drive {i}: drive_id_raw='{drive_id_raw}'"
                        )

                        # Parse drive_id format "node:drive" to get node_id and drive_id
                        node_id = None
                        drive_id = None

                        if ":" in drive_id_raw:
                            # Format: "1:1" (node:drive)
                            parts = drive_id_raw.split(":", 1)
                            if len(parts) == 2:
                                node_id, drive_id = parts
                                logger.debug(
                                    f"[DEBUG] Parsed drive_id format: node='{node_id}', drive='{drive_id}'"
                                )
                        elif "." in drive_id_raw:
                            # Format: "1.1" (node.drive)
                            parts = drive_id_raw.split(".", 1)
                            if len(parts) == 2:
                                node_id, drive_id = parts
                                logger.debug(
                                    f"[DEBUG] Parsed dot format: node='{node_id}', drive='{drive_id}'"
                                )
                        else:
                            # Single value - unlikely for this API
                            logger.warning(
                                f"[DEBUG] Drive {i}: unexpected drive_id format '{drive_id_raw}'"
                            )
                            continue

                        if not node_id or not drive_id:
                            logger.warning(
                                f"[DEBUG] Drive {i}: could not parse node/drive from drive_id '{drive_id_raw}'"
                            )
                            continue

                        # Determine drive health from available fields
                        drive_type = str(d.get("type", "")).upper()
                        busy = float(d.get("busy", 0.0))
                        access_latency = float(d.get("access_latency", 0.0))
                        iosched_queue = float(d.get("iosched_queue", 0.0))

                        logger.debug(
                            f"[DEBUG] Drive {i}: node={node_id}, drive={drive_id}, type='{drive_type}', busy={busy}, latency={access_latency}, queue={iosched_queue}"
                        )

                        # Health inference logic:
                        # - UNKNOWN type = unhealthy/offline
                        # - High busy percentage or latency = degraded
                        # - Normal values = healthy
                        is_healthy = 1
                        if drive_type == "UNKNOWN":
                            is_healthy = 0
                            logger.debug(
                                f"[DEBUG] Drive {i}: marked unhealthy due to UNKNOWN type"
                            )
                        elif busy > 90.0 or access_latency > 50.0:
                            is_healthy = 0
                            logger.debug(
                                f"[DEBUG] Drive {i}: marked degraded due to high busy={busy}% or latency={access_latency}ms"
                            )
                        else:
                            logger.debug(f"[DEBUG] Drive {i}: marked healthy")

                        # Set drive health metric
                        DRIVE_HEALTH.labels(
                            cluster_name=cluster_name,
                            node_id=node_id,
                            drive_id=drive_id,
                        ).set(is_healthy)

                        # Set drive busy percentage metric
                        DRIVE_BUSY.labels(
                            cluster_name=cluster_name,
                            node_id=node_id,
                            drive_id=drive_id,
                        ).set(busy)

                        # Set drive latency metric (convert to milliseconds)
                        DRIVE_LATENCY.labels(
                            cluster_name=cluster_name,
                            node_id=node_id,
                            drive_id=drive_id,
                        ).set(access_latency * 1000)

                        # Set drive queue depth metric
                        DRIVE_QUEUE.labels(
                            cluster_name=cluster_name,
                            node_id=node_id,
                            drive_id=drive_id,
                        ).set(iosched_queue)

                        logger.debug(
                            f"[DEBUG] Drive {i}: set all metrics - health={is_healthy}, busy={busy}, latency={access_latency}ms, queue={iosched_queue}"
                        )

                    logger.info(
                        f"[DEBUG] Successfully processed {len(drives)} drive health and performance metrics"
                    )

                except Exception as e:
                    logger.exception("[!] Drive health API failed")
                    logger.error(f"[DEBUG] Exception type: {type(e).__name__}")
                    logger.error(f"[DEBUG] Exception args: {e.args}")

                # Skip the separate performance API call since we get all data from health endpoint
                logger.debug(
                    "[DEBUG] Skipping separate drive performance API - using health endpoint data"
                )

            # --- v1.2: slow collectors (events, snapshots, pools, sensors,
            # dedupe, cloud pools) on their own cadence ---
            _now = time.time()
            if _now - self.last_slow_run >= SLOW_SCRAPE_INTERVAL:
                self.last_slow_run = _now
                self.scrape_slow(cluster_name)

            # First fully successful scrape -> /readyz goes 200
            self.ready = True

        except Exception:
            logger.exception(f"SCRAPE_FAIL | cluster={cluster_name}")
            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(0)
            SCRAPE_SUCCESS.labels(cluster_name=cluster_name).set(0)
            SCRAPE_DURATION.observe(max(perf_counter() - loop_start, 0.0))


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _discover_node_endpoint(client) -> tuple[str, str] | None:
    for ver, ep in [
        ("3", "cluster/nodes"),
        ("1", "cluster/nodes"),
        ("3", "nodes"),
        ("1", "nodes"),
    ]:
        try:
            raw = client._request("GET", ep, version=ver)
            if isinstance(raw, dict):
                logger.info(f"[DISCOVER] v{ver}/{ep} -> keys: {list(raw.keys())}")
                for val in raw.values():
                    if isinstance(val, list) and val:
                        return ver, ep
            elif isinstance(raw, list) and raw:
                return ver, ep
        except Exception as e:  # noqa: BLE001 -- probe: any failure means try next
            logger.info(f"[DISCOVER] v{ver}/{ep} -> {e}")
    return None


def _fetch_all_registry_keys(client) -> list[str]:
    all_keys: list[str] = []
    params: dict = {"limit": 1000}
    while True:
        try:
            data = client._request("GET", "statistics/keys", version="1", params=params)
        except Exception as e:  # noqa: BLE001 -- probe: any failure means try next
            logger.error(f"[DISCOVER] statistics/keys error: {e}")
            break
        keys_list = (
            data.get("keys", [])
            if isinstance(data, dict)
            else (data if isinstance(data, list) else [])
        )
        for entry in keys_list:
            name = entry if isinstance(entry, str) else entry.get("key", "")
            if name:
                all_keys.append(name)
        resume = data.get("resume") if isinstance(data, dict) else None
        if not resume:
            break
        params = {"resume": resume}
    return all_keys


def _validate_key(client, key: str) -> bool:
    try:
        resp = client._request(
            "GET",
            "statistics/current",
            version="1",
            params={"keys": key, "devid": "all"},
        )
        return bool(isinstance(resp, dict) and resp.get("stats"))
    except Exception:
        logger.debug("stat key validation failed", exc_info=True)
        return False


def _discover_cpu_key(client) -> str | None:
    logger.info("[DISCOVER] Querying statistics key registry for cpu keys...")
    cpu_keys = []
    params = {"limit": 1000}
    while True:
        try:
            data = client._request("GET", "statistics/keys", version="1", params=params)
        except Exception as e:  # noqa: BLE001 -- probe: any failure means try next
            logger.error(f"[DISCOVER] statistics/keys failed: {e}")
            break
        keys_list = (
            data.get("keys", [])
            if isinstance(data, dict)
            else (data if isinstance(data, list) else [])
        )
        for entry in keys_list:
            name = entry if isinstance(entry, str) else entry.get("key", "")
            if "cpu" in str(name).lower():
                cpu_keys.append(name)
        resume = data.get("resume") if isinstance(data, dict) else None
        if not resume:
            break
        params = {"resume": resume}
    logger.info(f"[DISCOVER] CPU-related keys found ({len(cpu_keys)}): {cpu_keys[:30]}")
    for key in cpu_keys:
        try:
            resp = client._request(
                "GET", "statistics/current", version="1", params={"keys": key}
            )
            if isinstance(resp, dict) and resp.get("stats"):
                logger.info(f"[DISCOVER] Valid CPU key: '{key}'")
                return key
        except Exception as e:  # noqa: BLE001 -- probe: any failure means try next key
            logger.debug(f"[DISCOVER] CPU key '{key}' probe failed: {e}")
    return None


def _discover_cpu_core_count(client) -> int:
    """
    Three-stage discovery so a 500 on v1/statistics/current does not
    strand us at core_count=1 and silently inflate CPU percentages.

    Stage 1: query node.cpu.count with devid=all
    Stage 2: query node.cpu.count without devid=all
    Stage 3: count numbered per-core idle keys in the registry
             (node.cpu.idle.0, node.cpu.idle.1, ...) — works even
             when statistics/current is returning 500s
    """
    for params in (
        {"keys": "node.cpu.count", "devid": "all"},
        {"keys": "node.cpu.count"},
    ):
        try:
            resp = client._request(
                "GET", "statistics/current", version="1", params=params
            )
            stats = resp.get("stats", [])
            if stats:
                count = int(stats[0].get("value") or 1)
                if count > 1:
                    logger.info(
                        f"[DISCOVER] CPU core count: {count} (via statistics/current)"
                    )
                    return count
        except Exception as e:  # noqa: BLE001 -- probe: any failure means try next
            logger.debug(f"[DISCOVER] CPU core count probe failed: {e}")

    try:
        all_keys = _fetch_all_registry_keys(client)
        core_keys = [
            k
            for k in all_keys
            if k.startswith("node.cpu.idle.") and k.split(".")[-1].isdigit()
        ]
        if core_keys:
            count = len(core_keys)
            logger.info(
                f"[DISCOVER] CPU core count: {count} (inferred from {count} per-core idle keys in registry)"
            )
            return max(count, 1)
    except Exception as e:  # noqa: BLE001 -- probe: any failure means try next
        logger.error(f"[DISCOVER] CPU core count stage-3 fallback failed: {e}")

    logger.error(
        "[DISCOVER] CPU core count could not be determined — defaulting to 1 (CPU % will be inflated)"
    )
    return 1


def _discover_stat_map(client) -> dict:
    logger.info("[DISCOVER] Building stat map from key registry...")
    all_keys = _fetch_all_registry_keys(client)
    cpu_disk_net_mem = [
        k
        for k in all_keys
        if any(s in k.lower() for s in ("cpu", "disk", "net", "mem"))
    ]
    logger.info(f"[DISCOVER] Total candidate keys: {len(cpu_disk_net_mem)}")
    stat_map: dict = {}
    claimed_gauges: set[int] = set()
    for prefix, gauge in STAT_PATTERNS:
        if id(gauge) in claimed_gauges:
            continue
        matches = [k for k in cpu_disk_net_mem if k.startswith(prefix)]
        if not matches:
            continue
        matches.sort(key=lambda k: (0 if ("avg" in k or "rate" in k) else 1, len(k), k))
        for candidate in matches:
            if _validate_key(client, candidate):
                logger.info(f"[DISCOVER]   '{prefix}' -> '{candidate}'")
                stat_map[candidate] = gauge
                claimed_gauges.add(id(gauge))
                break
    claimed_names = {g.__class__.__name__ for g in stat_map.values()}
    for prefix, gauge in STAT_PATTERNS:
        if id(gauge) not in claimed_gauges:
            gauge_name = [name for name, val in globals().items() if val is gauge]
            label = gauge_name[0] if gauge_name else "unknown"
            if label not in claimed_names:
                logger.info(f"[DISCOVER]   no valid key found for gauge {label}")
                STATPATTERN_MISS.labels(gauge_name=label, prefix=prefix).inc()
                claimed_names.add(label)
    logger.info(
        f"[DISCOVER] Final stat map ({len(stat_map)} keys): {list(stat_map.keys())}"
    )
    return stat_map


def _discover_drive_endpoint(client) -> tuple[str, str] | None:
    candidates = [
        ("3", "statistics/summary/drive"),
        ("1", "statistics/summary/drive"),
        ("1", "statistics/current"),
        ("3", "storagepool/storagepools"),
        ("3", "hardware/components/drives"),
        ("3", "storagepool/drives"),
        ("3", "hardware/drives"),
        ("2", "hardware/drives"),
    ]
    for ver, ep in candidates:
        try:
            logger.info(f"[DEBUG] Testing drive endpoint: v{ver}/{ep}")
            raw = client._request("GET", ep, version=ver, params={"limit": 5})
            logger.info(f"[DEBUG] Raw response from v{ver}/{ep}: {raw}")

            # Enhanced validation
            is_valid = False
            if isinstance(raw, dict):
                # Check for any list fields that might contain drive data
                for key, value in raw.items():
                    if isinstance(value, list) and value:
                        logger.info(
                            f"[DEBUG] Found list field '{key}' with {len(value)} items"
                        )
                        # Sample first item to see if it looks like drive data
                        if value[0] and isinstance(value[0], dict):
                            sample_keys = list(value[0].keys())
                            logger.info(f"[DEBUG] Sample item keys: {sample_keys}")
                            # Look for drive-like fields
                            drive_indicators = [
                                "drive",
                                "node",
                                "bay",
                                "status",
                                "health",
                                "device",
                            ]
                            if any(
                                indicator in str(sample_keys).lower()
                                for indicator in drive_indicators
                            ):
                                is_valid = True
                                logger.info(f"[DEBUG] Found drive indicators in {key}")
                                break
                    elif isinstance(value, dict) and value:
                        # Check nested dict structures
                        for sub_key, sub_value in value.items():
                            if isinstance(sub_value, list) and sub_value:
                                logger.info(
                                    f"[DEBUG] Found nested list '{key}.{sub_key}' with {len(sub_value)} items"
                                )
                                is_valid = True
                                break
                        if is_valid:
                            break
            elif isinstance(raw, list) and raw:
                logger.info(f"[DEBUG] Response is list with {len(raw)} items")
                if raw[0] and isinstance(raw[0], dict):
                    sample_keys = list(raw[0].keys())
                    logger.info(f"[DEBUG] Sample item keys: {sample_keys}")
                    drive_indicators = [
                        "drive",
                        "node",
                        "bay",
                        "status",
                        "health",
                        "device",
                    ]
                    if any(
                        indicator in str(sample_keys).lower()
                        for indicator in drive_indicators
                    ):
                        is_valid = True
                        logger.info("[DEBUG] Found drive indicators in direct list")

            if is_valid:
                logger.info(f"[DISCOVER] drive endpoint OK: v{ver}/{ep}")
                return ver, ep
            else:
                logger.info(f"[DEBUG] v{ver}/{ep} does not contain drive-like data")

        except Exception as e:  # noqa: BLE001 -- probe: any failure means try next
            logger.info(f"[DISCOVER] drive endpoint v{ver}/{ep} -> {e}")
            logger.debug(f"[DEBUG] Exception details: {type(e).__name__}: {e}")

    logger.info("[DISCOVER] No drive endpoint discovered; drive metrics skipped.")
    return None


def _discover_replication_lag_key(client) -> str | None:
    keys = _fetch_all_registry_keys(client)
    cands = [
        k
        for k in keys
        if ("sync" in k.lower() or "siq" in k.lower() or "replication" in k.lower())
        and "lag" in k.lower()
    ]
    for k in sorted(cands):
        if _validate_key(client, k):
            logger.info(f"[DISCOVER] replication lag key: {k}")
            return k
    logger.info("[DISCOVER] No replication lag key found.")
    return None


def _discover_capacity_keys(
    client, all_keys: list[str]
) -> tuple[str | None, str | None]:
    total_patterns = ["ifs.bytes.total", "cluster.bytes.total", "fs.bytes.total"]
    used_patterns = ["ifs.bytes.used", "cluster.bytes.used", "fs.bytes.used"]

    def _first_match(patterns):
        for pat in patterns:
            for k in [k for k in all_keys if pat in k]:
                if _validate_key(client, k):
                    logger.info(f"[DISCOVER] capacity key: '{k}'")
                    return k
        return None

    total_key = _first_match(total_patterns)
    used_key = _first_match(used_patterns)
    if not total_key:
        logger.info("[DISCOVER] No capacity total key found.")
    if not used_key:
        logger.info("[DISCOVER] No capacity used key found.")
    return total_key, used_key


def _discover_endpoint(
    client, candidates: list[tuple[str, str]]
) -> tuple[str, str] | None:
    """v1.2: probe (version, endpoint) candidates; return the first whose
    response is a non-empty dict or list. Best-effort -- a miss just means
    that metric family is skipped, like the drive endpoint discovery."""
    for ver, ep in candidates:
        try:
            raw = client._request("GET", ep, version=ver, params={"limit": 5})
            if isinstance(raw, dict) and raw:
                logger.info(f"[DISCOVER] endpoint OK: v{ver}/{ep}")
                return ver, ep
            if isinstance(raw, list) and raw:
                logger.info(f"[DISCOVER] endpoint OK: v{ver}/{ep}")
                return ver, ep
        except Exception:
            logger.debug(f"[DISCOVER] v{ver}/{ep} probe failed", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Per-node helpers
# ---------------------------------------------------------------------------


def _node_id(n: dict) -> str:
    return str(
        n.get("id") or n.get("lnn") or n.get("name") or n.get("devid") or "unknown"
    )


def _node_healthy(n: dict) -> bool:
    sf: dict = {}
    try:
        sf = (n.get("state") or {}).get("smartfail") or {}
    except Exception:
        logger.debug("node smartfail state unreadable; assuming healthy", exc_info=True)
        sf = {}
    if sf:
        return (
            bool(sf.get("in_cluster", True))
            and not bool(sf.get("down", False))
            and not bool(sf.get("smartfailed", False))
        )
    status_str = ""
    for key in ("status", "health", "state"):
        v = n.get(key)
        if isinstance(v, str):
            status_str = v.strip().upper()
            break
    return status_str in ("OK", "HEALTHY", "GOOD", "UP", "ONLINE", "")

    # ---------------------------------------------------------------------------
    # Scrape loop
    # ---------------------------------------------------------------------------


def collect_metrics():
    """v2: one thread scraping all configured targets sequentially."""
    global _scrapers
    logger.info(f"[*] Scraper thread started — polling every {SCRAPE_INTERVAL}s")

    scrapers = []
    for t in TARGETS:
        try:
            s = ClusterScraper(t)
            scrapers.append(s)
        except Exception:
            logger.exception(f"[!] [{t['name']}] target init failed — skipping")
    if not scrapers:
        logger.error("[!] No usable targets — scraper idle.")
    _scrapers = scrapers

    for s in scrapers:
        try:
            s.discover()
        except Exception:
            logger.exception(f"[!] [{s.name}] discovery failed")

    while True:
        for s in scrapers:
            try:
                s.scrape()
            except Exception:
                logger.exception(f"[!] [{s.name}] scrape iteration failed")
        time.sleep(SCRAPE_INTERVAL)


# v2: populated by collect_metrics(); read by /healthz and /readyz.
_scrapers: list = []


bg_thread = threading.Thread(target=collect_metrics, daemon=True)
bg_thread.start()


@app.get("/healthz")
def healthcheck():
    from fastapi.responses import JSONResponse

    if not bg_thread.is_alive():
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reason": "scraper thread dead"},
        )
    return {
        "status": "online",
        "scraper_alive": True,
        "targets": [
            {
                "target": s.name,
                "cluster_name": s.cluster_name,
                "ready": s.ready,
                "cpu_key": s.cpu_stat_key,
                "cpu_core_count": s.cpu_core_count,
                "node_endpoint": s.node_endpoint,
                "active_stat_map": list(s.active_stat_map.keys()),
            }
            for s in _scrapers
        ],
    }


@app.get("/livez")
def livez():
    """v1.2: liveness -- the process is up. Cheap, always 200."""
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    """v2: readiness -- 200 once at least one target has completed a
    successful scrape, so k8s doesn't send traffic to a pod serving empty
    metrics. Per-target status is included in the response."""
    ready = [s.name for s in _scrapers if s.ready]
    if ready:
        return {"status": "ready", "ready_targets": ready}
    return JSONResponse(
        status_code=503,
        content={"status": "not ready", "reason": "no successful scrape yet"},
    )


@app.get("/", include_in_schema=False)
def root():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    # v1.2: optional native TLS. Set both TLS_CERT_FILE and TLS_KEY_FILE
    # (e.g. mounted from a k8s Secret) to serve HTTPS on :8000.
    _ssl: dict = {}
    if TLS_CERT_FILE and TLS_KEY_FILE:
        _ssl = {"ssl_certfile": TLS_CERT_FILE, "ssl_keyfile": TLS_KEY_FILE}
        logger.info("[*] TLS enabled for :8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, **_ssl)
