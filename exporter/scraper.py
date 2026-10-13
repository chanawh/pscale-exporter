import requests
import urllib3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import os
import time
import logging
from typing import Optional, Dict, Any, List

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "3"  # Safe baseline for OneFS 8+/9.x — bump if endpoints 404


class CircuitBreaker:
    """Simple circuit breaker implementation"""

    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            raise e


class OneFSClient:
    def __init__(
        self,
        host,
        port,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_version=DEFAULT_API_VERSION,
    ):
        self.host = host
        self.base_url = f"https://{host}:{port}"
        self.api_prefix = "/platform"
        self.username = username or os.getenv("ISILON_USER", "root")
        self.password = password or os.getenv("ISILON_PASS", "")
        self.api_version = api_version
        self.session = self._build_session()
        self.circuit_breaker = CircuitBreaker()
        self.last_auth_time = 0
        self.auth_ttl = 3600  # 1 hour auth token TTL
        self._authenticate()

    def _build_session(self):
        session = requests.Session()
        retries = Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.verify = False
        return session

    def _authenticate(self):
        """Authenticate with OneFS API and handle token refresh"""
        # Check if current token is still valid
        if time.time() - self.last_auth_time < self.auth_ttl:
            logger.debug("Using existing authentication token")
            return

        logger.info(f"Authenticating to {self.host} as '{self.username}'")
        url = f"{self.base_url}/session/1/session"
        payload = {
            "username": self.username,
            "password": self.password,
            "services": ["platform"],
        }

        self.session.headers.clear()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Referer": f"{self.base_url}/",
            }
        )

        try:
            response = self.session.post(url, json=payload, timeout=30)
            if not response.ok:
                logger.error(
                    f"Auth failed: {response.status_code} - {response.text[:300]}"
                )
                raise Exception(f"Authentication failed: {response.status_code}")

            body = response.json()
            csrf_token = (
                body.get("csrf_token")
                or self.session.cookies.get("is_csrf_token")
                or self.session.cookies.get("isicsrf")
            )

            if csrf_token:
                self.session.headers.update({"X-CSRF-Token": csrf_token})
                logger.debug(f"CSRF token captured: {csrf_token[:8]}...")
            else:
                logger.warning("No CSRF token found")

            self.session.headers.update({"Referer": f"{self.base_url}/"})
            self.last_auth_time = time.time()
            logger.info("Authentication successful")

        except requests.exceptions.Timeout:
            logger.error("Authentication timeout")
            raise
        except requests.exceptions.ConnectionError:
            logger.error("Connection error during authentication")
            raise

    def _request(self, method, endpoint, version=None, params=None, json=None):
        """
        Enhanced request method with circuit breaker and improved error handling
        - Circuit breaker prevents cascading failures
        - Automatic token refresh on 401
        - Comprehensive error logging
        - Safe JSON parsing with fallback
        """
        ver = version or self.api_version
        url = f"{self.base_url}{self.api_prefix}/{ver}/{endpoint.lstrip('/')}"

        def _do_request():
            """Inner request function for circuit breaker"""
            try:
                response = self.session.request(
                    method, url, params=params, json=json, timeout=30
                )

                # Handle authentication refresh
                if response.status_code == 401:
                    logger.warning(f"401 on {url} - re-authenticating...")
                    self.last_auth_time = 0  # Force re-auth
                    self._authenticate()
                    response = self.session.request(
                        method, url, params=params, json=json, timeout=30
                    )

                # Handle HTTP errors
                if not response.ok:
                    error_msg = f"{response.status_code} for {url}"
                    if response.text:
                        error_msg += f" - {response.text[:400]}"
                    logger.error(error_msg)
                    response.raise_for_status()

                return response

            except requests.exceptions.Timeout:
                logger.error(f"Timeout on {url}")
                raise
            except requests.exceptions.ConnectionError:
                logger.error(f"Connection error on {url}")
                raise

        # Execute request through circuit breaker
        try:
            resp = self.circuit_breaker.call(_do_request)
        except Exception as e:
            if "Circuit breaker is OPEN" in str(e):
                logger.error(f"Circuit breaker OPEN - skipping request to {url}")
                return {}
            raise

        # Safe JSON parsing
        ctype = resp.headers.get("Content-Type", "")
        text = resp.text or ""

        if "application/json" in ctype and text.strip():
            try:
                return resp.json()
            except ValueError as e:
                logger.error(f"JSON parse error on {url}: {e}")
                logger.debug(f"Response text: {text[:200]}")
                return {}

        # Return empty dict for non-JSON responses
        return {}

    def get_supported_versions(self):
        """Call GET /platform to see which API versions the cluster exposes."""
        url = f"{self.base_url}{self.api_prefix}"
        response = self.session.get(url)
        if response.ok:
            ctype = response.headers.get("Content-Type", "")
            body = response.text or ""
            if "application/json" in ctype and body.strip():
                return response.json()
            print(
                f"[!] /platform returned no JSON (status {response.status_code}, Content-Type: {ctype}, len={len(body)})"
            )
            return None
        print(f"[!] Could not fetch API versions: {response.status_code}")
        return None

    def get_cluster_info(self):
        return self._request("GET", "cluster/identity", version="1")

    def get_paginated(self, endpoint, version=None):
        results = []
        params = {"limit": 100}
        while True:
            data = self._request("GET", endpoint, version=version, params=params)
            if isinstance(data, list):
                chunk, resume_token = data, None
            else:
                keys = [
                    k
                    for k, v in data.items()
                    if k not in ("resume", "total") and isinstance(v, list)
                ]
                if not keys:
                    break
                chunk, resume_token = data.get(keys[0], []), data.get("resume")
            results.extend(chunk)
            if not resume_token:
                break
            params["resume"] = resume_token
        return results


if __name__ == "__main__":
    # For local one-off testing with an already-running SSH tunnel:
    # ssh -L 8080:10.17.60.56:8080 -p 50019 root@10.241.80.184
    client = OneFSClient("localhost", 8080, "root", "a")
    print("\n--- Supported API Versions ---")
    versions = client.get_supported_versions()
    if versions:
        print(versions)
    print("\n--- Identity ---")
    ident = client.get_cluster_info()
    print(f"Cluster Name: {ident.get('name', 'Unknown')}")
    print("\n--- NFS Exports ---")
    exports = client.get_paginated("protocols/nfs/exports")
    print(f"Found {len(exports)} exports.")
    for ex in exports[:5]:
        print(f"  ID: {ex.get('id')} | Paths: {', '.join(ex.get('paths', []))}")
    print("\n--- Quotas ---")
    quotas = client.get_paginated("quota/quotas")
    print(f"Total Quotas: {len(quotas)}")
