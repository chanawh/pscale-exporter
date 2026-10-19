# PowerScale Exporter Operator

A Kubernetes operator (Go, controller-runtime) that manages PowerScale/OneFS
Prometheus exporter deployments from a single custom resource.

## What it does

One `PowerScaleExporter` CR (`monitoring.chanawh.io/v1alpha1`) reconciles:

- a **Deployment** running the exporter (env from Secrets — credentials are
  never inlined in the CR), with `/livez` / `/readyz` probes,
- a **ClusterIP Service** fronting the exporter pods,
- a **targets Secret** in multi-cluster mode: the operator resolves each
  cluster's credentials from its Secret, renders `targets.json`
  (`ISILON_TARGETS_FILE`), and mounts it — the same semantics as the
  exporter's `ISILON_TARGETS`, including fail-fast on missing passwords,
- a Prometheus Operator **ServiceMonitor** when `serviceMonitor.enabled`.

All owned resources carry a controller OwnerReference, so deleting the CR
cascades. The CR status reports `Available` / `Degraded` conditions and the
reconciled generation.

## Install

```bash
# CRD + RBAC
kubectl apply -f config/crd/bases/monitoring.chanawh.io_powerscaleexporters.yaml
kubectl apply -f config/rbac/role.yaml

# Deploy the controller (build the image first — see below)
# kubectl apply -f config/manager/  # TODO: add manager Deployment manifest

# Credentials, then a CR
kubectl create secret generic isilon-auth -n powerscale-monitoring \
  --from-literal=ISILON_USER=root --from-literal=ISILON_PASS='change-me'
kubectl apply -f config/examples/powerscaleexporter-single.yaml
```

Multi-cluster example: `config/examples/powerscaleexporter-multi.yaml`.

## Develop

Requires Go 1.23+.

```bash
cd operator
go build ./...
go vet ./...
go test ./...
```

Tests use the controller-runtime fake client (no cluster needed): CR create →
Deployment/Service(/ServiceMonitor) shape assertions, spec-update rollout,
missing-credential Degraded path, multi→single cluster Secret cleanup.

## Design notes

- **No defaulting webhook**: defaults (replicas=1, port 8080, secret key
  names, image) are applied in-memory by the reconciler, so the operator
  runs without cert-manager.
- **Secret hygiene**: the controller only *reads* referenced Secrets; the
  rendered targets Secret is owned by the CR and garbage-collected with it.
- **Drift correction**: on every reconcile the controller overwrites the
  Deployment pod template / Service ports / ServiceMonitor spec from the CR,
  so manual edits are reverted.
- **Config errors are Degraded, not crashes**: an unresolvable credential
  Secret sets `Degraded=True` and requeues in 30s instead of deploying a
  broken exporter.

## Honest verification note

`go build`, `go vet`, and `go test` are green (fake-client unit tests).
**Not verified here**: e2e against kind or a live cluster — there is no
`config/manager` Deployment manifest yet and no envtest/control-plane
binaries in this environment, so real API-server behavior (garbage
collection on CR deletion, ServiceMonitor acceptance by Prometheus
Operator) is unexercised. The fake client also has no GC; cascade deletion
is asserted via OwnerReferences, which is what a real cluster acts on.
