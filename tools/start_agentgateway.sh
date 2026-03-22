#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Load project env vars (API keys, endpoints) for gateway runtime.
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if ! command -v agentgateway >/dev/null 2>&1; then
  echo "agentgateway not found. Installing..."
  curl -sL https://agentgateway.dev/install | bash
fi

echo "Starting MCP servers bootstrap script..."
./tools/start_mcp_servers.sh &
MCP_BOOTSTRAP_PID=$!

wait_for_port() {
  local port="$1"
  local timeout=15
  local elapsed=0

  while [ "${elapsed}" -lt "${timeout}" ]; do
    if command -v nc >/dev/null 2>&1; then
      if nc -z localhost "${port}" >/dev/null 2>&1; then
        echo "Port ${port} is ready."
        return 0
      fi
    else
      if curl -fsS "http://localhost:${port}" >/dev/null 2>&1; then
        echo "Port ${port} is ready."
        return 0
      fi
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "Warning: port ${port} did not become ready within ${timeout}s."
  return 1
}

wait_for_port 3001 || true
wait_for_port 3002 || true
wait_for_port 3003 || true

if ps -p "${MCP_BOOTSTRAP_PID}" >/dev/null 2>&1; then
  wait "${MCP_BOOTSTRAP_PID}" || true
fi

echo "Agentgateway UI: http://localhost:15000/ui"
exec agentgateway -f tools/agentgateway.yaml
