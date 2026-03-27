# PowerScale Exporter - Comprehensive Guide

## 🎯 Project Overview

The PowerScale Exporter is a **production-ready Prometheus exporter** for Dell PowerScale / Isilon storage clusters, providing comprehensive monitoring, performance metrics, and health status reporting.

### Architecture
```
PowerScale Cluster → SSH Tunnel → Exporter → Prometheus → Grafana
```

### Core Components
- **FastAPI Application**: Lightweight HTTP server with `/healthz` and `/metrics/` endpoints
- **PowerScale Scraper**: Python client for API authentication and data collection
- **Security Layer**: Production-grade container and Kubernetes security
- **Monitoring Stack**: Prometheus integration with Grafana dashboards

### Metrics Collected
- **System Performance**: CPU, memory, disk, network metrics
- **Storage Capacity**: Total/used space, quotas, export statistics
- **Cluster Health**: Node status, drive health, network connectivity
- **Application Metrics**: Self-observability and performance indicators

## 🚀 Quick Start

### Option 1: Docker Compose (Development)
```bash
docker-compose up -d
# Grafana: http://localhost:3000 (admin/admin)
```

### Option 2: Kubernetes (Production)
```bash
kubectl apply -f k8s/
kubectl get pods -n powerscale-monitoring
```

### Option 3: KIND + Podman (Local Testing)
```bash
# Build and deploy
./deploy-kind.sh

# Verify deployment
podman exec kind-cluster-control-plane /tmp/k8s/verify-deployment.sh
```

## 📋 Prerequisites

### System Requirements
- **Python 3.11+** for local development
- **Docker/Podman** for container runtime
- **Kubernetes 1.25+** for production deployment
- **PowerScale 8.0+** with API access

### Network Requirements
- **Port 8080**: PowerScale API access
- **Port 8000**: Exporter metrics endpoint
- **Port 30080**: Kubernetes NodePort (optional)
- **SSH Access**: For tunnel configuration (if needed)

## 🐳 Deployment Options

### Docker Compose Development

#### Setup
```bash
# Clone repository
git clone <repository-url>
cd powerscale-exporter

# Start all services
docker-compose up -d

# Access services
curl http://localhost:8000/healthz
open http://localhost:3000  # Grafana
```

#### Configuration
Create `.env.local`:
```bash
ISILON_HOST=your-powerscale-cluster.com
ISILON_PORT=8080
ISILON_USER=monitoring-user
ISILON_PASS=secure-password
SCRAPE_INTERVAL=30
LOG_LEVEL=INFO
```

### Kubernetes Production Deployment

#### Namespace and Configuration
```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Apply configuration
kubectl apply -f k8s/configmap.yaml

# Create secrets
kubectl create secret generic powerscale-exporter-secrets \
  --from-literal=ISILON_USER=monitoring-user \
  --from-literal=ISILON_PASS=secure-password \
  --namespace=powerscale-monitoring
```

#### Application Deployment
```bash
# Deploy application
kubectl apply -f k8s/deployment.yaml

# Deploy services
kubectl apply -f k8s/service-clusterip.yaml
kubectl apply -f k8s/service-nodeport.yaml

# Apply security policy
kubectl apply -f k8s/networkpolicy.yaml
```

#### Verification
```bash
# Check deployment status
kubectl get pods -n powerscale-monitoring
kubectl get services -n powerscale-monitoring

# Run verification script
./k8s/verify-deployment.sh

# Test endpoints
kubectl port-forward -n powerscale-monitoring svc/powerscale-exporter-clusterip 8000:8000 &
curl http://localhost:8000/healthz
curl http://localhost:8000/metrics/
```

## 🔧 KIND + Podman Testing (Detailed)

### Environment Setup

#### Install Required Software
```bash
# Podman Installation
# Windows (Chocolatey)
choco install podman

# macOS (Homebrew)
brew install podman

# Linux (Ubuntu/Debian)
sudo apt update && sudo apt install podman

# KIND Installation
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-windows-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# kubectl Installation
curl -LO "https://dl.k8s.io/release/v1.28.0/bin/windows/amd64/kubectl.exe"
```

