#!/bin/bash

# PowerScale Exporter KIND Deployment Script for Podman
# This script handles deployment to KIND cluster running in Podman

set -e

KIND_CONTAINER="kind-cluster-control-plane"
NAMESPACE="powerscale-monitoring"
IMAGE_NAME="localhost/powerscale-exporter_isilon-exporter:latest"

echo "🚀 Deploying PowerScale Exporter to KIND cluster..."

# Check if KIND container is running
if ! podman ps | grep -q $KIND_CONTAINER; then
    echo "❌ KIND container '$KIND_CONTAINER' is not running"
    echo "💡 Start your KIND cluster first"
    exit 1
fi

# Build local image if not exists
echo "🏗️  Building local image..."
if ! podman images | grep -q powerscale-exporter_isilon-exporter; then
    podman build -t $IMAGE_NAME .
    echo "✅ Image built successfully"
else
    echo "✅ Image already exists"
fi

# Copy Kubernetes manifests to KIND container
echo "� Copying Kubernetes manifests..."
podman cp k8s/manifests $KIND_CONTAINER:/tmp/k8s/
podman cp k8s/scripts $KIND_CONTAINER:/tmp/k8s/

# Apply all manifests
echo "🔧 Applying Kubernetes manifests..."
podman exec $KIND_CONTAINER bash -c "kubectl apply -f /tmp/k8s/manifests/namespace.yaml"
podman exec $KIND_CONTAINER bash -c "kubectl apply -f /tmp/k8s/manifests/configmap.yaml"
podman exec $KIND_CONTAINER bash -c "kubectl apply -f /tmp/k8s/manifests/deployment.yaml"
podman exec $KIND_CONTAINER bash -c "kubectl apply -f /tmp/k8s/manifests/service-clusterip.yaml"
podman exec $KIND_CONTAINER bash -c "kubectl apply -f /tmp/k8s/manifests/service-nodeport.yaml"
podman exec $KIND_CONTAINER bash -c "kubectl apply -f /tmp/k8s/manifests/networkpolicy.yaml"

# Wait for namespace to be created
echo "⏳ Waiting for namespace to be ready..."
podman exec $KIND_CONTAINER kubectl wait --for=condition=Ready namespace/$NAMESPACE --timeout=60s || true

# Configure secrets (prompt for password)
echo "🔑 Configuring PowerScale credentials..."
read -s -p "Enter PowerScale password: " ISILON_PASS
echo

podman exec $KIND_CONTAINER kubectl create secret generic powerscale-exporter-secrets \
    --from-literal=ISILON_USER=root \
    --from-literal=ISILON_PASS="$ISILON_PASS" \
    --namespace=$NAMESPACE \
    --dry-run=client -o yaml | podman exec -i $KIND_CONTAINER kubectl apply -f -

# Restart deployment to pick up new secrets
echo "🔄 Restarting deployment to apply new secrets..."
podman exec $KIND_CONTAINER kubectl rollout restart deployment/powerscale-exporter -n $NAMESPACE

# Wait for pods to be ready
echo "⏳ Waiting for pods to be ready..."
podman exec $KIND_CONTAINER kubectl wait --for=condition=ready pod \
    -l app=powerscale-exporter -n $NAMESPACE --timeout=300s

# Run verification script
echo "🔍 Running deployment verification..."
podman exec $KIND_CONTAINER bash -c "chmod +x /tmp/k8s/scripts/verify-deployment.sh && /tmp/k8s/scripts/verify-deployment.sh"

# Show pod logs
echo "📋 Recent pod logs:"
podman exec $KIND_CONTAINER kubectl logs -l app=powerscale-exporter -n $NAMESPACE --tail=20

# Test the service
echo "🧪 Testing service endpoints..."

# Test NodePort access
echo "Testing NodePort access (http://localhost:30080)..."
if curl -f http://localhost:30080/healthz > /dev/null 2>&1; then
    echo "✅ NodePort accessible"
    curl http://localhost:30080/healthz
else
    echo "⚠️  NodePort not responding, trying port-forward..."
    echo "🌐 Setting up port forwarding..."
    podman exec $KIND_CONTAINER kubectl port-forward -n $NAMESPACE svc/powerscale-exporter-clusterip 8000:8000 &
    PORT_FORWARD_PID=$!
    sleep 3
    if curl -f http://localhost:8000/healthz > /dev/null 2>&1; then
        echo "✅ Service accessible via port-forward"
        curl http://localhost:8000/healthz
    else
        echo "❌ Service not responding"
    fi
fi

echo ""
echo "🎉 PowerScale Exporter is running successfully!"
echo ""
echo "📊 Access endpoints:"
if curl -s --max-time 5 http://localhost:30080/healthz > /dev/null 2>&1; then
    echo "   Health:  http://localhost:30080/healthz"
    echo "   Metrics: http://localhost:30080/metrics/"
else
    echo "   Health:  http://localhost:8000/healthz"
    echo "   Metrics: http://localhost:8000/metrics/"
fi
echo ""
echo "🔍 Debug commands:"
echo "   podman exec $KIND_CONTAINER kubectl get pods -n $NAMESPACE"
echo "   podman exec $KIND_CONTAINER kubectl logs -f deployment/powerscale-exporter -n $NAMESPACE"
echo "   podman exec $KIND_CONTAINER kubectl describe pod -l app=powerscale-exporter -n $NAMESPACE"
