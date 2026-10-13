"""Mock Dell PowerScale (OneFS) REST API for demo and development use.

Implements just enough of the OneFS platform API for the exporter's
OneFSClient to authenticate, discover endpoints/stat keys, and scrape
statistics -- without any real storage hardware.

Served over HTTPS because OneFSClient always uses https:// (it sets
verify=False, so the self-signed cert generated at container startup
is accepted).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mock_onefs import data

app = FastAPI(title="mock-onefs", version="0.1.0")


@app.post("/session/1/session")
async def create_session(request: Request):
    body = await request.json()
    # Accept any credentials; this is a demo box.
    _ = body.get("username"), body.get("password")
    resp = JSONResponse(
        {
            "csrf_token": "mock-csrf-token",
            "timeout_absolute": 3600,
            "services": ["platform"],
        }
    )
    resp.set_cookie("isicsrf", "mock-csrf-token")
    return resp


@app.get("/platform")
async def platform_versions():
    return {
        "directory": [{"name": "platform", "versions": ["1", "3"]}],
        "platform": {"versions": ["1", "3"]},
    }


@app.get("/platform/1/cluster/identity")
@app.get("/platform/3/cluster/identity")
async def cluster_identity():
    return {
        "name": data.CLUSTER_NAME,
        "id": "mock-cluster-id",
        "version": data.CLUSTER_VERSION,
    }


@app.get("/platform/3/cluster/nodes")
@app.get("/platform/1/cluster/nodes")
async def cluster_nodes():
    return {"nodes": data.NODES, "total": len(data.NODES)}


@app.get("/platform/1/statistics/keys")
async def statistics_keys(limit: int = 1000):
    keys = data.STAT_KEYS[:limit]
    return {"keys": keys, "total": len(data.STAT_KEYS), "resume": None}


@app.get("/platform/1/statistics/current")
async def statistics_current(keys: str = "", devid: str = "all"):
    """Return one stat entry per node for every requested key."""
    stats = []
    for key in [k.strip() for k in keys.split(",") if k.strip()]:
        for node in data.NODES:
            stats.append(
                {
                    "key": key,
                    "devid": str(node["id"]),
                    "value": data.stat_value(key),
                }
            )
    return {"stats": stats}


@app.get("/platform/3/statistics/summary/drive")
@app.get("/platform/1/statistics/summary/drive")
async def drive_summary():
    return {"drives": data.drives()}


@app.get("/platform/3/quota/quotas")
async def quotas():
    return {"quotas": data.QUOTAS, "total": len(data.QUOTAS)}


@app.get("/platform/3/protocols/nfs/exports")
async def nfs_exports():
    return {"exports": data.NFS_EXPORTS, "total": len(data.NFS_EXPORTS)}


@app.get("/platform/3/protocols/smb/shares")
async def smb_shares():
    return {"shares": data.SMB_SHARES, "total": len(data.SMB_SHARES)}


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "cluster": data.CLUSTER_NAME}