#### Create KIND Cluster
```bash
# Create KIND cluster with port mappings
kind create cluster --name powerscale-test --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 30080
    protocol: TCP
EOF
```

### Image Management

#### Build and Load Images
```bash
# Build the application image
podman build -t localhost/powerscale-exporter_isilon-exporter:latest .

# Load image into KIND cluster
kind load docker-image localhost/powerscale-exporter_isilon-exporter:latest --name powerscale-test

# Alternative: Manual image transfer
podman save localhost/powerscale-exporter_isilon-exporter:latest -o powerscale-exporter.tar
podman cp powerscale-exporter.tar kind-cluster-control-plane:/tmp/
podman exec kind-cluster-control-plane bash -c "ctr -n k8s.io images import /tmp/powerscale-exporter.tar"
```

### Kubernetes Deployment in KIND

#### Manual Deployment Steps
```bash
# Copy manifests to KIND container
podman cp k8s kind-cluster-control-plane:/tmp/

# Apply configurations (using bash wrapper for Windows compatibility)
podman exec kind-cluster-control-plane bash -c "kubectl apply -f /tmp/k8s/namespace.yaml"
podman exec kind-cluster-control-plane bash -c "kubectl apply -f /tmp/k8s/configmap.yaml"

# Create secrets
podman exec kind-cluster-control-plane bash -c "kubectl create secret generic powerscale-exporter-secrets \
  --from-literal=ISILON_USER=root \
  --from-literal=ISILON_PASS=a \
  --namespace=powerscale-monitoring"

# Deploy application
podman exec kind-cluster-control-plane bash -c "kubectl apply -f /tmp/k8s/deployment.yaml"
podman exec kind-cluster-control-plane bash -c "kubectl apply -f /tmp/k8s/service-clusterip.yaml"
podman exec kind-cluster-control-plane bash -c "kubectl apply -f /tmp/k8s/service-nodeport.yaml"
```

### Network Configuration

#### SSH Tunnel Setup
```bash
# Start isilon-tunnel container
podman-compose up -d isilon-tunnel

# Connect tunnel to KIND network
podman network connect kind isilon-tunnel

# Get tunnel IP address
TUNNEL_IP=$(podman inspect isilon-tunnel --format "{{.NetworkSettings.Networks.kind.IPAddress}}")

# Update ConfigMap with IP address
kubectl patch configmap powerscale-exporter-config -n powerscale-monitoring -p "data:
  ISILON_HOST: \"$TUNNEL_IP\""
```

#### Testing Connectivity
```bash
# Test PowerScale connectivity from KIND
podman exec kind-cluster-control-plane bash -c "kubectl exec deployment/powerscale-exporter -n powerscale-monitoring -- nc -zv $TUNNEL_IP 8080"

# Test API access
podman exec kind-cluster-control-plane bash -c "kubectl exec deployment/powerscale-exporter -n powerscale-monitoring -- curl -k https://$TUNNEL_IP:8080/platform/1"
```

### Verification and Testing

#### Health Checks
```bash
# Wait for pods to be ready
podman exec kind-cluster-control-plane bash -c "kubectl wait --for=condition=ready pod -l app=powerscale-exporter -n powerscale-monitoring --timeout=300s"

# Check pod logs
podman exec kind-cluster-control-plane bash -c "kubectl logs -f deployment/powerscale-exporter -n powerscale-monitoring"

# Test health endpoint
curl -f http://localhost:30080/healthz

# Test metrics endpoint
curl http://localhost:30080/metrics/ | head -20
```

#### Service Testing
```bash
# Port-forward testing (alternative to NodePort)
podman exec kind-cluster-control-plane bash -c "kubectl port-forward -n powerscale-monitoring svc/powerscale-exporter-clusterip 8000:8000 &"
PORT_FORWARD_PID=$!

# Test via port-forward
curl http://localhost:8000/healthz
curl http://localhost:8000/metrics/

# Clean up port-forward
kill $PORT_FORWARD_PID
```

