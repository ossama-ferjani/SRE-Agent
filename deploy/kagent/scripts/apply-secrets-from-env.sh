#!/usr/bin/env bash
# Load API keys and Argo CD token from .env into Kubernetes secrets (namespace kagent).
# Does not print secret values. Requires kubectl and a default context.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SRE_AGENT_ENV_FILE:-$SCRIPT_DIR/../../../.env}"
NS="${KAGENT_NAMESPACE:-kagent}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE (set SRE_AGENT_ENV_FILE to override)" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

kubectl create secret generic mcp-argocd-auth -n "$NS" \
  --from-literal=ARGOCD_API_TOKEN="${ARGOCD_TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic sre-agent-secrets -n "$NS" \
  --from-literal=OPENAI_COMPAT_API_KEY="${OPENAI_COMPAT_API_KEY}" \
  --from-literal=GOOGLE_API_KEY="${GOOGLE_API_KEY}" \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

# MCPServer v1alpha1 only supports plain env strings; mirror token into the MCPServer spec.
kubectl patch mcpserver mcp-argocd -n "$NS" --type merge -p "$(python3 -c "
import json, os
t = os.environ['ARGOCD_TOKEN']
print(json.dumps({'spec': {'deployment': {'env': {
  'ARGOCD_BASE_URL': 'https://argocd-server.argocd.svc.cluster.local',
  'NODE_TLS_REJECT_UNAUTHORIZED': '0',
  'ARGOCD_API_TOKEN': t,
}}}}))
")"

echo "Applied secrets in namespace $NS and patched mcpserver/mcp-argocd."
