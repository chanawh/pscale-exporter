import threading
import time
import os
from fastapi import FastAPI
from prometheus_client import make_asgi_app, Gauge
from scraper import OneFSClient

# --- Configuration ---
def _int_env(name, default):
    v = (os.getenv(name) or "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default

ISILON_HOST     = os.getenv("ISILON_HOST", "127.0.0.1")
ISILON_PORT     = _int_env("ISILON_PORT", 8080)
ISILON_USER     = os.getenv("ISILON_USER", "root")
ISILON_PASS     = os.getenv("ISILON_PASS", "a")
SCRAPE_INTERVAL = _int_env("SCRAPE_INTERVAL", 30)

# --- Prometheus Metrics ---
CLUSTER_HEALTH = Gauge("isilon_cluster_health", "Cluster health (1=OK, 0=Error)", ["cluster_name"])
NODE_STATUS    = Gauge("isilon_node_status", "Node status (1=OK, 0=Error)", ["cluster_name", "node_id"])
NODE_CPU       = Gauge("isilon_node_cpu_value", "CPU-related statistic value per node.", ["cluster_name", "node_id"])
QUOTA_COUNT    = Gauge("isilon_quota_total", "Total number of quotas defined.", ["cluster_name"])

# NEW: typed CPU & disk gauges
NODE_CPU_USER      = Gauge("isilon_node_cpu_user_pct",      "CPU user %",        ["cluster_name", "node_id"])
NODE_CPU_SYS       = Gauge("isilon_node_cpu_sys_pct",       "CPU sys %",         ["cluster_name", "node_id"])
NODE_CPU_IDLE      = Gauge("isilon_node_cpu_idle_pct",      "CPU idle %",        ["cluster_name", "node_id"])
NODE_DISK_BUSY     = Gauge("isilon_node_disk_busy_pct",     "Disk busy %",       ["cluster_name", "node_id"])
NODE_DISK_IOPS_IN  = Gauge("isilon_node_disk_iops_in",      "Disk IOPS in",      ["cluster_name", "node_id"])
NODE_DISK_IOPS_OUT = Gauge("isilon_node_disk_iops_out",     "Disk IOPS out",     ["cluster_name", "node_id"])
NODE_DISK_BW_IN    = Gauge("isilon_node_disk_bw_in_bytes",  "Disk bytes/s in",   ["cluster_name", "node_id"])
NODE_DISK_BW_OUT   = Gauge("isilon_node_disk_bw_out_bytes", "Disk bytes/s out",  ["cluster_name", "node_id"])

# Ordered by preference — avg/rate variants first, then fallbacks.
# Discovery picks the first prefix that matches a registry key AND validates against the API.
STAT_PATTERNS = [
    ("node.cpu.user.avg",         NODE_CPU_USER),
    ("node.cpu.user",             NODE_CPU_USER),
    ("node.cpu.sys.avg",          NODE_CPU_SYS),
    ("node.cpu.sys",              NODE_CPU_SYS),
    ("node.cpu.idle.avg",         NODE_CPU_IDLE),
    ("node.cpu.idle",             NODE_CPU_IDLE),
    ("node.disk.xfers.busy.avg",  NODE_DISK_BUSY),
    ("node.disk.busy.avg",        NODE_DISK_BUSY),
    ("node.disk.busy",            NODE_DISK_BUSY),
    ("node.disk.xfers.in.rate",   NODE_DISK_IOPS_IN),
    ("node.disk.iops.in",         NODE_DISK_IOPS_IN),
    ("node.disk.xfers.out.rate",  NODE_DISK_IOPS_OUT),
    ("node.disk.iops.out",        NODE_DISK_IOPS_OUT),
    ("node.disk.bytes.in.rate",   NODE_DISK_BW_IN),
    ("node.disk.xfer.size.in",    NODE_DISK_BW_IN),
    ("node.disk.bytes.out.rate",  NODE_DISK_BW_OUT),
    ("node.disk.xfer.size.out",   NODE_DISK_BW_OUT),
]

# --- App & Client Setup ---
app = FastAPI(title="PowerScale Exporter")
app.mount("/metrics", make_asgi_app())
client = OneFSClient(ISILON_HOST, ISILON_PORT, ISILON_USER, ISILON_PASS)

# Resolved once at startup
_cpu_stat_key: str | None = None
_node_endpoint: tuple[str, str] | None = None
_active_stat_map: dict = {}   # { "actual.key.name": Gauge }
_cpu_core_count: int = 1      # used to normalize raw per-core-sum CPU values

# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _discover_node_endpoint() -> tuple[str, str] | None:
    candidates = [
        ("3", "cluster/nodes"),
        ("1", "cluster/nodes"),
        ("3", "cluster/config/nodes"),
        ("1", "cluster/config/nodes"),
    ]
    for ver, ep in candidates:
        try:
            raw = client._request("GET", ep, version=ver)
            if isinstance(raw, dict):
                print(f"[DISCOVER] v{ver}/{ep} → keys: {list(raw.keys())}")
                for key, val in raw.items():
                    if isinstance(val, list):
                        print(f"    '{key}': {len(val)}")
                        if val:
                            return ver, ep
            elif isinstance(raw, list) and raw:
                print(f"[DISCOVER] v{ver}/{ep} → list[{len(raw)}]")
                return ver, ep
            else:
                print(f"[DISCOVER] v{ver}/{ep} → empty/unexpected: {type(raw)}")
        except Exception as e:
            print(f"[DISCOVER] v{ver}/{ep} → {e}")
    return None


def _discover_cpu_key() -> str | None:
    print("[DISCOVER] Querying statistics key registry for 'cpu' keys...")
    cpu_keys = []
    params = {"limit": 1000}
    while True:
        try:
            data = client._request("GET", "statistics/keys", version="1", params=params)
        except Exception as e:
            print(f"[DISCOVER] statistics/keys failed: {e}")
            break
        keys_list = data.get("keys", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for entry in keys_list:
            name = entry if isinstance(entry, str) else entry.get("key", "")
            if "cpu" in str(name).lower():
                cpu_keys.append(name)
        resume = data.get("resume") if isinstance(data, dict) else None
        if not resume:
            break
        params = {"resume": resume}

    print(f"[DISCOVER] CPU-related keys found ({len(cpu_keys)}): {cpu_keys[:30]}")
    for key in cpu_keys:
        try:
            resp = client._request("GET", "statistics/current", version="1", params={"keys": key})
            if isinstance(resp, dict) and resp.get("stats"):
                print(f"[DISCOVER] ✓ Valid CPU key: '{key}'")
                return key
        except Exception:
            pass
    print("[DISCOVER] No valid CPU stat key found.")
    return None


def _discover_cpu_core_count() -> int:
    """Query node.cpu.count to know how many cores per node so we can normalize."""
    try:
        resp = client._request(
            "GET", "statistics/current", version="1", params={"keys": "node.cpu.count", "devid": "all"}
        )
        stats = resp.get("stats", [])
        if stats:
            count = int(stats[0].get("value") or 1)
            print(f"[DISCOVER] CPU core count per node: {count}")
            return max(count, 1)
    except Exception as e:
        print(f"[DISCOVER] Could not get CPU core count: {e}")
    return 1


def _fetch_all_registry_keys() -> list[str]:
    """Page through statistics/keys and return every key name."""
    all_keys: list[str] = []
    params: dict = {"limit": 1000}
    while True:
        try:
            data = client._request("GET", "statistics/keys", version="1", params=params)
        except Exception as e:
            print(f"[DISCOVER] statistics/keys error: {e}")
            break
        keys_list = data.get("keys", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
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
    """Return True only if the cluster actually returns stats for this key."""
    try:
        resp = client._request(
            "GET", "statistics/current", version="1", params={"keys": key, "devid": "all"}
        )
        return bool(isinstance(resp, dict) and resp.get("stats"))
    except Exception:
        return False


def _discover_stat_map() -> dict:
    """
    For each STAT_PATTERN prefix (in order), find registry keys that start with
    it, validate them, and map the first working one to its Gauge.
    Returns {confirmed_key: Gauge}.
    """
    print("[DISCOVER] Building cpu/disk stat map from key registry...")
    all_keys = _fetch_all_registry_keys()
    cpu_disk_keys = [k for k in all_keys if "cpu" in k.lower() or "disk" in k.lower()]
    print(f"[DISCOVER] Total cpu/disk candidate keys: {len(cpu_disk_keys)}")

    stat_map: dict = {}
    claimed_gauges: set[int] = set()

    for prefix, gauge in STAT_PATTERNS:
        if id(gauge) in claimed_gauges:
            continue  # this gauge already has a confirmed key

        matches = [k for k in cpu_disk_keys if k.startswith(prefix)]
        if not matches:
            continue  # silent — patterns are tried in order, many are fallbacks

        # avg/rate first, then shortest (most aggregate), then alpha
        matches.sort(key=lambda k: (0 if ("avg" in k or "rate" in k) else 1, len(k), k))

        for candidate in matches:
            if _validate_key(candidate):
                print(f"[DISCOVER]   ✓ '{prefix}' → '{candidate}'")
                stat_map[candidate] = gauge
                claimed_gauges.add(id(gauge))
                break
        # no 'else' print — fallback prefixes for same gauge will try next iteration

    # Report anything we couldn't find
    claimed_names = {g.__class__.__name__ for g in stat_map.values()}
    for prefix, gauge in STAT_PATTERNS:
        if id(gauge) not in claimed_gauges:
            gauge_name = [name for name, val in globals().items() if val is gauge]
            label = gauge_name[0] if gauge_name else "unknown"
            # Only warn once per gauge
            if label not in claimed_names:
                print(f"[DISCOVER]   ✗ no valid key found for gauge {label}")
                claimed_names.add(label)

    print(f"[DISCOVER] Final stat map ({len(stat_map)} keys): {list(stat_map.keys())}")
    return stat_map

# ---------------------------------------------------------------------------
# Per-node helpers (unchanged)
# ---------------------------------------------------------------------------

def _node_id(n: dict) -> str:
    return str(n.get("id") or n.get("lnn") or n.get("name") or n.get("devid") or "unknown")


def _node_healthy(n: dict) -> bool:
    sf = {}
    try:
        sf = (n.get("state") or {}).get("smartfail") or {}
    except Exception:
        sf = {}
    in_cluster   = bool(sf.get("in_cluster", True))
    is_down      = bool(sf.get("down", False))
    is_smartfail = bool(sf.get("smartfailed", False))
    if sf:
        return in_cluster and (not is_down) and (not is_smartfail)
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
    print(f"[*] Scraper thread started — polling every {SCRAPE_INTERVAL}s")

    _node_endpoint = _discover_node_endpoint()
    if _node_endpoint:
        print(f"[*] Node endpoint: v{_node_endpoint[0]}/{_node_endpoint[1]}")
    else:
        print("[!] No node endpoint discovered — node metrics will be skipped.")

    _cpu_stat_key = _discover_cpu_key()
    if not _cpu_stat_key:
        print("[!] Legacy NODE_CPU gauge will be skipped.")

    # FIX 1: discover core count so we can normalize 929-style CPU values
    _cpu_core_count = _discover_cpu_core_count()

    _active_stat_map = _discover_stat_map()
    if not _active_stat_map:
        print("[!] No cpu/disk stat keys resolved — check registry output above.")

    while True:
        cluster_name = "unknown_cluster"
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
                    NODE_STATUS.labels(cluster_name=cluster_name, node_id=nid).set(healthy)

            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(
                1 if (total == 0 or ok == total) else 0
            )

            if _active_stat_map:
                # FIX 2: pre-seed all gauges with 0.0 for every known node so
                # they always appear in /metrics even when the cluster is idle
                for nid in node_ids:
                    for g in set(_active_stat_map.values()):
                        g.labels(cluster_name=cluster_name, node_id=nid).set(0.0)

                resp = client._request(
                    "GET", "statistics/current", version="1",
                    params={"keys": ",".join(_active_stat_map.keys()), "devid": "all"}
                )
                for stat in resp.get("stats", []):
                    key   = stat.get("key", "")
                    devid = str(stat.get("devid", "0"))
                    raw_val = stat.get("value")
                    try:
                        val = float(raw_val) if raw_val is not None else 0.0
                    except (TypeError, ValueError):
                        val = 0.0

                    # FIX 3: normalize per-core-sum CPU values → true 0-100%
                    if "cpu" in key and "count" not in key and val > 100:
                        val = val / _cpu_core_count

                    # Legacy gauge (backwards compat)
                    if "cpu" in key and "count" not in key:
                        NODE_CPU.labels(cluster_name=cluster_name, node_id=devid).set(val)

                    gauge = _active_stat_map.get(key)
                    if gauge:
                        gauge.labels(cluster_name=cluster_name, node_id=devid).set(val)

            quotas = client.get_paginated("quota/quotas")
            QUOTA_COUNT.labels(cluster_name=cluster_name).set(len(quotas))

            print(f"[*] Scrape OK — cluster={cluster_name}, nodes={total}, ok={ok}, quotas={len(quotas)}")

        except Exception as e:
            print(f"[!] Scrape failed: {e}")
            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(0)

        time.sleep(SCRAPE_INTERVAL)


bg_thread = threading.Thread(target=collect_metrics, daemon=True)
bg_thread.start()


@app.get("/healthz")
def healthcheck():
    return {
        "status":          "online",
        "cluster_host":    ISILON_HOST,
        "cpu_key":         _cpu_stat_key,
        "cpu_core_count":  _cpu_core_count,
        "node_endpoint":   _node_endpoint,
        "active_stat_map": list(_active_stat_map.keys()),
        "scraper_alive":   bg_thread.is_alive(),
    }


@app.get("/", include_in_schema=False)
def root():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)