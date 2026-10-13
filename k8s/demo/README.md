# Kubernetes demo (kind)

Runs the exporter against the mock OneFS cluster **inside Kubernetes** — no
PowerScale hardware, no cloud account needed. Images are pulled from Docker Hub
(published by CI from `main`).

## Run it

```bash
kind create cluster --name pscale-demo

kubectl apply -k k8s/demo/

kubectl -n powerscale-monitoring rollout status deploy/mock-onefs
kubectl -n powerscale-monitoring rollout status deploy/powerscale-exporter

kubectl -n powerscale-monitoring port-forward svc/powerscale-exporter-clusterip 8000:8000
```

Then open:

- http://localhost:8000/metrics/ — live `isilon_*` series scraped from the mock
- http://localhost:8000/healthz — health and endpoint-discovery status

## What the overlay does

`k8s/demo/kustomization.yaml` builds on the base manifests in `k8s/manifests/`
and adds demo-only pieces:

- `mock-onefs.yaml` — the mock OneFS Deployment + Service
- `demo-secret.yaml` — demo credentials (the mock accepts any user/pass)
- `configmap-patch.yaml` — points the exporter at `mock-onefs:8080`

## Against a real cluster

Apply the base manifests and provide your own secret — the demo secret is
**not** for real use:

```bash
kubectl apply -f k8s/manifests/namespace.yaml
kubectl apply -f k8s/manifests/configmap.yaml   # edit ISILON_HOST first
kubectl -n powerscale-monitoring create secret generic powerscale-exporter-secrets \
  --from-literal=ISILON_USER='<user>' --from-literal=ISILON_PASS='<pass>'
kubectl apply -f k8s/manifests/deployment.yaml
kubectl apply -f k8s/manifests/service-clusterip.yaml
kubectl apply -f k8s/manifests/networkpolicy.yaml
```

## Clean up

```bash
kind delete cluster --name pscale-demo
```
