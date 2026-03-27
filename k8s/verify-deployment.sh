#!/bin/bash

# PowerScale Exporter Kubernetes Deployment Verification Script
# This script verifies that all components are working correctly

set -e

NAMESPACE="powerscale-monitoring"
SERVICE_NAME="powerscale-exporter"

echo "🔍 Verifying PowerScale Exporter Kubernetes Deployment..."
echo ""

# Check namespace exists
echo "📋 Checking namespace..."
if kubectl get namespace $NAMESPACE > /dev/null 2>&1; then
    echo "✅ Namespace '$NAMESPACE' exists"
else
    echo "❌ Namespace '$NAMESPACE' not found"
    exit 1
fi

# Check deployment
echo "📦 Checking deployment..."
if kubectl get deployment $SERVICE_NAME -n $NAMESPACE > /dev/null 2>&1; then
    echo "✅ Deployment '$SERVICE_NAME' exists"
    REPLICAS=$(kubectl get deployment $SERVICE_NAME -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
    echo "   Ready replicas: $REPLICAS"
else
    echo "❌ Deployment '$SERVICE_NAME' not found"
    exit 1
fi

# Check pods
echo "🐳 Checking pods..."
POD_STATUS=$(kubectl get pods -l app=$SERVICE_NAME -n $NAMESPACE -o jsonpath='{.items[0].status.phase}')
READY_REPLICAS=$(kubectl get pods -l app=$SERVICE_NAME -n $NAMESPACE -o jsonpath='{.items[0].status.containerStatuses[0].ready}')
echo "   Pod status: $POD_STATUS"
echo "   Ready containers: $READY_REPLICAS"

if [[ "$POD_STATUS" == "Running" && "$READY_REPLICAS" == "true" ]]; then
    echo "✅ Pods are running and ready"
else
    echo "⚠️  Pods not ready - checking logs..."
    kubectl logs -l app=$SERVICE_NAME -n $NAMESPACE --tail=10
fi

# Check services
echo "🌐 Checking services..."
echo "   ClusterIP Service:"
if kubectl get service $SERVICE_NAME-clusterip -n $NAMESPACE > /dev/null 2>&1; then
    CLUSTER_IP=$(kubectl get service $SERVICE_NAME-clusterip -n $NAMESPACE -o jsonpath='{.spec.clusterIPs[0]}')
    echo "   ✅ $SERVICE_NAME-clusterip: $CLUSTER_IP:8000"
else
    echo "   ❌ ClusterIP service not found"
fi

echo "   NodePort Service:"
if kubectl get service $SERVICE_NAME-nodeport -n $NAMESPACE > /dev/null 2>&1; then
    NODE_PORT=$(kubectl get service $SERVICE_NAME-nodeport -n $NAMESPACE -o jsonpath='{.spec.ports[0].nodePort}')
    echo "   ✅ $SERVICE_NAME-nodeport: localhost:$NODE_PORT (requires port-forward)"
else
    echo "   ❌ NodePort service not found"
fi

# Test health endpoint
echo "💓 Testing health endpoint..."
if [[ -n "$CLUSTER_IP" ]]; then
    if kubectl run health-test --image=curlimages/curl --rm -i --restart=Never -- curl -f http://$CLUSTER_IP:8000/healthz -n $NAMESPACE > /dev/null 2>&1; then
        echo "✅ Health endpoint responding"
    else
        echo "❌ Health endpoint not responding"
    fi
fi

# Test metrics endpoint
echo "📊 Testing metrics endpoint..."
if [[ -n "$CLUSTER_IP" ]]; then
    if kubectl run metrics-test --image=curlimages/curl --rm -i --restart=Never -- curl -f http://$CLUSTER_IP:8000/metrics/ -n $NAMESPACE > /dev/null 2>&1; then
        METRICS_COUNT=$(kubectl run metrics-test --image=curlimages/curl --rm -i --restart=Never -- curl -s http://$CLUSTER_IP:8000/metrics/ -n $NAMESPACE | grep -c "^# HELP")
        echo "✅ Metrics endpoint responding ($METRICS_COUNT metric types found)"
    else
        echo "❌ Metrics endpoint not responding"
    fi
fi

# Check network policies
echo "🔒 Checking network policies..."
if kubectl get networkpolicy $SERVICE_NAME-netpol -n $NAMESPACE > /dev/null 2>&1; then
    echo "✅ Network policy '$SERVICE_NAME-netpol' exists"
else
    echo "⚠️  Network policy not found (optional for basic functionality)"
fi

# Summary
echo ""
echo "🎯 Deployment Summary:"
echo "   Namespace: $NAMESPACE"
echo "   Application: $SERVICE_NAME"
echo "   Health: http://$CLUSTER_IP:8000/healthz"
echo "   Metrics: http://$CLUSTER_IP:8000/metrics/"
echo ""
echo "📝 To access from host:"
echo "   kubectl port-forward -n $NAMESPACE svc/$SERVICE_NAME-clusterip 8000:8000"
echo ""
echo "✅ Kubernetes deployment verification complete!"
