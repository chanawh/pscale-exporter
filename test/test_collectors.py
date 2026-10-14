"""Unit tests for exporter/collectors.py (v1.2 pure parsers).

The parsers take raw OneFS API payloads and return plain data -- no
network, no globals -- so every test below feeds canned responses.
"""

import pytest

from collectors import (
    any_list,
    find_list,
    parse_cloudpools,
    parse_dedupe,
    parse_events,
    parse_sensors,
    parse_snapshots,
    parse_storagepools,
    parse_versions,
)


# ---------------------------------------------------------------------------
# find_list
# ---------------------------------------------------------------------------


def test_find_list_top_level():
    assert find_list({"events": [{"id": 1}]}, "events") == [{"id": 1}]


def test_find_list_nested_one_level():
    assert find_list({"result": {"events": [{"id": 1}]}}, "events") == [{"id": 1}]


def test_find_list_bare_list():
    assert find_list([1, 2], "events") == [1, 2]


def test_find_list_missing():
    assert find_list({"other": 1}, "events") == []
    assert find_list({}, "events") == []
    assert find_list(None, "events") == []


def test_any_list():
    assert any_list({"events": [{"id": 1}]})
    assert any_list({"result": {"items": [1]}})
    assert any_list([1])
    assert not any_list({"events": []})
    assert not any_list({})
    assert not any_list(None)


# ---------------------------------------------------------------------------
# parse_events
# ---------------------------------------------------------------------------


def test_parse_events_basic():
    payload = {
        "events": [
            {
                "id": "ev-1",
                "severity": "critical",
                "time": 1700000000,
                "message": "disk failed",
                "node_lnn": 2,
            },
            {"id": "ev-2", "severity": "info", "time": 1700000100, "message": "ok"},
        ]
    }
    out = parse_events(payload)
    assert len(out) == 2
    # newest first
    assert out[0]["event_id"] == "ev-2"
    assert out[1]["severity"] == "CRITICAL"
    assert out[1]["node_id"] == "2"
    assert out[1]["timestamp"] == 1700000000.0


def test_parse_events_unknown_severity_defaults_to_info():
    out = parse_events({"events": [{"id": "e", "severity": "bogus"}]})
    assert out[0]["severity"] == "INFO"


def test_parse_events_skips_idless_and_truncates():
    payload = {"events": [{"no": "id"}] + [{"id": f"e{i}"} for i in range(10)]}
    out = parse_events(payload, max_events=5)
    assert len(out) == 5
    assert all(e["event_id"].startswith("e") for e in out)


def test_parse_events_message_truncated():
    out = parse_events({"events": [{"id": "e", "message": "x" * 500}]})
    assert len(out[0]["message"]) == 200


# ---------------------------------------------------------------------------
# parse_snapshots
# ---------------------------------------------------------------------------


def test_parse_snapshots_count_and_bytes():
    payload = {
        "snapshots": [
            {"name": "s1", "size_bytes": 100},
            {"name": "s2", "size_bytes": 200},
        ]
    }
    assert parse_snapshots(payload) == (2, 300)


def test_parse_snapshots_no_size_field():
    assert parse_snapshots({"snapshots": [{"name": "s1"}]}) == (1, None)
    assert parse_snapshots({}) == (0, None)


# ---------------------------------------------------------------------------
# parse_storagepools
# ---------------------------------------------------------------------------


def test_parse_storagepools():
    payload = {
        "storagepools": [
            {"name": "hdd", "total_bytes": 1000, "used_bytes": 400},
            {"name": "ssd", "usage": {"bytes_total": 2000, "bytes_used": 100}},
        ]
    }
    out = parse_storagepools(payload)
    assert out[0] == {"pool": "hdd", "total": 1000.0, "used": 400.0}
    assert out[1]["total"] == 2000.0  # nested usage dict


def test_parse_storagepools_missing_values_are_none():
    out = parse_storagepools({"storagepools": [{"name": "x"}]})
    assert out[0]["total"] is None and out[0]["used"] is None


# ---------------------------------------------------------------------------
# parse_sensors
# ---------------------------------------------------------------------------


def test_parse_sensors_kinds():
    payload = {
        "sensors": [
            {"node_id": 1, "name": "temp0", "type": "temp", "value": 42.5},
            {"node_id": 1, "name": "fan1", "type": "fan", "value": 4500, "unit": "rpm"},
            {"node_id": 2, "name": "psu0", "type": "psu", "value": "OK"},
            {"node_id": 2, "name": "psu1", "type": "psu", "value": "FAILED"},
            {"node_id": 3, "name": "???", "type": "mystery", "value": 1},
        ]
    }
    out = parse_sensors(payload)
    by_name = {s["sensor"]: s for s in out}
    assert by_name["temp0"]["kind"] == "temp"
    assert by_name["fan1"]["kind"] == "fan"
    assert by_name["psu0"]["value"] == 1.0
    assert by_name["psu1"]["value"] == 0.0
    assert "???" not in by_name  # unclassifiable skipped


def test_parse_sensors_unit_inference():
    out = parse_sensors(
        {"sensors": [{"node_id": 1, "name": "t", "value": 40, "unit": "C"}]}
    )
    assert out[0]["kind"] == "temp"


# ---------------------------------------------------------------------------
# parse_dedupe / parse_cloudpools
# ---------------------------------------------------------------------------


def test_parse_dedupe():
    assert parse_dedupe({"saved_bytes": 10**12, "ratio": 1.8}) == {
        "saved_bytes": 1e12,
        "ratio": 1.8,
    }
    assert parse_dedupe({"dedupe": {"saved_bytes": 5}})["saved_bytes"] == 5.0
    assert parse_dedupe({}) is None
    assert parse_dedupe({"unrelated": 1}) is None


def test_parse_cloudpools():
    out = parse_cloudpools({"pools": [{"name": "aws", "used_bytes": 123}]})
    assert out == [{"pool": "aws", "used": 123.0}]
    assert parse_cloudpools({}) == []


# ---------------------------------------------------------------------------
# parse_versions
# ---------------------------------------------------------------------------


def test_parse_versions():
    cv, nv = parse_versions(
        {"version": "9.5.0"},
        [{"id": 1, "onefs_version": "9.5.0"}, {"id": 2, "onefs_version": "9.4.0"}],
    )
    assert cv == "9.5.0"
    assert nv == [("1", "9.5.0"), ("2", "9.4.0")]


def test_parse_versions_missing():
    assert parse_versions({}, []) == (None, [])
    assert parse_versions({"name": "x"}, [{"id": 1}]) == (None, [])
