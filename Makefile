.PHONY: install run test test-memory test-registry lint format clean \
        mcp-install sqld-up sqld-down reset-memory \
        port-forward switch-model gateway run-gateway \
        kagent-apply kagent-apply-byo kagent-verify kagent-incluster kagent-secrets kagent-render kagent-smoke

# ── Setup ──────────────────────────────────────────────────────
install:
	pip3 install -r requirements.txt

# ── Run ────────────────────────────────────────────────────────
run:
	python3 -m cli.cli

run-gateway:
	MCP_GATEWAY_URL=http://localhost:3000 LLM_GATEWAY_URL=http://localhost:8080/v1 python3 -m cli.cli

model:
	MODEL=$(MODEL) python3 -m cli.cli

# ── MCP servers (community, stdio — spawned automatically by the agent) ───────
mcp-install:
	./tools/start_mcp_servers.sh

gateway:
	./tools/start_agentgateway.sh

# ── Docker sqld (networked SQLite, optional) ───────────────────
sqld-up:
	cd mcp_servers && docker compose up -d

sqld-down:
	cd mcp_servers && docker compose down

# ── Kubernetes port-forwards ───────────────────────────────────
port-forward:
	@echo "Starting port-forwards in background..."
	kubectl port-forward svc/kube-prometheus-kube-prome-prometheus \
	  -n monitoring 9090:9090 &
	kubectl port-forward svc/argocd-server -n argocd 8443:443 &
	@echo "Prometheus → http://localhost:9090"
	@echo "Argo CD    → https://localhost:8443"

# ── Testing ────────────────────────────────────────────────────
test:
	pytest tests/ -v

test-memory:
	pytest tests/test_memory.py -v

test-registry:
	pytest tests/test_registry.py -v

test-mcp:
	pytest tests/test_mcp.py -v

# ── Code quality ───────────────────────────────────────────────
lint:
	ruff check . --fix

format:
	ruff format .

# ── Cleanup ────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache

reset-memory:
	rm -f ~/.sre_agent/memory.db ~/.sre_agent/checkpoints.db
	@echo "Memory wiped."

# ── Helpers ────────────────────────────────────────────────────
switch-model:
	@echo "Edit models/config.yaml → active.provider and active.model"
	@echo "Then restart: make run"
	@echo ""
	@echo "Or set env var at runtime:  MODEL=openai/gpt-4o make run"
	@echo "Or use CLI command:         /model openai/gpt-4o"

# ── kagent migration helpers ───────────────────────────────────
# Overlays: remote | byo | dev | prod  (default for full stack: dev)
KAGENT_OVERLAY ?= dev

kagent-apply:
	kubectl apply -k deploy/kagent/overlays/remote

kagent-apply-byo:
	kubectl apply -k deploy/kagent/overlays/byo

kagent-verify:
	kagent get agent
	kagent get session

kagent-smoke:
	bash deploy/kagent/scripts/smoke-kagent.sh

# Load keys from .env into kagent namespace (run before or after kagent-incluster).
kagent-secrets:
	bash deploy/kagent/scripts/apply-secrets-from-env.sh

# Full in-cluster stack (MCP + agentgateway + RemoteMCPServer + BYO). Use KAGENT_OVERLAY=prod for HA gateway.
kagent-incluster:
	kubectl apply -k deploy/kagent/overlays/$(KAGENT_OVERLAY)

# Render manifests to stdout (e.g. make kagent-render KAGENT_OVERLAY=prod)
kagent-render:
	kubectl kustomize deploy/kagent/overlays/$(KAGENT_OVERLAY)
