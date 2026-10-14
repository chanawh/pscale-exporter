"""Pure parsing helpers for the v1.2 collectors.

Each ``parse_*`` function takes a raw OneFS API payload and returns plain
data structures. No network, no globals, no prometheus_client -- so they
are unit-testable in isolation. The scrape loop in main.py calls these
and sets the gauges.

Every parser is defensive: OneFS field names vary across versions, so
each tries several candidate keys and degrades to "no data" instead of
crashing. This mirrors the discovery philosophy used for stat keys.
"""

SEVERITIES = ("CRITICAL", "ERROR", "WARNING", "INFO")


def find_list(payload, *keys):
    """Return the first non-empty list found under any of ``keys``.

    Looks at the top level, then one level deep
    (e.g. ``{"result": {"events": [...]}}``). Bare lists pass through.
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list) and v:
            return v
    for v in payload.values():
        if isinstance(v, dict):
            for k in keys:
                w = v.get(k)
                if isinstance(w, list) and w:
                    return w
    return []


def any_list(payload):
    """True if the payload contains any non-empty list, top-level or one
    level deep. Used by endpoint discovery when the field name is unknown."""
    if isinstance(payload, list):
        return bool(payload)
    if not isinstance(payload, dict):
        return False
    for v in payload.values():
        if isinstance(v, list) and v:
            return True
        if isinstance(v, dict):
            for w in v.values():
                if isinstance(w, list) and w:
                    return True
    return False


def _severity(s):
    s = str(s or "INFO").upper()
    return s if s in SEVERITIES else "INFO"


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parse_events(payload, max_events=50):
    """Parse an event/events payload.

    Returns a list of dicts, newest first, truncated to ``max_events``
    (cardinality guard):
    ``{"event_id", "severity", "node_id", "timestamp", "message"}``.
    """
    out = []
    for e in find_list(payload, "events", "items", "results"):
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or e.get("event_id") or e.get("uuid") or "")
        if not eid:
            continue
        node = e.get("node_lnn", e.get("node", e.get("lnn", e.get("devid", ""))))
        out.append(
            {
                "event_id": eid,
                "severity": _severity(e.get("severity")),
                "node_id": str(node or ""),
                "timestamp": _num(e.get("time", e.get("timestamp", e.get("created")))),
                "message": str(e.get("message", e.get("description", "")))[:200],
            }
        )
    out.sort(key=lambda d: d["timestamp"] or 0, reverse=True)
    return out[:max_events]


def parse_snapshots(payload):
    """Parse a snapshot list -> ``(count: int, bytes_total: int | None)``."""
    snaps = find_list(payload, "snapshots", "items", "results")
    total = 0
    have_size = False
    for s in snaps:
        if not isinstance(s, dict):
            continue
        for k in ("size_bytes", "size", "bytes", "usage_bytes"):
            v = _num(s.get(k))
            if v is not None:
                total += v
                have_size = True
                break
    return len(snaps), (int(total) if have_size else None)


def parse_storagepools(payload):
    """Parse a storagepool list -> ``[{"pool", "total", "used"}]`` (bytes or None)."""
    out = []
    for p in find_list(payload, "storagepools", "pools", "items"):
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or p.get("id") or "unknown")
        src = p.get("usage") if isinstance(p.get("usage"), dict) else p
        out.append(
            {
                "pool": name,
                "total": _num(
                    src.get("bytes_total", src.get("total_bytes", src.get("total")))
                ),
                "used": _num(
                    src.get("bytes_used", src.get("used_bytes", src.get("used")))
                ),
            }
        )
    return out


def parse_sensors(payload):
    """Parse hardware sensors -> ``[{"node_id", "sensor", "kind", "value"}]``.

    ``kind`` is one of ``temp`` (Celsius), ``fan`` (RPM), ``psu``
    (1 = healthy). Entries that cannot be classified are skipped.
    """
    out = []
    for s in find_list(payload, "sensors", "items", "components"):
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or s.get("id") or "unknown")
        node = str(s.get("node_id", s.get("node", s.get("lnn", ""))))
        kind_raw = str(s.get("type", s.get("kind", ""))).lower()
        unit = str(s.get("unit", "")).lower()
        if "temp" in kind_raw or unit in ("c", "celsius", "\u00b0c"):
            kind = "temp"
        elif "fan" in kind_raw or "rpm" in unit:
            kind = "fan"
        elif "psu" in kind_raw or "power" in kind_raw:
            kind = "psu"
        else:
            continue
        v = s.get("value", s.get("reading"))
        if kind == "psu" and not isinstance(v, (int, float)):
            v = 1.0 if str(v).upper() in ("OK", "HEALTHY", "GOOD", "ONLINE") else 0.0
        v = _num(v)
        if v is None:
            continue
        out.append({"node_id": node, "sensor": name, "kind": kind, "value": v})
    return out


def parse_dedupe(payload):
    """Parse a dedupe summary -> ``{"saved_bytes", "ratio"}`` or None."""
    d = payload if isinstance(payload, dict) else {}
    if not any(k in d for k in ("saved_bytes", "bytes_saved", "saved", "ratio")):
        for v in d.values():
            if isinstance(v, dict) and any(
                k in v for k in ("saved_bytes", "bytes_saved", "ratio")
            ):
                d = v
                break
    saved = _num(d.get("saved_bytes", d.get("bytes_saved", d.get("saved"))))
    ratio = _num(d.get("ratio", d.get("dedupe_ratio", d.get("efficiency_ratio"))))
    if saved is None and ratio is None:
        return None
    return {"saved_bytes": saved, "ratio": ratio}


def parse_cloudpools(payload):
    """Parse cloud pools -> ``[{"pool", "used"}]`` (bytes or None)."""
    out = []
    for p in find_list(payload, "pools", "cloudpools", "items"):
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or p.get("id") or "unknown")
        out.append(
            {
                "pool": name,
                "used": _num(p.get("used_bytes", p.get("bytes_used", p.get("used")))),
            }
        )
    return out


def parse_versions(identity, nodes):
    """-> ``(cluster_version: str | None, [(node_id, version)])``."""
    cluster_version = None
    if isinstance(identity, dict):
        for k in ("version", "onefs_version", "cluster_version"):
            v = identity.get(k)
            if v:
                cluster_version = str(v)
                break
    node_versions = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or n.get("lnn") or n.get("name") or "")
        ver = n.get("onefs_version", n.get("version", n.get("firmware_version", "")))
        if nid and ver:
            node_versions.append((nid, str(ver)))
    return cluster_version, node_versions
