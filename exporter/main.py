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

ISILON_HOST     = os.getenv("ISILON_HOST", "10.17.60.56")
ISILON_PORT     = _int_env("ISILON_PORT", 8080)
ISILON_USER     = os.getenv("ISILON_USER", "root")
ISILON_PASS     = os.getenv("ISILON_PASS", "a")
SCRAPE_INTERVAL = _int_env("SCRAPE_INTERVAL", 30)

# --- Prometheus Metrics ---
CLUSTER_HEALTH = Gauge("isilon_cluster_health", "Cluster health (1=OK, 0=Error)", ["cluster_name"])
NODE_STATUS    = Gauge("isilon_node_status", "Node status (1=OK, 0=Error)", ["cluster_name", "node_id"])
NODE_CPU       = Gauge("isilon_node_cpu_value", "CPU-related statistic value per node.", ["cluster_name", "node_id"])
QUOTA_COUNT    = Gauge("isilon_quota_total", "Total number of quotas defined.", ["cluster_name"])

# --- App & Client Setup ---
app = FastAPI(title="PowerScale Exporter")
app.mount("/metrics", make_asgi_app())
client = OneFSClient(ISILON_HOST, ISILON_PORT, ISILON_USER, ISILON_PASS)

# Cached discoveries — resolved once at startup
_cpu_stat_key: str | None = None
_node_endpoint: tuple[str, str] | None = None  # (version, endpoint)

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

        keys_list = []
        if isinstance(data, dict):
            keys_list = data.get("keys", [])
        elif isinstance(data, list):
            keys_list = data

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

# ---------------------------------------------------------------------------
# Per-node helpers
# ---------------------------------------------------------------------------

def _node_id(n: dict) -> str:
    return str(n.get("id") or n.get("lnn") or n.get("name") or n.get("devid") or "unknown")

def _node_healthy(n: dict) -> bool:
    sf = {}
    try:
        sf = (n.get("state") or {}).get("smartfail") or {}
    except Exception:
        sf = {}

    in_cluster = bool(sf.get("in_cluster", True))
    is_down = bool(sf.get("down", False))
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
    global _cpu_stat_key, _node_endpoint
    print(f"[*] Scraper thread started — polling every {SCRAPE_INTERVAL}s")

    _node_endpoint = _discover_node_endpoint()
    if _node_endpoint:
        print(f"[*] Node endpoint: v{_node_endpoint[0]}/{_node_endpoint[1]}")
    else:
        print("[!] No node endpoint discovered — node metrics will be skipped.")

    _cpu_stat_key = _discover_cpu_key()
    if not _cpu_stat_key:
        print("[!] CPU metrics will be skipped.")

    while True:
        cluster_name = "unknown_cluster"
        try:
            ident = client.get_cluster_info()
            cluster_name = ident.get("name", "unknown_cluster")

            total, ok = 0, 0
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
                    healthy = 1 if _node_healthy(n) else 0
                    ok += healthy
                    NODE_STATUS.labels(cluster_name=cluster_name, node_id=nid).set(healthy)

            CLUSTER_HEALTH.labels(cluster_name=cluster_name).set(
                1 if (total == 0 or ok == total) else 0
            )

            if _cpu_stat_key:
                resp = client._request("GET", "statistics/current", version="1", params={"keys": _cpu_stat_key})
                for stat in resp.get("stats", []):
                    devid = str(stat.get("devid", "0"))
                    try:
                        val = float(stat.get("value", 0.0))
                    except (TypeError, ValueError):
                        val = 0.0
                    NODE_CPU.labels(cluster_name=cluster_name, node_id=devid).set(val)

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
        "node_endpoint":   _node_endpoint,
        "scraper_alive":   bg_thread.is_alive(),
    }

@app.get("/", include_in_schema=False)
def root():
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)