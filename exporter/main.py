import logging
import os
import threading
import time
from time import perf_counter

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from scraper import OneFSClient

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

if not ISILON_PASS:
    raise RuntimeError("ISILON_PASS is not set: refusing to start without a password")

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
client = OneFSClient(ISILON_HOST, ISILON_PORT, ISILON_USER, ISILON_PASS)

_cpu_stat_key: str | None = None
_node_endpoint: tuple[str, str] | None = None
_active_stat_map: dict = {}
_cpu_core_count: int = 1
_known_nodes_last_seen: dict[str, float] = {}
_drive_endpoint: tuple[str, str] | None = None
_replication_lag_key: str | None = None
_cap_total_key: str | None = None
_cap_used_key: str | None = None

# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _discover_node_endpoint() -> tuple[str, str] | None:
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


def _fetch_all_registry_keys() -> list[str]:
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


def _validate_key(key: str) -> bool:
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


def _discover_cpu_key() -> str | None:
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


def _discover_cpu_core_count() -> int:
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
        all_keys = _fetch_all_registry_keys()
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


def _discover_stat_map() -> dict:
    logger.info("[DISCOVER] Building stat map from key registry...")
    all_keys = _fetch_all_registry_keys()
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
            if _validate_key(candidate):
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


def _discover_drive_endpoint() -> tuple[str, str] | None:
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


def _discover_replication_lag_key() -> str | None:
    keys = _fetch_all_registry_keys()
    cands = [
        k
        for k in keys
        if ("sync" in k.lower() or "siq" in k.lower() or "replication" in k.lower())
        and "lag" in k.lower()
    ]
    for k in sorted(cands):
        if _validate_key(k):
            logger.info(f"[DISCOVER] replication lag key: {k}")
            return k
    logger.info("[DISCOVER] No replication lag key found.")
    return None


