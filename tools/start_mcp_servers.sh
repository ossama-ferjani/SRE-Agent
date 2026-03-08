#!/usr/bin/env bash
# Start all three MCP servers as background processes.
# Logs go to /tmp/mcp-*.log
# Usage: ./tools/start_mcp_servers.sh [stop]

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="/tmp/sre-mcp-pids"
mkdir -p "$PID_DIR"

stop_servers() {
    echo "Stopping MCP servers..."
    for name in k8s prometheus argocd; do
        PID_FILE="$PID_DIR/$name.pid"
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            kill "$PID" 2>/dev/null && echo "  Stopped $name (pid $PID)" || echo "  $name already stopped"
            rm -f "$PID_FILE"
        fi
    done
    exit 0
}

if [ "${1}" = "stop" ]; then
    stop_servers
fi

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

echo "Starting MCP servers..."

# Kubernetes MCP — port 3001
python3 "$SCRIPT_DIR/k8s_mcp.py" > /tmp/mcp-k8s.log 2>&1 &
echo $! > "$PID_DIR/k8s.pid"
echo "  k8s      → http://localhost:3001/mcp  (pid $!)"

# Prometheus MCP — port 3002
python3 "$SCRIPT_DIR/prometheus_mcp.py" > /tmp/mcp-prometheus.log 2>&1 &
echo $! > "$PID_DIR/prometheus.pid"
echo "  prometheus → http://localhost:3002/mcp  (pid $!)"

# Argo CD MCP — port 3003
python3 "$SCRIPT_DIR/argocd_mcp.py" > /tmp/mcp-argocd.log 2>&1 &
echo $! > "$PID_DIR/argocd.pid"
echo "  argocd   → http://localhost:3003/mcp  (pid $!)"

echo ""
echo "Waiting for servers to start..."
sleep 3

# Health check each
for port in 3001 3002 3003; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/mcp" 2>/dev/null || echo "000")
    NAME=$([ $port -eq 3001 ] && echo "k8s" || ([ $port -eq 3002 ] && echo "prometheus" || echo "argocd"))
    if [ "$STATUS" != "000" ]; then
        echo "  ✅ $NAME (:$port) → HTTP $STATUS"
    else
        echo "  ⚠️  $NAME (:$port) → not responding (check /tmp/mcp-$NAME.log)"
    fi
done

echo ""
echo "Logs: /tmp/mcp-k8s.log  /tmp/mcp-prometheus.log  /tmp/mcp-argocd.log"
echo "Stop: ./tools/start_mcp_servers.sh stop"
