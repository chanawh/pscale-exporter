# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-10-15

Deeper OneFS coverage: nine new metric families collected on the slow
cadence.

### Added
- SyncIQ policy metrics: `isilon_synciq_policy_info`,
  `isilon_synciq_policy_enabled`, `isilon_synciq_policy_last_success_timestamp`
  (per policy)
- Quota metrics: `isilon_quota_usage_bytes`, `isilon_quota_limit_bytes`,
  `isilon_quota_usage_ratio` (per quota: `quota_id`/`path`/`type` labels)
- Share inventory: `isilon_nfs_export_info` (per export),
  `isilon_smb_share_info` (per share)
- `isilon_drive_firmware_info` (per drive)
- e2e CI asserts all nine new series against the mock OneFS API

### Notes
- The duplicate PSU metric was deliberately skipped: v1.2.0's
  hardware-sensor coverage already reports PSU health.

## [2.0.0] - 2026-10-14

One exporter scrapes multiple clusters.

### Added
- Multi-cluster scraping via `ISILON_TARGETS` / `ISILON_TARGETS_FILE`;
  per-target health reporting
- Two-cluster e2e assertion in CI

### Notes
- Every series already carried a `cluster_name` label, so no metric-name or
  label changes were needed: existing dashboards and the 18 alert rules work
  unchanged across clusters.
- Multi-cluster is opt-in: without `ISILON_TARGETS`/`ISILON_TARGETS_FILE`
  the exporter runs exactly like v1 (single cluster from
  `ISILON_HOST`/`ISILON_PASS`).

## [1.2.0] - 2026-10-14

Feature release: broader metric coverage, production readiness signals, and
hardened delivery.

### Added
- 13 new gauges: OneFS events, snapshots, storage pools, hardware sensors,
  dedupe, CloudPools, cluster/node versions
- Slow-collector cadence for expensive endpoints, with an event cardinality
  guard
- `/livez` and readiness-gated `/readyz` endpoints
- Optional bearer auth and native TLS for the exporter itself
- Mock OneFS fault-injection endpoints (drive failure, node-down scenarios)
- Capacity recording rules and 4 new alerts (18 total)
- e2e CI job: demo stack boot, key-series assertions, drive-failure
  round-trip

### Fixed
- `Dockerfile` runtime stage now ships `collectors.py` (was
  `ModuleNotFoundError` at startup)
- Dedupe discovery: endpoints returning summary dicts are discovered, not
  just lists

## [1.0.0] - 2026-10-13

First hardened release. Twelve PRs took the original exporter from
broken-CI prototype to a documented, demo-proven, production-shaped
project:

### Added
- Test suite (pytest) with black/ruff/mypy/pip-audit gates in CI
- Mock OneFS cluster (`mock_onefs/`) and hardware-free demo paths:
  Docker Compose, kind + Kustomize, Helm (`mock.enabled=true`)
- Helm chart (`helm/powerscale-exporter`) for real-cluster and demo installs
- Kustomize demo overlay deploying the mock in-cluster
- Alert runbooks (`docs/runbooks.md`) linked from every alert annotation
- Release inputs: `docker/metadata-action` configured to publish versioned
  Docker Hub tags from git tags (`type=ref,event=tag`) — however, the
  workflow's `on:` block had no `tags:` trigger, so tag pushes never ran CI
  and no versioned (`:1.0.0`) image was ever published (fixed in Unreleased;
  Docker Hub held only `latest`/`main`/`sha-*` tags as of 2026-10-15)

### Changed
- Full README rewrite: verified quickstarts, real metric names from live
  `/metrics/` output, architecture diagram, accurate config reference
- Multi-stage Dockerfiles, non-root `appuser` (uid 10001), read-only root
  filesystem
- EKS deploy job gated to manual `workflow_dispatch`
- Hash-pinned dependencies (`requirements.in` → `requirements.txt`)

### Fixed
- Drive metrics silently skipped: mock drive IDs `bay-N-M` → `N:M`
  (exporter parses `node:drive` labels)
- Demo kustomize overlay referenced files outside its root
  (`LoadRestrictionsRootOnly`) — added base kustomization
- Exporter refused to start without `ISILON_PASS` in every path
  (previously only Compose failed fast; `main.py` defaulted to `"a"`)
- Removed 3 alert rules firing on metrics the exporter never emits
  (`isilon_node_memory_total_gb`, `isilon_node_net_errors_total`)
- kind node image pinned to v1.32.0 for Docker Desktop (cgroup v1) hosts

### Removed
- Stale `deploy-kind.sh` (Podman/`localhost/` flow contradicted the docs)
- Fabricated metric names and stale deployment paths from the README

