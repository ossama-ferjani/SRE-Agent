#!/usr/bin/env bash
# Quick checks for in-cluster SRE stack + how to exercise the kagent API.
set -euo pipefail

NS="${KAGENT_NAMESPACE:-kagent}"

echo "=== MCPServer (stdio MCP pods) ==="
kubectl get mcpserver -n "$NS" -o wide

echo ""
echo "=== RemoteMCPServer (includes sre-agentgateway → agentgateway) ==="
kubectl get remotemcpserver -n "$NS" -o wide

echo ""
echo "=== agentgateway workload ==="
kubectl get deploy,svc -n "$NS" agentgateway 2>/dev/null || true

echo ""
echo "=== In-cluster HTTP probe (GET / often returns 406 for MCP; not 5xx is fine) ==="
POD="agw-smoke-$(date +%s)"
kubectl run -n "$NS" "$POD" --rm -i --restart=Never --image=curlimages/curl:8.5.0 -- \
  curl -sS -o /dev/null -w "HTTP %{http_code}\n" --max-time 8 \
  "http://agentgateway.${NS}.svc.cluster.local:3000/" || true

echo ""
echo "=== kagent CLI (needs API reachable) ==="
echo "Terminal A:"
echo "  kubectl port-forward -n $NS svc/kagent-controller 8083:8083"
echo "Terminal B:"
echo "  kagent --kagent-url http://localhost:8083 get agent -n $NS"
echo "  kagent --kagent-url http://localhost:8083 get tool -n $NS | head"
echo "  kagent --kagent-url http://localhost:8083 invoke -a k8s-agent -t 'Say hello' -n $NS"
echo ""
echo "Note: invoke requires a working LLM backend for that agent (e.g. Ollama or configured provider)."
