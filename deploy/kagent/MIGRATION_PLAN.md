# kagent migration — what was done

The following was added so the SRE stack can run under kagent in Kubernetes alongside the existing local LangGraph CLI path.

## Repository layout (`deploy/kagent/`)

- **Kustomize**: `base/` holds split manifests; `overlays/dev` applies the full in-cluster stack; `overlays/prod` adds HA and resource limits for `agentgateway`; `overlays/remote` and `overlays/byo` apply only the `RemoteMCPServer` or only the BYO `Agent`. Root `kustomization.yaml` aliases `overlays/dev`.
- **`base/rbac/`**: ServiceAccount and ClusterRoleBinding so the Kubernetes MCP server can use the cluster API (`mcp-kubernetes-sa`).
- **`base/mcp/`**: Three `MCPServer` resources — `mcp-kubernetes`, `mcp-prometheus`, `mcp-argocd` — with in-cluster URLs for Prometheus and Argo CD. The Argo CD API token is not in git; it is applied via `scripts/apply-secrets-from-env.sh` (reads `.env`, creates `mcp-argocd-auth` and `sre-agent-secrets`, patches `mcp-argocd` env because the CRD only supports plain `env` strings).
- **`base/gateway/`**: `ConfigMap` with `agentgateway` config (MCP fan-out to the three `MCPServer` services on port 3000, path `/mcp`), `Deployment`, and `Service` for in-cluster `agentgateway` (`ghcr.io/agentgateway/agentgateway:0.9.0-musl`).
- **`base/integration/bundles/`**: `remote/` — `RemoteMCPServer` `sre-agentgateway` pointing at the in-cluster gateway (use URL ending in `/mcp` so kagent can reconcile tools; short DNS `http://agentgateway.kagent.svc.cluster.local:3000/mcp` matches what was validated in-cluster). `byo/` — `Agent` `sre-agent-byo` (BYO) with env for gateway URLs and `secretKeyRef` to `sre-agent-secrets`; image remains a placeholder until you build and push a real image.
- **`scripts/apply-secrets-from-env.sh`**: Loads keys from `sre-agent/.env` into Kubernetes secrets and patches Argo MCP.
- **`scripts/smoke-kagent.sh`**: Cluster checks (MCPServer, RemoteMCPServer, `agentgateway`, HTTP probe).

## Local dev tooling (unchanged path, documented for parity)

- **`tools/agentgateway.yaml`**: Local gateway config with optional JWT auth, `mcpAuthorization` allowlist, and OpenTelemetry tracing env hooks — used with `make gateway` / `make run-gateway`, not the in-cluster `ConfigMap` unless you copy settings manually.

## Makefile

- `make kagent-incluster` — `kubectl apply -k deploy/kagent/overlays/$(KAGENT_OVERLAY)` (default `dev`).
- `make kagent-apply` — remote overlay only; `make kagent-apply-byo` — BYO only; `make kagent-secrets` — secrets script; `make kagent-smoke` — smoke script; `make kagent-render` — render manifests.

## Cluster prerequisites (Helm / runtime, not in this repo’s apply)

- kagent installed (CRDs, controller, bundled agents such as `k8s-agent`).
- **`ModelConfig` `default-model-config`** in the cluster must point at an LLM you can reach from agent pods (the chart default targets Ollama on `host.docker.internal:11434`). Adjust provider, model, and secrets to match your keys.
- Optional: **`deploy/kagent/base/ollama/ollama.yaml`** — Ollama `Deployment` + `Service` in `kagent` if you deploy an in-cluster model server (apply on its own; pull a model inside the pod, e.g. `llama3.2`).
