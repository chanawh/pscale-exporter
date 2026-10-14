# PowerScale Exporter — Comprehensive Guide (retired)

> **This guide is no longer maintained.** It described the original
> pre-hardening project — SSH-tunnel-centric architecture, Podman-based
> KIND flow, and metric names the exporter never emitted — and
> contradicts the current code. It is kept as a pointer so old links
> don't rot; the original content is preserved in git history.
>
> Everything worth keeping now lives in the [README](README.md),
> verified against the current code and a live kind deployment:
>
> - Architecture diagram
> - Three hardware-free demo quickstarts (Compose, kind + Kustomize, Helm)
> - Real-cluster deployment paths (Helm, Kustomize, Compose, bare metal)
> - Full metrics reference with real names from live `/metrics/` output
> - Configuration, monitoring/alerting (with [runbooks](docs/runbooks.md)),
>   and troubleshooting from real incidents