## 🔒 Security Configuration

### Container Security
The deployment includes production-grade security:
- **Non-root user**: Runs as user ID 1000
- **Read-only filesystem**: Prevents unauthorized modifications
- **Capability dropping**: All Linux capabilities removed
- **Resource limits**: CPU and memory constraints

### Kubernetes Security
```yaml
# Network Policy Example
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: powerscale-exporter-netpol
spec:
  podSelector:
    matchLabels:
      app: powerscale-exporter
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 8000
```

## 📊 Monitoring Integration

### Prometheus Configuration
```yaml
scrape_configs:
  - job_name: 'powerscale-exporter'
    static_configs:
      - targets: ['powerscale-exporter-clusterip.powerscale-monitoring.svc.cluster.local:8000']
    scrape_interval: 30s
    metrics_path: /metrics/
```

### Grafana Dashboard
- **Complete Dashboard**: Comprehensive PowerScale monitoring
- **Pre-built Panels**: CPU, memory, storage, network metrics
- **Alert Integration**: Threshold-based notifications
- **Historical Analysis**: Trend visualization and capacity planning

## 🧪 Troubleshooting Guide

### Common Issues and Solutions

#### 1. Image Pull BackOff Error
**Problem**: `STATUS: ImagePullBackOff`

**Solution**:
```bash
# Verify image is loaded into KIND cluster
podman exec kind-cluster-control-plane bash -c "ctr -n k8s.io images ls | grep powerscale"

# Reload image if necessary
kind load docker-image localhost/powerscale-exporter_isilon-exporter:latest --name powerscale-test
```

#### 2. Windows Path Translation Problems
**Problem**: `ERROR: the path "C:/Users/..." does not exist`

**Solution**:
```bash
# Use bash wrapper for proper path handling
podman exec kind-cluster-control-plane bash -c "kubectl apply -f /tmp/k8s/"

# Copy directories without trailing slash
podman cp k8s kind-cluster-control-plane:/tmp/
```

#### 3. DNS Resolution Failure
**Problem**: `Failed to resolve 'isilon-tunnel'`

**Solution**:
```bash
# Get container IP address
TUNNEL_IP=$(podman inspect isilon-tunnel --format "{{.NetworkSettings.Networks.kind.IPAddress}}")

# Update configuration with IP
kubectl patch configmap powerscale-exporter-config -n powerscale-monitoring -p "data:
  ISILON_HOST: \"$TUNNEL_IP\""

# Restart deployment
kubectl rollout restart deployment/powerscale-exporter -n powerscale-monitoring
```

#### 4. Authentication Failures
**Problem**: `Exception: Authentication failed: 401`

**Solution**:
```bash
# Test authentication manually
curl -k -X POST -H 'Content-Type: application/json' \
  -u root:a -d '{"username":"root","password":"a"}' \
  https://$TUNNEL_IP:8080/session/1/session

# Update Kubernetes secret
kubectl create secret generic powerscale-exporter-secrets \
  --from-literal=ISILON_USER=root \
  --from-literal=ISILON_PASS=a \
  --namespace=powerscale-monitoring \
  --dry-run=client -o yaml | kubectl apply -f -
```

#### 5. NodePort Not Accessible
**Problem**: `curl: (7) Failed to connect to localhost port 30080`

**Solution**:
```bash
# Use port-forwarding instead
kubectl port-forward -n powerscale-monitoring svc/powerscale-exporter-clusterip 8000:8000 &
curl http://localhost:8000/healthz

# Or access within cluster
kubectl exec deployment/powerscale-exporter -n powerscale-monitoring -- curl http://localhost:8000/healthz
```

### Debug Commands

#### Cluster Information
```bash
# Cluster status
podman exec kind-cluster-control-plane bash -c "kubectl cluster-info"

# Node status
podman exec kind-cluster-control-plane bash -c "kubectl get nodes -o wide"

# All resources in namespace
podman exec kind-cluster-control-plane bash -c "kubectl get all -n powerscale-monitoring"
```

