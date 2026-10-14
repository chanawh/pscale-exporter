"""Unit tests for v2 multi-cluster support (exporter/main.py).

Importing ``main`` starts the background scraper thread, so the OneFS
client's network I/O is stubbed out before import. The thread then spins
harmlessly against empty responses.
"""

import json
import os
from unittest.mock import patch

import pytest

os.environ["ISILON_PASS"] = "test-secret"

with patch("scraper.OneFSClient._authenticate", lambda self: None), patch(
    "scraper.OneFSClient._request", lambda self, *a, **k: {}
):
    import main


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Each test starts without target env vars."""
    monkeypatch.delenv("ISILON_TARGETS", raising=False)
    monkeypatch.delenv("ISILON_TARGETS_FILE", raising=False)
    monkeypatch.setenv("ISILON_PASS", "test-secret")


# ---------------------------------------------------------------------------
# load_targets
# ---------------------------------------------------------------------------


def test_load_targets_single_cluster_fallback():
    targets = main.load_targets()
    assert len(targets) == 1
    assert targets[0]["host"] == os.getenv("ISILON_HOST", "127.0.0.1")
    assert targets[0]["password"] == "test-secret"


def test_load_targets_fails_without_password(monkeypatch):
    monkeypatch.delenv("ISILON_PASS")
    with pytest.raises(RuntimeError, match="ISILON_PASS"):
        main.load_targets()


def test_load_targets_json_list(monkeypatch):
    monkeypatch.setenv(
        "ISILON_TARGETS",
        json.dumps(
            [
                {"name": "prod", "host": "10.0.0.1", "password": "s3cret"},
                {"host": "10.0.0.2", "port": 8443, "user": "admin", "password": "x"},
            ]
        ),
    )
    targets = main.load_targets()
    assert len(targets) == 2
    assert targets[0] == {
        "name": "prod",
        "host": "10.0.0.1",
        "port": 8080,
        "user": "root",
        "password": "s3cret",
    }
    # name defaults to host
    assert targets[1]["name"] == "10.0.0.2"
    assert targets[1]["port"] == 8443
    assert targets[1]["user"] == "admin"


def test_load_targets_from_file_json(tmp_path, monkeypatch):
    f = tmp_path / "targets.json"
    f.write_text(json.dumps([{"host": "10.0.0.5", "password": "pw"}]))
    monkeypatch.setenv("ISILON_TARGETS_FILE", str(f))
    targets = main.load_targets()
    assert len(targets) == 1 and targets[0]["host"] == "10.0.0.5"


def test_load_targets_from_file_yaml(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    f = tmp_path / "targets.yaml"
    f.write_text("- host: 10.0.0.6\n  password: pw\n")
    monkeypatch.setenv("ISILON_TARGETS_FILE", str(f))
    targets = main.load_targets()
    assert len(targets) == 1 and targets[0]["host"] == "10.0.0.6"


def test_load_targets_rejects_missing_password(monkeypatch):
    monkeypatch.setenv("ISILON_TARGETS", json.dumps([{"host": "10.0.0.1"}]))
    with pytest.raises(RuntimeError, match="password"):
        main.load_targets()


def test_load_targets_rejects_empty_list(monkeypatch):
    monkeypatch.setenv("ISILON_TARGETS", "[]")
    with pytest.raises(RuntimeError, match="No targets"):
        main.load_targets()


# ---------------------------------------------------------------------------
# ClusterScraper per-target isolation
# ---------------------------------------------------------------------------


def _scraper(name, host):
    with patch.object(main, "OneFSClient") as cls:
        s = main.ClusterScraper(
            {"name": name, "host": host, "port": 8080, "user": "root", "password": "p"}
        )
        s._mock_cls = cls
        return s


def test_scrapers_have_isolated_state():
    s1 = _scraper("a", "h1")
    s2 = _scraper("b", "h2")
    assert s1.client is not s2.client
    s1.known_events.add(("ev-1",))
    s1.known_nodes_last_seen["1"] = 123.0
    assert ("ev-1",) not in s2.known_events
    assert "1" not in s2.known_nodes_last_seen
    assert s1.name == "a" and s2.name == "b"


def test_scraper_registers_target_info():
    _scraper("prod", "10.0.0.1")
    # TARGET_INFO gauge should have a series for this target
    found = False
    for metric in main.TARGET_INFO.collect():
        for sample in metric.samples:
            if sample.labels.get("target") == "prod":
                found = True
    assert found
    # cleanup so tests don't leak series
    main.TARGET_INFO.remove("prod", "10.0.0.1", "8080")


def test_scraper_client_uses_target_credentials():
    s = _scraper("prod", "10.0.0.9")
    cls = s._mock_cls
    args, _kwargs = cls.call_args
    assert args == ("10.0.0.9", 8080, "root", "p")
