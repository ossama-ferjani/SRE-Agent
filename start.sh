#!/usr/bin/env bash
# start.sh — Start required port-forwards then launch the SRE agent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔗 Starting port-forwards..."

# Kill any stale port-forwards first
pkill -f "kubectl port-forward.*8080" 2>/dev/null || true
pkill -f "kubectl port-forward.*9090" 2>/dev/null || true
sleep 1

# ArgoCD — 8080 → argocd-server:443
kubectl port-forward svc/argocd-server -n argocd 8080:443 \
  --address=127.0.0.1 >/dev/null 2>&1 &
PF_ARGO=$!
echo "  ✅ ArgoCD     → https://localhost:8080  (pid $PF_ARGO)"

# Prometheus — 9090 → prometheus:9090
kubectl port-forward svc/kube-prometheus-kube-prome-prometheus -n monitoring 9090:9090 \
  --address=127.0.0.1 >/dev/null 2>&1 &
PF_PROM=$!
echo "  ✅ Prometheus → http://localhost:9090   (pid $PF_PROM)"

# Wait a moment for port-forwards to establish
sleep 2

# Verify connections
curl -sk -o /dev/null -w "  ArgoCD   HTTP status: %{http_code}\n" https://localhost:8080 || true
curl -s  -o /dev/null -w "  Prometheus HTTP status: %{http_code}\n" http://localhost:9090 || true

echo ""
echo "🚀 Launching SRE Agent..."
echo ""

# Trap to kill port-forwards on exit
cleanup() {
  echo ""
  echo "🛑 Stopping port-forwards..."
  kill $PF_ARGO $PF_PROM 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$SCRIPT_DIR"
python3 cli/cli.py "$@"