#### Network Debugging
```bash
# Test service connectivity
podman exec kind-cluster-control-plane bash -c "kubectl exec -n powerscale-monitoring deployment/powerscale-exporter -- curl http://localhost:8000/healthz"

# Check DNS resolution
podman exec kind-cluster-control-plane bash -c "kubectl exec -n powerscale-monitoring deployment/powerscale-exporter -- nslookup kubernetes.default"
```

## ☁️ AWS CI/CD Pipeline

### Prerequisites
- AWS account with EKS cluster
- Docker Hub account for image registry
- GitHub repository with secrets configured

### Required GitHub Secrets
```bash
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_REGION=us-east-1
EKS_CLUSTER_NAME=your-eks-cluster-name
POWERSCALE_PASSWORD=your-powerscale-password
```

### EKS Cluster Setup
```bash
# Create EKS cluster
aws eks create-cluster \
  --name powerscale-cluster \
  --region us-east-1 \
  --kubernetes-version 1.28 \
  --nodegroup-name standard-workers \
  --node-type t3.medium \
  --nodes 2 \
  --managed

# Configure kubectl
aws eks update-kubeconfig --name powerscale-cluster --region us-east-1
```

### Deployment Process
The CI/CD pipeline will:
1. **Test**: Run unit tests, code quality checks, security scanning
2. **Build**: Build and push Docker image to Docker Hub
3. **Deploy**: Deploy to AWS EKS cluster
4. **Verify**: Test endpoints and show deployment status

### Accessing AWS Service
```bash
# Port forward from local
kubectl port-forward -n powerscale-monitoring svc/powerscale-exporter-service 8000:8000 &
curl http://localhost:8000/healthz

# Get load balancer URL
kubectl get ingress powerscale-exporter-ingress -n powerscale-monitoring
curl http://powerscale.your-domain.com/healthz
```

## 📈 Advanced Features

### Horizontal Pod Autoscaling
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: powerscale-exporter-hpa
  namespace: powerscale-monitoring
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: powerscale-exporter
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Prometheus Operator Integration
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: powerscale-exporter
  namespace: powerscale-monitoring
spec:
  selector:
    matchLabels:
      app: powerscale-exporter
  endpoints:
  - port: http
    path: /metrics/
    interval: 30s
```

## 🧹 Cleanup

### Remove KIND Testing Environment
```bash
# Delete KIND cluster
kind delete cluster --name powerscale-test

# Remove local images
podman rmi localhost/powerscale-exporter_isilon-exporter:latest

# Clean up containers
podman-compose down
```

### Remove Kubernetes Deployment
```bash
# Delete all resources
kubectl delete namespace powerscale-monitoring

# Remove secrets
kubectl delete secret powerscale-exporter-secrets -n powerscale-monitoring
```

## 📚 Additional Resources

- **[README.md](README.md)** - Quick start and overview
- **[CHANGELOG.md](CHANGELOG.md)** - Version history
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contribution guidelines
- **[KIND Documentation](https://kind.sigs.k8s.io/)** - Kubernetes in Docker
- **[Podman Documentation](https://podman.io/)** - Container runtime
- **[Kubernetes Documentation](https://kubernetes.io/docs/)** - Container orchestration

---

## 🎯 Production Readiness Checklist

- ✅ **Security Contexts**: Non-root execution, read-only filesystem
- ✅ **Network Policies**: Traffic restrictions and isolation  
- ✅ **Resource Limits**: CPU and memory constraints
- ✅ **Health Checks**: Proper liveness and readiness probes
- ✅ **Monitoring**: Prometheus integration and alerting
- ✅ **Documentation**: Complete deployment and troubleshooting guides
- ✅ **CI/CD**: Automated testing and deployment pipelines
- ✅ **Scalability**: HPA and load balancing configurations

**This comprehensive guide provides all necessary information for development, testing, and production deployment of the PowerScale Exporter.**
