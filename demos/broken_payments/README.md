# Demo: Broken Payments Service

A real deployable broken scenario across all three MCPs.

## What breaks

| Layer | What happens |
|-------|-------------|
| **Kubernetes** | `payments` pods OOMKilled every ~6s → CrashLoopBackOff. `checkout` pods stay running but return 503 because payments is unreachable. |
| **Prometheus** | `PaymentsServiceDown`, `PaymentsPodOOMKilling`, `PaymentsHighRestartRate`, `CheckoutDegradedDueToPayments` alerts fire. |
| **Argo CD** | Application `payments` shows `Synced / Degraded` — the bad sync is visible in history. |

## Deploy

```bash
# 1. namespace + workloads
kubectl apply -f demos/broken_payments/k8s/

# 2. Prometheus alert rules (requires Prometheus Operator / kube-prometheus-stack)
kubectl apply -f demos/broken_payments/monitoring/

# 3. ArgoCD application (edit repoURL in application.yaml first)
kubectl apply -f demos/broken_payments/argocd/application.yaml -n argocd
```

## Watch it break

```bash
kubectl get pods -n production -w
```

You should see payments pods cycle through `Running → OOMKilled → CrashLoopBackOff` every ~6 seconds.

## Now run your agent

Point the agent at your cluster (make sure `PROMETHEUS_URL`, `ARGOCD_URL`, `ARGOCD_TOKEN` are set) and ask:

```
CRITICAL: payments-service is down in production. Pods are CrashLoopBackOff.
Investigate the root cause.
```

The agent should:
1. Use **Kubernetes MCP** — list pods, describe the crashing one, see OOMKilled + v2.3.1 image
2. Use **Prometheus MCP** — query memory metrics, confirm the leak pattern and firing alerts
3. Use **Argo CD MCP** — list apps, get history, roll back to the last healthy revision

## Teardown

```bash
kubectl delete namespace production
kubectl delete -f demos/broken_payments/argocd/application.yaml -n argocd
```
