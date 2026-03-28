# kagent deployment layout

Kubernetes manifests for running the SRE agent stack with [kagent](https://kagent.dev): in-cluster MCP servers, `agentgateway`, `RemoteMCPServer`, and optional BYO `Agent`.

## Layout

```
deploy/kagent/
├── MIGRATION_PLAN.md
├── README.md
├── base/
│   ├── kustomization.yaml
│   ├── rbac/                  # MCP Kubernetes SA + ClusterRoleBinding
│   ├── mcp/                   # MCPServer CRs
│   ├── gateway/               # agentgateway ConfigMap, Deployment, Service
│   └── integration/bundles/
│       ├── remote/            # RemoteMCPServer (sub-overlay + full stack include)
│       └── byo/               # BYO Agent (sub-overlay + full stack include)
├── overlays/
│   ├── dev/                   # Full stack (includes base)
│   ├── prod/                  # Full stack + HA gateway patch
│   ├── remote/                # RemoteMCPServer only
│   └── byo/                   # BYO Agent only
└── scripts/
    └── apply-secrets-from-env.sh
```

## Prerequisites

- kagent installed in the cluster (CRDs + controller).
- Namespace `kagent` (or set `KAGENT_NAMESPACE` when using the secrets script).
- Prometheus / Argo CD URLs in `base/mcp/servers.yaml` must match your cluster (or patch via overlay).

## Secrets

API keys and Argo CD token are not stored in git. From the repo root `sre-agent/`:

```bash
bash deploy/kagent/scripts/apply-secrets-from-env.sh
```

Re-run after changing `.env`. Override with `SRE_AGENT_ENV_FILE` / `KAGENT_NAMESPACE` if needed.

## Apply

From `sre-agent/`:

| Goal | Command |
|------|---------|
| Full stack (default dev overlay) | `make kagent-incluster` — applies `overlays/dev` |
| Full stack (prod overlay: 2× gateway, limits, anti-affinity) | `make kagent-incluster KAGENT_OVERLAY=prod` |
| RemoteMCPServer only | `make kagent-apply` |
| BYO Agent only | `make kagent-apply-byo` |
| Render without applying | `make kagent-render` or `make kagent-render KAGENT_OVERLAY=prod` |

Plain `kubectl`:

```bash
kubectl apply -k deploy/kagent                    # same as overlays/dev
kubectl apply -k deploy/kagent/overlays/dev
kubectl apply -k deploy/kagent/overlays/prod
```

## Verification

**Cluster smoke (no CLI install):**

```bash
bash deploy/kagent/scripts/smoke-kagent.sh
```

**kagent CLI** talks to the controller API (not kubectl). Install the [release binary](https://github.com/kagent-dev/kagent/releases) or `brew install kagent`, then:

```bash
# expose the controller API (default http://localhost:8083)
kubectl port-forward -n kagent svc/kagent-controller 8083:8083
```

In another terminal:

```bash
kagent --kagent-url http://localhost:8083 get agent -n kagent
kagent --kagent-url http://localhost:8083 get tool -n kagent | head
kagent --kagent-url http://localhost:8083 invoke -a k8s-agent -t "List pods in namespace kagent" -n kagent
```

`invoke` only succeeds if that agent’s **LLM backend** is configured in the cluster (many installs use Ollama; if you see an Ollama connection error, configure the provider or use an agent that points at your API keys).

**BYO agent** (`sre-agent-byo`) needs a real container image and secrets; only then:

```bash
kagent --kagent-url http://localhost:8083 invoke -a sre-agent-byo -t "List unhealthy pods" -n kagent --stream
```

## Notes

- Local gateway tuning and JWT live in `tools/agentgateway.yaml`; in-cluster gateway config is `base/gateway/configmap.yaml`.
- Production overlay patches `agentgateway` replicas and resources; tighten RBAC for `mcp-kubernetes-sa` before production.
