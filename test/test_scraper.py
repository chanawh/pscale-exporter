"""Unit tests for exporter/scraper.py.

The OneFSClient constructor performs a network login, so the fixture
neutralises ``_authenticate`` and every test below either mocks
``_request``/``session.request`` or exercises pure logic. No test here
touches the network.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from scraper import CircuitBreaker, OneFSClient


@pytest.fixture
def client():
    """A OneFSClient whose constructor login is stubbed out."""
    with patch.object(OneFSClient, "_authenticate", lambda self: None):
        return OneFSClient("fake-host", 8080, "root", "secret")


def _resp(ok=True, status=200, payload=None, text=""):
    r = MagicMock()
    r.ok = ok
    r.status_code = status
    r.text = text
    r.headers = {"Content-Type": "application/json"}
    r.json.return_value = payload if payload is not None else {}
    return r


# ---------------------------------------------------------------------------
# get_paginated
# ---------------------------------------------------------------------------


def test_get_paginated_follows_resume_token(client):
    client._request = MagicMock(
        side_effect=[
            {"quotas": [{"id": 1}], "resume": "tok1"},
            {"quotas": [{"id": 2}]},
        ]
    )
    assert client.get_paginated("quota/quotas") == [{"id": 1}, {"id": 2}]
    assert client._request.call_count == 2
    # second call carries the resume token
    _, kwargs = client._request.call_args
    assert kwargs["params"]["resume"] == "tok1"


def test_get_paginated_accepts_bare_list(client):
    client._request = MagicMock(return_value=[{"id": 1}, {"id": 2}])
    assert client.get_paginated("protocols/nfs/exports") == [{"id": 1}, {"id": 2}]


def test_get_paginated_stops_on_empty_response(client):
    client._request = MagicMock(return_value={})
    assert client.get_paginated("quota/quotas") == []


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, timeout=60)
    failing = MagicMock(side_effect=Exception("boom"))
    with pytest.raises(Exception, match="boom"):
        cb.call(failing)
    with pytest.raises(Exception, match="boom"):
        cb.call(failing)
    assert cb.state == "OPEN"
    with pytest.raises(Exception, match="Circuit breaker is OPEN"):
        cb.call(failing)


def test_circuit_breaker_half_open_recovery():
    cb = CircuitBreaker(failure_threshold=1, timeout=60)
    with pytest.raises(Exception, match="x"):
        cb.call(MagicMock(side_effect=Exception("x")))
    assert cb.state == "OPEN"
    cb.last_failure_time = time.time() - 61  # force the timeout to expire
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0


def test_request_returns_empty_when_circuit_open(client):
    client.circuit_breaker.state = "OPEN"
    client.circuit_breaker.last_failure_time = time.time()
    client.session.request = MagicMock(
        side_effect=AssertionError("must not hit the network")
    )
    assert client._request("GET", "anything") == {}
    client.session.request.assert_not_called()


# ---------------------------------------------------------------------------
# _request auth refresh
# ---------------------------------------------------------------------------


def test_request_reauthenticates_on_401(client):
    client._authenticate = MagicMock()
    client.session.request = MagicMock(
        side_effect=[
            _resp(ok=False, status=401, text="unauthorized"),
            _resp(ok=True, payload={"key": "value"}, text='{"key": "value"}'),
        ]
    )
    assert client._request("GET", "cluster/identity", version="1") == {"key": "value"}
    assert client.session.request.call_count == 2
    client._authenticate.assert_called_once()
