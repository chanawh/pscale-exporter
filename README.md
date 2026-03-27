# PowerScale Prometheus Exporter

A comprehensive Prometheus exporter for Dell PowerScale / Isilon storage clusters, providing detailed metrics for monitoring storage infrastructure health and performance.

## 🚀 Features

- **Cluster Health Monitoring**: Overall cluster status and node availability
- **Performance Metrics**: CPU, memory, disk, and network statistics per node
- **Storage Metrics**: Capacity usage, quota counts, NFS/SMB shares
- **Drive Health**: Individual drive status and performance monitoring
- **Replication Monitoring**: SyncIQ replication lag tracking
- **Auto-Discovery**: Automatic API endpoint and metric discovery
- **Production Ready**: Health checks, error handling, retry logic
- **Containerized**: Docker and docker-compose deployment ready
- **CI/CD Ready**: Comprehensive testing, linting, and security scanning

## 🏗️ Architecture

- **FastAPI**: Modern async web framework for HTTP endpoints
- **Prometheus Client**: Standard metrics exposition format
- **Robust Scraper**: Resilient OneFS API client with auto-retry
- **Circuit Breaker**: Fault tolerance with automatic recovery
- **Containerized**: Docker and docker-compose deployment ready

## 📋 Prerequisites

- Docker & Docker Compose (recommended)
- Python 3.11+ (for manual installation)
- Access to Dell PowerScale/Isilon OneFS API
- SSH tunnel configuration (for secure cluster access)

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Clone and start all services
git clone <repository-url>
cd powerscale-exporter
docker-compose up -d

# Verify services are running
curl http://localhost:8000/healthz
curl http://localhost:19091/api/v1/targets
curl http://localhost:13001
```

This starts:
- **PowerScale exporter** on port 8000
- **Prometheus** on port 19091
- **Grafana** on port 13001
- **SSH tunnel** for secure cluster access

### Option 2: Kubernetes Deployment

#### Standard Kubernetes
```bash
# For clusters with kubectl available locally
kubectl apply -f k8s/

# Configure credentials
kubectl create secret generic powerscale-exporter-secrets \
  --from-literal=ISILON_USER=root \
  --from-literal=ISILON_PASS=your-password \
  --namespace=powerscale-monitoring \
  --dry-run=client -o yaml | kubectl apply -f -

# Verify deployment
kubectl get pods -n powerscale-monitoring
kubectl get services -n powerscale-monitoring
```

#### Podman KIND (Local Testing)
```bash
# Build local image
podman build -t localhost/powerscale-exporter_isilon-exporter:latest .

# Deploy to KIND cluster
./deploy-kind.sh

# Or manual deployment:
podman cp k8s/ kind-cluster-control-plane:/tmp/
podman exec kind-cluster-control-plane kubectl apply -f /tmp/k8s/

# Access via NodePort
curl http://localhost:30080/healthz
curl http://localhost:30080/metrics/
```

### Option 3: Manual Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ISILON_HOST=your-cluster-host
export ISILON_PORT=8080
export ISILON_USER=root
export ISILON_PASS=your-password
export SCRAPE_INTERVAL=30

# Run the exporter
cd exporter
python main.py
```

## 📊 Available Metrics

### Cluster Metrics
- `isilon_cluster_health` - Overall cluster status (1=healthy, 0=unhealthy)
- `isilon_cluster_capacity_bytes` - Total cluster capacity in bytes
- `isilon_cluster_used_bytes` - Used storage in bytes
- `isilon_cluster_available_bytes` - Available storage in bytes

### Node Metrics
- `isilon_node_status` - Node health status (1=online, 0=offline)
- `isilon_node_cpu_percent` - CPU utilization percentage
- `isilon_node_memory_bytes` - Memory usage statistics
- `isilon_node_disk_bytes` - Disk usage and performance

### Drive Metrics
- `isilon_drive_status` - Individual drive health
- `isilon_drive_temperature_celsius` - Drive temperature
- `isilon_drive_bytes` - Drive capacity and usage

### Performance Metrics
- `isilon_network_bytes_total` - Network throughput
- `isilon_ops_total` - Operation counts by type
- `isilon_latency_seconds` - Response time metrics

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ISILON_HOST` | 127.0.0.1 | PowerScale cluster hostname |
| `ISILON_PORT` | 8080 | API port |
| `ISILON_USER` | root | Username |
| `ISILON_PASS` | a | Password |
| `SCRAPE_INTERVAL` | 30 | Metrics collection interval (seconds) |
| `TOMBSTONE_TTL` | 86400 | Node tombstone TTL (seconds) |

## 🛠️ Development

### Setup Development Environment

```bash
# Install development dependencies
pip install -r requirements.txt
pip install -e exporter/

