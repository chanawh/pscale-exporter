# Mock OneFS API

A fake Dell PowerScale (OneFS) REST API for demos and development. It
implements just enough of the platform API for the exporter's `OneFSClient`
to authenticate, discover endpoints/stat keys, and scrape statistics --
with no real storage hardware.

## What's mocked

| Endpoint | Purpose |
|---|---|
| `POST /session/1/session` | Authentication (accepts any credentials) |
| `GET /platform` | API version discovery |
| `GET /platform/{1,3}/cluster/identity` | Cluster name/version |
| `GET /platform/{1,3}/cluster/nodes` | 3-node inventory |
| `GET /platform/1/statistics/keys` | Stat key registry |
| `GET /platform/1/statistics/current` | Per-node stat values (jittered so graphs move) |
| `GET /platform/{1,3}/statistics/summary/drive` | Drive health inventory (12 drives) |

Served over HTTPS with a self-signed cert generated at container startup
(`OneFSClient` uses `https://` with `verify=False`, so this is accepted).

## Run the demo

```bash
docker compose -f docker-compose.demo.yml up --build
```

- Exporter metrics: http://localhost:8000/metrics/
- Exporter health:  http://localhost:8000/healthz
- Mock API health:  https://localhost:8443/healthz (self-signed cert)

Point the exporter at the mock by setting `ISILON_HOST=mock-onefs`
(`ISILON_PORT=8080`); any username/password works. The stat values include
a small random jitter per scrape so Grafana graphs render live data
instead of flat lines.
