# powerscale-exporter Helm chart

Deploys the PowerScale (OneFS) Prometheus exporter, hardened the same way as
`k8s/manifests/` (non-root uid 10001, read-only root filesystem, NetworkPolicy).

## Demo mode (no hardware)

```bash
helm install pscale ./helm/powerscale-exporter --set mock.enabled=true

kubectl -n powerscale-monitoring rollout status deploy/pscale-powerscale-exporter
kubectl -n powerscale-monitoring port-forward svc/pscale-powerscale-exporter-clusterip 8000:8000
# open http://localhost:8000/metrics/
```

Demo mode also deploys the mock OneFS cluster in-chart and points the
exporter at it (`ISILON_HOST` = mock service, 15s scrape interval).

## Real cluster

```bash
helm install pscale ./helm/powerscale-exporter \
  --set isilon.host=10.0.0.5 \
  --set isilon.port=8080 \
  --set auth.user=monitor \
  --set auth.password='...'
```

Prefer not to pass the password on the command line? Create the Secret
yourself and point the chart at it:

```bash
kubectl -n powerscale-monitoring create secret generic onefs-creds \
  --from-literal=ISILON_USER=monitor --from-literal=ISILON_PASS='...'

helm install pscale ./helm/powerscale-exporter \
  --set isilon.host=10.0.0.5 \
  --set auth.existingSecret=onefs-creds
```

## Upgrading

```bash
helm upgrade pscale ./helm/powerscale-exporter --set mock.enabled=true
```

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `1` | Exporter replicas |
| `namespace.create` / `namespace.name` | `true` / `powerscale-monitoring` | Namespace handling |
| `image.repository` / `image.tag` / `image.pullPolicy` | `awhchan/powerscale-exporter` / `latest` / `IfNotPresent` | Exporter image |
| `isilon.host` / `isilon.port` | `powerscale.example.com` / `8080` | Target cluster (ignored when `mock.enabled`) |
| `scrapeInterval`, `tombstoneTtl`, `logLevel`, `maxRetries`, `timeout`, `circuitBreakerThreshold` | see `values.yaml` | Exporter tuning (ConfigMap) |
| `auth.user` / `auth.password` / `auth.existingSecret` | `root` / `demo` / `""` | Credentials (Secret) |
| `mock.enabled` | `false` | Deploy the mock OneFS cluster in-chart |
| `mock.image.*` | `awhchan/powerscale-mock-onefs:latest` | Mock image |
| `service.clusterIP.enabled` | `true` | Internal metrics service |
| `service.nodePort.enabled` / `service.nodePort.port` | `false` / `30080` | NodePort exposure |
| `networkPolicy.enabled` / `networkPolicy.egressCidrs` | `true` / private ranges | Lock down exporter traffic |
| `resources` | `128Mi/100m` req, `256Mi/200m` lim | Exporter resources |