# Run tests with coverage
pytest test/ -v --cov=exporter --cov-report=html

# Code formatting and linting
black .
ruff check .
mypy exporter/ --ignore-missing-imports

# Security scanning
safety check
bandit -r exporter/
```

### Project Structure

```
powerscale-exporter/
├── exporter/                 # Core application
│   ├── main.py              # FastAPI application entry point
│   ├── scraper.py           # OneFS API client
│   └── pyproject.toml       # Package configuration
├── grafana/                 # Grafana dashboards & provisioning
├── Dockerfile               # Container build configuration
├── docker-compose.yml       # Service orchestration
├── requirements.txt        # Python dependencies
├── prometheus.yml           # Prometheus configuration
├── alert-rules.yml          # Alert rules
├── alertmanager.yml         # Alertmanager configuration
├── README.md                # This file
├── CHANGELOG.md             # Version history
├── CONTRIBUTING.md          # Development guidelines
├── LICENSE                  # MIT License
└── .gitignore               # Git exclusions
```

## 📈 Monitoring & Alerting

### Grafana Dashboards

Pre-configured dashboards include:
- **Cluster Overview**: Overall health and capacity
- **Node Performance**: Per-node resource utilization
- **Storage Analytics**: Capacity trends and usage patterns
- **Drive Health**: Hardware monitoring and alerts

### Alert Rules

Critical alerts configured:
- Cluster health degradation
- Node offline detection
- Capacity threshold warnings
- Drive failure notifications
- High latency alerts

## 🔒 Security

- **SSH Tunneling**: Secure cluster communication
- **API Authentication**: OneFS API token management
- **Container Security**: Minimal base images
- **Secrets Management**: Environment-based configuration
- **Security Scanning**: Automated vulnerability checks

## 🧪 Testing

### Test Suite

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=exporter --cov-report=html

# Run specific test categories
pytest -m unit
pytest -m integration
```

## 🚀 Deployment

### Production Deployment

1. **Environment Setup**: Configure environment variables
2. **SSL/TLS**: Configure HTTPS endpoints
3. **Authentication**: Set up proper API credentials
4. **Monitoring**: Configure alert thresholds
5. **Backup**: Regular configuration backups

## 🔄 CI/CD Pipeline

### GitHub Actions

Automated pipeline includes:
- **Code Quality**: Black formatting, Ruff linting, MyPy type checking
- **Testing**: Unit and integration tests with coverage
- **Security**: Safety dependency scanning, Bandit security analysis
- **Build**: Package creation and validation
- **Multi-Python**: Testing on Python 3.11 and 3.12

## 📚 Documentation

### Essential Reading
- **[COMPREHENSIVE_GUIDE.md](COMPREHENSIVE_GUIDE.md)** - Complete project documentation with detailed KIND/Podman deployment
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and changes
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contribution guidelines

## 📊 API Documentation

### Endpoints

- `GET /` - Application information
- `GET /healthz` - Health check endpoint
- `GET /metrics` - Prometheus metrics endpoint

### Health Check Response

```json
{
  "status": "healthy",
  "timestamp": "2024-03-26T16:30:00Z",
  "version": "0.1.0"
}
```

## 🐛 Troubleshooting

### Common Issues

**SSH Tunnel Connection Failed**
- Verify SSH key permissions
- Check network connectivity
- Validate jump host configuration

**API Authentication Errors**
- Verify OneFS API credentials
- Check API version compatibility
- Validate user permissions

**Metrics Not Updating**
- Check cluster connectivity
- Verify API endpoint accessibility
- Review scraper logs

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
python main.py
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add unit tests for new features
- Update documentation
- Ensure all CI checks pass

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Dell Technologies for PowerScale/Isilon API documentation
- Prometheus community for metrics best practices
- Grafana for visualization platform
- FastAPI for modern web framework

## 📞 Support

For issues and questions:
- Create GitHub Issue for bug reports
- Check documentation for common solutions
- Review logs for error details

---

**Note**: This exporter is designed for monitoring Dell PowerScale/Isilon storage clusters and requires proper API access and network connectivity to function correctly.
