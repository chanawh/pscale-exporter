import requests
import urllib3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_API_VERSION = "3"  # Safe baseline for OneFS 8+/9.x — bump if endpoints 404

class OneFSClient:
    def __init__(self, host, port, username, password,
                 api_version=DEFAULT_API_VERSION):
        self.host = host
        # FIX: remove URLDefense-mangled value
        self.base_url = f"https://{host}:{port}"
        self.api_prefix = "/platform"
        self.username = username
        self.password = password
        self.api_version = api_version
        self.session = self._build_session()
        self._authenticate()

    def _build_session(self):
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1,
                        status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))
        session.verify = False
        return session

    def _authenticate(self):
        url = f"{self.base_url}/session/1/session"
        payload = {
            "username": self.username,
            "password": self.password,
            "services": ["platform"]
        }

        self.session.headers.clear()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": f"{self.base_url}/"
        })

        response = self.session.post(url, json=payload)

        if not response.ok:
            # FIX: remove accidental newline inside f-string
            print(f"[!] Auth failed\n{response.status_code}:\n{response.text[:300]}")
        response.raise_for_status()

        body = response.json()
        csrf_token = (
            body.get("csrf_token")
            or self.session.cookies.get("is_csrf_token")
            or self.session.cookies.get("isicsrf")
        )

        if csrf_token:
            self.session.headers.update({"X-CSRF-Token": csrf_token})
            print(f"[*] CSRF token captured: {csrf_token[:8]}...")
        else:
            print("[!] Warning: no CSRF token found.")
            print(f"    Response body keys: {list(body.keys())}")
            print(f"    Cookies: {dict(self.session.cookies)}")

        self.session.headers.update({"Referer": f"{self.base_url}/"})
        print(f"[*] Authenticated to {self.host} as '{self.username}'")
        print(f"[*] Session cookies: {dict(self.session.cookies)}")

    def _request(self, method, endpoint, version=None, params=None, json=None):
        ver = version or self.api_version
        url = f"{self.base_url}{self.api_prefix}/{ver}/{endpoint.lstrip('/')}"
        response = self.session.request(method, url, params=params, json=json)

        if response.status_code == 401:
            print(f"[!] 401 on {url} — re-authenticating...")
            self._authenticate()
            response = self.session.request(method, url, params=params, json=json)

        if not response.ok:
            print(f"[!] {response.status_code} for {url}")
            print(f"    Response: {response.text[:400]}")
        response.raise_for_status()
        return response.json()

    def get_supported_versions(self):
        """Call GET /platform to see which API versions the cluster exposes."""
        url = f"{self.base_url}{self.api_prefix}"
        response = self.session.get(url)
        if response.ok:
            ctype = response.headers.get("Content-Type", "")
            body = response.text or ""
            if "application/json" in ctype and body.strip():
                return response.json()
            # FIX: remove accidental newline inside f-string
            print(f"[!] /platform returned no JSON (status {response.status_code}, Content-Type: {ctype}, len={len(body)})")
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
                keys = [k for k, v in data.items() if k not in ("resume", "total") and isinstance(v, list)]
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