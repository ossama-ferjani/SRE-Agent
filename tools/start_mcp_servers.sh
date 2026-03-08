#!/usr/bin/env bash
# Install community MCP servers used by the SRE agent.
# MCP servers now run as stdio subprocesses — no ports, no background processes needed.
# The agent spawns them automatically on startup.
#
# Usage: ./tools/start_mcp_servers.sh

set -e

echo "Installing community MCP servers..."

echo "  [1/2] npm: mcp-server-kubernetes"
npm install -g mcp-server-kubernetes

echo "  [2/2] pip: prometheus-mcp-server"
pip install prometheus-mcp-server

echo ""
echo "  argocd-mcp runs via npx — no install needed."
echo ""
echo "Done. Start the agent with: make run"
