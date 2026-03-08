.PHONY: install run test test-memory test-registry lint format clean \
        mcp-start mcp-stop mcp-logs sqld-up sqld-down reset-memory \
        port-forward switch-model

# ── Setup ──────────────────────────────────────────────────────
install:
	pip3 install -r requirements.txt

# ── Run ────────────────────────────────────────────────────────
run:
	python3 -m cli.cli

model:
	MODEL=$(MODEL) python3 -m cli.cli

# ── MCP servers (Python, run locally) ─────────────────────────
mcp-start:
	./tools/start_mcp_servers.sh

mcp-stop:
	./tools/start_mcp_servers.sh stop

mcp-logs:
	@echo "=== Kubernetes MCP ===" && tail -30 /tmp/mcp-k8s.log || true
	@echo "=== Prometheus MCP ===" && tail -30 /tmp/mcp-prometheus.log || true
	@echo "=== Argo CD MCP    ===" && tail -30 /tmp/mcp-argocd.log || true

# ── Docker sqld (networked SQLite, optional) ───────────────────
sqld-up:
	cd mcp_servers && docker compose up -d

sqld-down:
	cd mcp_servers && docker compose down

# ── Kubernetes port-forwards ───────────────────────────────────
port-forward:
	@echo "Starting port-forwards in background..."
	kubectl port-forward svc/prometheus-kube-prometheus-kube-prome-prometheus \
	  -n monitoring 9090:9090 &
	kubectl port-forward svc/argocd-server -n argocd 8080:443 &
	@echo "Prometheus → http://localhost:9090"
	@echo "Argo CD    → https://localhost:8080"

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
