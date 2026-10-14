"""Canned cluster model for the mock OneFS API.

Values are realistic magnitudes with a small random jitter applied per
request so demo graphs move instead of rendering flat lines.
"""

import random
import time

CLUSTER_NAME = "mock-onefs"
CLUSTER_VERSION = "9.5.0"

# Failure-injection state, mutated via POST /platform/1/faults.
# None = healthy baseline; "drive-failure" | "node-down" otherwise.
FAULTS = {"scenario": None}

NODES = [
    {
        "id": 1,
        "lnn": 1,
        "name": "mock-node-1",
        "status": "OK",
        "onefs_version": "9.5.0",
    },
    {
        "id": 2,
        "lnn": 2,
        "name": "mock-node-2",
        "status": "OK",
        "onefs_version": "9.5.0",
    },
    {
        "id": 3,
        "lnn": 3,
        "name": "mock-node-3",
        "status": "OK",
        "onefs_version": "9.5.0",
    },
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
    fault = FAULTS.get("scenario") == "drive-failure"
    out = []
    for node in NODES:
        for bay in range(1, DRIVES_PER_NODE + 1):
            failed = fault and node["id"] == 1 and bay == 1
            out.append(
                {
                    # Real OneFS uses "node:bay" drive ids; the exporter
                    # parses this format for its metric labels.
                    "drive_id": f"{node['id']}:{bay}",
                    "node": node["id"],
                    "bay": bay,
                    "type": "UNKNOWN" if failed else ("SSD" if bay % 2 else "HDD"),
                    "status": "FAILED" if failed else "HEALTHY",
                    "health": "FAILED" if failed else "OK",
                    "device": f"/dev/da{bay - 1}",
                    "busy": 100.0 if failed else round(random.uniform(2.0, 25.0), 1),
                    "access_latency": (
                        120.0 if failed else round(random.uniform(0.4, 3.2), 2)
                    ),
                    "iosched_queue": (
                        round(random.uniform(8.0, 20.0), 2)
                        if failed
                        else round(random.uniform(0.0, 2.0), 2)
                    ),
                }
            )
    return out


# ---------------------------------------------------------------------------
# v1.2 model: events, snapshots, storage pools, sensors, dedupe, cloud pools
# ---------------------------------------------------------------------------


def events() -> list:
    """Canned OneFS event stream: 5 baseline events across severities, plus
    a CRITICAL drive-failure event while the fault scenario is active."""
    now = int(time.time())
    out = [
        {
            "id": "ev-001",
            "severity": "WARNING",
            "time": now - 3600,
            "message": "Drive 2:3 SMART trip detected, monitoring for pre-failure",
            "node_lnn": 2,
        },
        {
            "id": "ev-002",
            "severity": "INFO",
            "time": now - 7200,
            "message": "Diskpool restripe completed on storagepool hdd",
            "node_lnn": 0,
        },
        {
            "id": "ev-003",
            "severity": "ERROR",
            "time": now - 1800,
            "message": "Network interface mlx5_0 flapped on node 1",
            "node_lnn": 1,
        },
        {
            "id": "ev-004",
            "severity": "INFO",
            "time": now - 86400,
            "message": "Snapshot auto-delete completed: snap-2026-09-01",
            "node_lnn": 0,
        },
        {
            "id": "ev-005",
            "severity": "WARNING",
            "time": now - 43200,
            "message": "OneFS license expires in 30 days",
            "node_lnn": 0,
        },
    ]
    if FAULTS.get("scenario") == "drive-failure":
        out.append(
            {
                "id": "ev-fault-001",
                "severity": "CRITICAL",
                "time": now,
                "message": "Drive 1:1 failed",
                "node_lnn": 1,
            }
        )
    return out


def snapshots() -> list:
    """3 snapshots with sizes."""
    base = [
        ("snap-daily-2026-10-13", "/ifs/data", 45 * 1024**3),
        ("snap-weekly-2026-10-11", "/ifs/home", 120 * 1024**3),
        ("snap-monthly-2026-10-01", "/ifs/shared", 300 * 1024**3),
    ]
    return [
        {
            "name": name,
            "path": path,
            "size_bytes": int(size * random.uniform(0.98, 1.02)),
        }
        for name, path, size in base
    ]


def storagepools() -> list:
    """2 storage pools with capacity."""
    return [
        {
            "name": "hdd",
            "total_bytes": 80 * 1024**4,
            "used_bytes": int(55 * 1024**4 * random.uniform(0.99, 1.01)),
        },
        {
            "name": "ssd",
            "total_bytes": 20 * 1024**4,
            "used_bytes": int(7 * 1024**4 * random.uniform(0.99, 1.01)),
        },
    ]


def sensors() -> list:
    """Per node: 1 temp sensor (C), 1 fan (RPM), 1 PSU (1.0 = healthy)."""
    out = []
    for node in NODES:
        nid = node["id"]
        out.append(
            {
                "node_id": nid,
                "name": "temp-inlet",
                "type": "temp",
                "value": round(random.uniform(35.0, 45.0), 1),
                "unit": "C",
            }
        )
        out.append(
            {
                "node_id": nid,
                "name": "fan-1",
                "type": "fan",
                "value": round(random.uniform(4000.0, 6000.0), 0),
                "unit": "rpm",
            }
        )
        out.append(
            {
                "node_id": nid,
                "name": "psu-1",
                "type": "psu",
                "value": 1.0,
                "unit": "ok",
            }
        )
    return out


def dedupe() -> dict:
    """SmartDedupe savings summary."""
    return {
        "saved_bytes": int(8 * 1024**4 * random.uniform(0.99, 1.01)),
        "ratio": round(random.uniform(1.75, 1.85), 2),
    }


def cloudpools() -> list:
    """CloudPools tiering state."""
    return [
        {
            "name": "cloud-archive",
            "used_bytes": int(12 * 1024**4 * random.uniform(0.99, 1.01)),
        }
    ]