def _discover_capacity_keys(all_keys: list[str]) -> tuple[str | None, str | None]:
    total_patterns = ["ifs.bytes.total", "cluster.bytes.total", "fs.bytes.total"]
    used_patterns = ["ifs.bytes.used", "cluster.bytes.used", "fs.bytes.used"]

    def _first_match(patterns):
        for pat in patterns:
            for k in [k for k in all_keys if pat in k]:
                if _validate_key(k):
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
    global _cpu_stat_key, _node_endpoint, _active_stat_map, _cpu_core_count
    global _drive_endpoint, _replication_lag_key, _cap_total_key, _cap_used_key

    logger.info(f"[*] Scraper thread started — polling every {SCRAPE_INTERVAL}s")

    _node_endpoint = _discover_node_endpoint()
    if _node_endpoint:
        logger.info(f"[*] Node endpoint: v{_node_endpoint[0]}/{_node_endpoint[1]}")
    else:
        logger.error("[!] No node endpoint discovered — node metrics will be skipped.")

    _cpu_stat_key = _discover_cpu_key()
    _cpu_core_count = _discover_cpu_core_count()
    logger.info(f"[*] CPU core count resolved: {_cpu_core_count}")

    _active_stat_map = _discover_stat_map()
    if not _active_stat_map:
        logger.error("[!] No cpu/disk/net/mem stat keys resolved.")

    _all_keys = _fetch_all_registry_keys()
    _cap_total_key, _cap_used_key = _discover_capacity_keys(_all_keys)

    _drive_endpoint = _discover_drive_endpoint()
    _replication_lag_key = _discover_replication_lag_key()

    while True:
        loop_start = perf_counter()
        cluster_name = "unknown_cluster"
        quotas: list = []
        try:
            ident = client.get_cluster_info()
            cluster_name = ident.get("name", "unknown_cluster")
            total, ok = 0, 0
            node_ids: list[str] = []

            if _node_endpoint:
                ver, ep = _node_endpoint
                raw = client._request("GET", ep, version=ver)
                nodes = []
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
                    _known_nodes_last_seen[nid] = now
                    NODE_LAST_SEEN.labels(cluster_name=cluster_name, node_id=nid).set(
                        now
                    )

            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(
                1 if (total > 0 and ok == total) else 0
            )

            # --- Per-node stats ---
            if _active_stat_map:
                for nid in node_ids:
                    for g in set(_active_stat_map.values()):
                        g.labels(cluster_name=cluster_name, node_id=nid).set(0.0)

                resp = client._request(
                    "GET",
                    "statistics/current",
                    version="1",
                    params={"keys": ",".join(_active_stat_map.keys()), "devid": "all"},
                )
                for stat in resp.get("stats", []):
                    key = stat.get("key", "")
                    devid = str(stat.get("devid", "0"))
                    raw_val = stat.get("value")
                    try:
                        val = float(raw_val) if raw_val is not None else 0.0
                    except (TypeError, ValueError):
                        val = 0.0

                    gauge = _active_stat_map.get(key)

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
                        val = val / _cpu_core_count

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
            if _known_nodes_last_seen:
                current = set(node_ids)
                now = time.time()
                for nid, ts in list(_known_nodes_last_seen.items()):
                    if (now - ts) > TOMBSTONE_TTL:
                        _known_nodes_last_seen.pop(nid, None)
                        continue
                    if nid not in current:
                        NODE_STATUS.labels(cluster_name=cluster_name, node_id=nid).set(
                            0
                        )
                        NODE_LAST_SEEN.labels(
                            cluster_name=cluster_name, node_id=nid
                        ).set(ts)

            # --- Cluster capacity ---
            if _cap_total_key:
                try:
                    r = client._request(
                        "GET",
                        "statistics/current",
                        version="1",
                        params={"keys": _cap_total_key},
                    )
                    s = r.get("stats", [])
                    if s:
                        CLUSTER_CAP_TOTAL.labels(cluster_name=cluster_name).set(
                            float(s[0].get("value") or 0.0)
                        )
                except Exception:
                    logger.exception("[!] Capacity total fetch failed")

            if _cap_used_key:
                try:
                    r = client._request(
                        "GET",
                        "statistics/current",
                        version="1",
                        params={"keys": _cap_used_key},
                    )
                    s = r.get("stats", [])
                    if s:
                        CLUSTER_CAP_USED.labels(cluster_name=cluster_name).set(
                            float(s[0].get("value") or 0.0)
                        )
                except Exception:
                    logger.exception("[!] Capacity used fetch failed")

            # --- SyncIQ replication lag ---
            if _replication_lag_key:
                try:
                    r = client._request(
                        "GET",
                        "statistics/current",
                        version="1",
                        params={"keys": _replication_lag_key},
                    )
                    s = r.get("stats", [])
                    if s:
                        REPL_LAG.labels(cluster_name=cluster_name).set(
                            max(float(s[0].get("value") or 0.0), 0.0)
                        )
                except Exception:
                    logger.exception("[!] Replication lag fetch failed")

            # --- Quota / NFS / SMB counts ---
            quotas = client.get_paginated("quota/quotas")
            QUOTA_COUNT.labels(cluster_name=cluster_name).set(len(quotas))

            try:
                exports = client.get_paginated("protocols/nfs/exports")
                NFS_EXPORT_COUNT.labels(cluster_name=cluster_name).set(len(exports))
            except Exception:
                logger.exception("[!] NFS export count failed")
                NFS_EXPORT_COUNT.labels(cluster_name=cluster_name).set(0)

            try:
                shares = client.get_paginated("protocols/smb/shares")
                SMB_SHARE_COUNT.labels(cluster_name=cluster_name).set(len(shares))
            except Exception:
                logger.exception("[!] SMB share count failed")
                SMB_SHARE_COUNT.labels(cluster_name=cluster_name).set(0)

            # --- Drive health + performance (independent try blocks) ---
            if _drive_endpoint:

                try:
                    health_data = client._request(
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

        except Exception:
            logger.exception(f"SCRAPE_FAIL | cluster={cluster_name}")
            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(0)
            SCRAPE_SUCCESS.labels(cluster_name=cluster_name).set(0)
            SCRAPE_DURATION.observe(max(perf_counter() - loop_start, 0.0))

        time.sleep(SCRAPE_INTERVAL)


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
        "cluster_host": ISILON_HOST,
        "cpu_key": _cpu_stat_key,
        "cpu_core_count": _cpu_core_count,
        "node_endpoint": _node_endpoint,
        "active_stat_map": list(_active_stat_map.keys()),
        "cap_total_key": _cap_total_key,
        "cap_used_key": _cap_used_key,
        "scraper_alive": True,
    }


@app.get("/", include_in_schema=False)
def root():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
