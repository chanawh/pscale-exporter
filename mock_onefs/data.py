"""Canned cluster model for the mock OneFS API.

Values are realistic magnitudes with a small random jitter applied per
request so demo graphs move instead of rendering flat lines.
"""

import random

CLUSTER_NAME = "mock-onefs"
CLUSTER_VERSION = "9.5.0"

NODES = [
    {"id": 1, "lnn": 1, "name": "mock-node-1", "status": "OK"},
    {"id": 2, "lnn": 2, "name": "mock-node-2", "status": "OK"},
    {"id": 3, "lnn": 3, "name": "mock-node-3", "status": "OK"},
]

DRIVES_PER_NODE = 4

# key -> (base value, jitter fraction). Keys intentionally cover the
# STAT_PATTERNS prefixes the exporter discovers (cpu/disk/net/mem),
# plus capacity and replication-lag keys.
STAT_BASES = {
    # --- CPU ---
    "node.cpu.user.avg": (22.5, 0.30),
    "node.cpu.sys.avg": (8.0, 0.30),
    "node.cpu.idle.avg": (69.5, 0.10),
    "node.cpu.count": (4, 0.0),
    "node.cpu.idle.0": (70.0, 0.10),
    "node.cpu.idle.1": (68.0, 0.10),
    "node.cpu.idle.2": (71.0, 0.10),
    "node.cpu.idle.3": (69.0, 0.10),
    # --- Disk ---
    "node.disk.busy.avg": (15.0, 0.40),
    "node.disk.xfers.in.rate": (1200.0, 0.30),
    "node.disk.xfers.out.rate": (800.0, 0.30),
    "node.disk.bytes.in.rate": (25_000_000.0, 0.30),
    "node.disk.bytes.out.rate": (18_000_000.0, 0.30),
    # --- Network ---
    "node.net.bytes.in.rate": (40_000_000.0, 0.30),
    "node.net.bytes.out.rate": (35_000_000.0, 0.30),
    # --- Memory ---
    "node.mem.used.pct": (62.0, 0.05),
    # --- Capacity (bytes) ---
    "ifs.bytes.total": (100 * 1024**4, 0.0),
    "ifs.bytes.used": (62 * 1024**4, 0.01),
    # --- Replication ---
    "siq.lag": (4.0, 0.50),
}

STAT_KEYS = sorted(STAT_BASES.keys())


QUOTAS = [
    {"id": "quota-1", "path": "/ifs/data", "type": "directory"},
    {"id": "quota-2", "path": "/ifs/home", "type": "directory"},
]

NFS_EXPORTS = [
    {"id": 1, "paths": ["/ifs/data"]},
    {"id": 2, "paths": ["/ifs/shared"]},
]

SMB_SHARES = [
    {"id": "share-data", "name": "data", "path": "/ifs/data"},
    {"id": "share-home", "name": "home", "path": "/ifs/home"},
]


def stat_value(key: str) -> float:
    """Return a jittered value for a stat key (unknown keys get a default)."""
    base, jitter = STAT_BASES.get(key, (1.0, 0.0))
    if jitter:
        return base * (1.0 + random.uniform(-jitter, jitter))
    return float(base)


def drives() -> list:
    """Pretend drive inventory: DRIVES_PER_NODE drives per node."""
    out = []
    for node in NODES:
        for bay in range(1, DRIVES_PER_NODE + 1):
            out.append(
                {
                    "drive_id": f"bay-{node['id']}-{bay}",
                    "node": node["id"],
                    "bay": bay,
                    "type": "SSD" if bay % 2 else "HDD",
                    "status": "HEALTHY",
                    "health": "OK",
                    "device": f"/dev/da{bay - 1}",
                    "busy": round(random.uniform(2.0, 25.0), 1),
                    "access_latency": round(random.uniform(0.4, 3.2), 2),
                    "iosched_queue": round(random.uniform(0.0, 2.0), 2),
                }
            )
    return out
