"""Kubernetes MCP server — exposes k8s cluster tools via FastMCP streamable-HTTP.

Run: python3 tools/k8s_mcp.py
Listens on: http://localhost:3001/mcp
"""

from __future__ import annotations

import json
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kubernetes", host="0.0.0.0", port=3001)


def _k8s_clients():
    """Return (CoreV1Api, AppsV1Api, BatchV1Api, client) loaded from kubeconfig."""
    from kubernetes import client, config
    config.load_kube_config()
    core = client.CoreV1Api()
    apps = client.AppsV1Api()
    batch = client.BatchV1Api()
    events = client.CoreV1Api()
    return core, apps, batch, events


@mcp.tool()
def list_namespaces() -> str:
    """List all namespaces in the cluster."""
    core, _, _, _ = _k8s_clients()
    ns_list = core.list_namespace()
    names = [ns.metadata.name for ns in ns_list.items]
    return json.dumps({"namespaces": names})


@mcp.tool()
def list_pods(namespace: str = "default", label_selector: str = "") -> str:
    """List pods in a namespace, optionally filtered by label selector."""
    core, _, _, _ = _k8s_clients()
    kwargs = {}
    if label_selector:
        kwargs["label_selector"] = label_selector
    pods = core.list_namespaced_pod(namespace, **kwargs)
    result = []
    for p in pods.items:
        result.append({
            "name": p.metadata.name,
            "namespace": p.metadata.namespace,
            "phase": p.status.phase,
            "ready": all(
                c.ready for c in (p.status.container_statuses or [])
            ),
            "restarts": sum(
                c.restart_count for c in (p.status.container_statuses or [])
            ),
            "node": p.spec.node_name,
            "age": str(p.metadata.creation_timestamp),
        })
    return json.dumps({"pods": result, "count": len(result)})


@mcp.tool()
def get_pod_logs(name: str, namespace: str = "default", tail_lines: int = 100, container: str = "") -> str:
    """Get logs from a pod (last N lines)."""
    core, _, _, _ = _k8s_clients()
    kwargs = {"tail_lines": tail_lines}
    if container:
        kwargs["container"] = container
    try:
        logs = core.read_namespaced_pod_log(name, namespace, **kwargs)
        return logs
    except Exception as exc:
        return f"Error getting logs: {exc}"


@mcp.tool()
def describe_pod(name: str, namespace: str = "default") -> str:
    """Get full details of a pod including events and container states."""
    core, _, _, _ = _k8s_clients()
    pod = core.read_namespaced_pod(name, namespace)
    containers = []
    for c in (pod.status.container_statuses or []):
        state = {}
        if c.state.running:
            state = {"running": True, "started_at": str(c.state.running.started_at)}
        elif c.state.waiting:
            state = {"waiting": True, "reason": c.state.waiting.reason, "message": c.state.waiting.message}
        elif c.state.terminated:
            state = {"terminated": True, "exit_code": c.state.terminated.exit_code, "reason": c.state.terminated.reason}
        containers.append({
            "name": c.name,
            "ready": c.ready,
            "restarts": c.restart_count,
            "image": c.image,
            "state": state,
        })
    return json.dumps({
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": pod.status.phase,
        "node": pod.spec.node_name,
        "labels": pod.metadata.labels or {},
        "containers": containers,
        "conditions": [{"type": c.type, "status": c.status, "reason": c.reason} for c in (pod.status.conditions or [])],
    }, default=str)


@mcp.tool()
def list_deployments(namespace: str = "default") -> str:
    """List deployments in a namespace."""
    _, apps, _, _ = _k8s_clients()
    deps = apps.list_namespaced_deployment(namespace)
    result = []
    for d in deps.items:
        result.append({
            "name": d.metadata.name,
            "namespace": d.metadata.namespace,
            "desired": d.spec.replicas,
            "ready": d.status.ready_replicas or 0,
            "available": d.status.available_replicas or 0,
            "image": d.spec.template.spec.containers[0].image if d.spec.template.spec.containers else "",
        })
    return json.dumps({"deployments": result})


@mcp.tool()
def scale_deployment(name: str, replicas: int, namespace: str = "default") -> str:
    """Scale a deployment to the specified number of replicas."""
    from kubernetes import client
    _, apps, _, _ = _k8s_clients()
    body = {"spec": {"replicas": replicas}}
    apps.patch_namespaced_deployment_scale(name, namespace, body)
    return json.dumps({"scaled": True, "deployment": name, "replicas": replicas})


@mcp.tool()
def restart_deployment(name: str, namespace: str = "default") -> str:
    """Restart a deployment by patching its pod template annotation."""
    from kubernetes import client
    import datetime
    _, apps, _, _ = _k8s_clients()
    now = datetime.datetime.utcnow().isoformat()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                }
            }
        }
    }
    apps.patch_namespaced_deployment(name, namespace, body)
    return json.dumps({"restarted": True, "deployment": name})


@mcp.tool()
def list_services(namespace: str = "default") -> str:
    """List services in a namespace."""
    core, _, _, _ = _k8s_clients()
    svcs = core.list_namespaced_service(namespace)
    result = [
        {
            "name": s.metadata.name,
            "type": s.spec.type,
            "cluster_ip": s.spec.cluster_ip,
            "ports": [{"port": p.port, "protocol": p.protocol} for p in (s.spec.ports or [])],
        }
        for s in svcs.items
    ]
    return json.dumps({"services": result})


@mcp.tool()
def get_events(namespace: str = "default", field_selector: str = "") -> str:
    """Get cluster events, optionally filtered (e.g. type=Warning)."""
    core, _, _, _ = _k8s_clients()
    kwargs = {}
    if field_selector:
        kwargs["field_selector"] = field_selector
    evts = core.list_namespaced_event(namespace, **kwargs)
    result = [
        {
            "type": e.type,
            "reason": e.reason,
            "message": e.message,
            "object": f"{e.involved_object.kind}/{e.involved_object.name}",
            "count": e.count,
            "last_time": str(e.last_timestamp),
        }
        for e in sorted(evts.items, key=lambda x: x.last_timestamp or x.event_time or "", reverse=True)[:50]
    ]
    return json.dumps({"events": result})


@mcp.tool()
def get_node_status() -> str:
    """Get status and resource info for all cluster nodes."""
    core, _, _, _ = _k8s_clients()
    nodes = core.list_node()
    result = []
    for n in nodes.items:
        conditions = {c.type: c.status for c in (n.status.conditions or [])}
        result.append({
            "name": n.metadata.name,
            "ready": conditions.get("Ready") == "True",
            "cpu": n.status.capacity.get("cpu"),
            "memory": n.status.capacity.get("memory"),
            "k8s_version": n.status.node_info.kubelet_version,
        })
    return json.dumps({"nodes": result})


@mcp.tool()
def delete_pod(name: str, namespace: str = "default") -> str:
    """Delete (restart) a pod by name — the controller will recreate it."""
    core, _, _, _ = _k8s_clients()
    core.delete_namespaced_pod(name, namespace)
    return json.dumps({"deleted": True, "pod": name, "namespace": namespace})


if __name__ == "__main__":
    print("Starting Kubernetes MCP server on http://0.0.0.0:3001/mcp")
    mcp.run(transport="streamable-http")