## [0.1.0] - 2024-03-26

### Added
- Initial release of PowerScale Prometheus Exporter
- Comprehensive metrics collection for Dell PowerScale/Isilon clusters
- FastAPI-based HTTP endpoints for Prometheus metrics
- Docker containerization with docker-compose orchestration
- SSH tunnel support for secure cluster access
- Circuit breaker pattern for fault tolerance
- Health check endpoints (`/healthz`, `/`)
- Prometheus metrics endpoint (`/metrics/`)
- Grafana dashboards for visualization
- Prometheus alerting rules
- Alertmanager configuration
- Comprehensive documentation
- CI/CD pipeline foundation with GitHub Actions
- Code quality tools (Black, Ruff, MyPy)
- Security scanning (Safety, Bandit)
- Unit and integration test framework
- Package configuration with pyproject.toml
- Project cleanup and structure optimization

### Features
- **Cluster Monitoring**: Overall health status and capacity metrics
- **Node Monitoring**: Per-node CPU, memory, disk, and network statistics
- **Drive Monitoring**: Individual drive health and performance metrics
- **Performance Metrics**: Network throughput, operation counts, latency tracking
- **Auto-Discovery**: Automatic API endpoint and metric detection
- **Error Handling**: Comprehensive error recovery and retry logic
- **Production Ready**: Structured logging, health checks, graceful shutdown

### Architecture
- **Modern Python**: Python 3.11+ with type hints
- **Async Framework**: FastAPI for high-performance HTTP endpoints
- **Prometheus Integration**: Standard metrics exposition format
- **Container Security**: Minimal base images and security scanning
- **Scalable Design**: Modular architecture for easy extension

### Documentation
- Comprehensive README with installation and usage guides
- API documentation with endpoint descriptions
- Troubleshooting guide with common issues
- Development setup and contribution guidelines
- Architecture overview and design decisions
- CHANGELOG.md for version tracking
- CONTRIBUTING.md for development guidelines
- LICENSE file for legal compliance

### Project Structure
- Clean separation of application code and configuration
- Docker files moved to project root for standard structure
- Eliminated redundant files and configurations
- Comprehensive .gitignore for Python projects
- Centralized dependency management

### CI/CD
- Automated testing on Python 3.11 and 3.12
- Code quality checks with formatting and linting
- Security vulnerability scanning
- Build and package validation
- Coverage reporting and analysis

## [Unreleased]

### Fixed
- Versioned Docker Hub images now publish on git tag pushes: added
  `tags: ['v*']` to the workflow `on:` block and switched both image
  metadata blocks (exporter + mock) from `type=ref,event=tag` to
  `type=semver,pattern={{version}}`, so pushing `vX.Y.Z` publishes image
  tag `X.Y.Z`. Previously the `type=ref,event=tag` lines were dead config —
  tag pushes never ran CI, and no `:1.0.0`/`:1.2.0`/`:2.0.0`/`:3.0.0` images
  were ever published.

### Backfill (run after this PR merges)
The `v1.2.0`, `v2.0.0`, and `v3.0.0` tags already exist but never ran CI.
Delete and re-push each tag to trigger the workflow; the tags keep pointing
at the same commits, so the GitHub Releases are unaffected:

```bash
for v in 1.2.0 2.0.0 3.0.0; do
  git push origin :refs/tags/v$v
  git push origin v$v
done
```

Each re-push runs CI and publishes the matching semver image tag
(`awhchan/powerscale-exporter:1.2.0`, `:2.0.0`, `:3.0.0`, and the same for
`awhchan/powerscale-mock-onefs`). Verify on Docker Hub afterwards.

---

## Version History

### v0.1.0 (2024-03-26)
- **Initial Release**: Complete PowerScale monitoring solution
- **Production Ready**: Full CI/CD pipeline and comprehensive testing
- **Documentation**: Complete setup and usage documentation
- **Security**: Automated vulnerability scanning and secure defaults
- **Structure**: Clean project structure with no redundancy

---

## Migration Guide

### From v0.0.x to v0.1.0
No breaking changes. This is the initial stable release.

### Environment Variables
All configuration is now handled through environment variables for better containerization and security.

### Docker Changes
- Moved from `requirements.txt` in exporter to root `requirements.txt`
- Updated build context for better security
- Added health checks and proper signal handling
- Simplified dependency installation

### Configuration
- Centralized all configuration in environment variables
- Removed hardcoded credentials
- Added comprehensive logging configuration

---

## Support

For questions about this changelog or to report issues:
- Create an issue on GitHub
- Check the documentation for troubleshooting
- Review the migration guide for upgrade instructions
