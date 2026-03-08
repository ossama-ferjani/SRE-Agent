"""Argo CD MCP server — exposes app sync/rollback/status tools via FastMCP streamable-HTTP.

Run: python3 tools/argocd_mcp.py
Listens on: http://localhost:3003/mcp
"""

from __future__ import annotations

import json
import os
import warnings

import requests
import urllib3
from mcp.server.fastmcp import FastMCP

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ARGOCD_URL = os.environ.get("ARGOCD_URL", "https://localhost:8080")
ARGOCD_TOKEN = os.environ.get("ARGOCD_TOKEN", "")

mcp = FastMCP("argocd", host="0.0.0.0", port=3003)


def _headers() -> dict:
    return {"Authorization": f"Bearer {ARGOCD_TOKEN}", "Content-Type": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    try:
        resp = requests.get(f"{ARGOCD_URL}{path}", headers=_headers(), params=params, verify=False, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        # Return error as a dict instead of raising
        return {"error": f"HTTP {e.response.status_code}: {e.response.reason}", "items": [], "history": []}
    except requests.exceptions.RequestException as e:
        return {"error": f"Connection error: {e}", "items": [], "history": []}


def _post(path: str, body: dict | None = None) -> dict:
    try:
        resp = requests.post(f"{ARGOCD_URL}{path}", headers=_headers(), json=body or {}, verify=False, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.reason}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Connection error: {e}"}


@mcp.tool()
def list_apps(project: str = "") -> str:
    """List all Argo CD applications and their sync/health status."""
    params = {}
    if project:
        params["project"] = project
    data = _get("/api/v1/applications", params)
    apps = data.get("items") or []
    result = [
        {
            "name": a["metadata"]["name"],
            "project": a["spec"].get("project", "default"),
            "repo": a["spec"]["source"].get("repoURL", ""),
            "path": a["spec"]["source"].get("path", ""),
            "target_revision": a["spec"]["source"].get("targetRevision", "HEAD"),
            "destination_namespace": a["spec"]["destination"].get("namespace", ""),
            "sync_status": a["status"].get("sync", {}).get("status"),
            "health_status": a["status"].get("health", {}).get("status"),
            "last_synced": a["status"].get("operationState", {}).get("finishedAt", ""),
        }
        for a in apps
    ]
    return json.dumps({"apps": result, "count": len(result)})


@mcp.tool()
def get_app(name: str) -> str:
    """Get full details for an Argo CD application."""
    data = _get(f"/api/v1/applications/{name}")
    if "error" in data:
        return json.dumps({"error": data["error"]})
    status = data.get("status", {})
    return json.dumps({
        "name": data["metadata"]["name"],
        "project": data["spec"].get("project"),
        "source": data["spec"].get("source", {}),
        "destination": data["spec"].get("destination", {}),
        "sync_status": status.get("sync", {}).get("status"),
        "sync_revision": status.get("sync", {}).get("revision"),
        "health_status": status.get("health", {}).get("status"),
        "conditions": status.get("conditions", []),
        "resources": [
            {
                "kind": r.get("kind"),
                "name": r.get("name"),
                "namespace": r.get("namespace"),
                "sync_status": r.get("status"),
                "health": r.get("health", {}).get("status"),
            }
            for r in status.get("resources", [])
        ],
    }, default=str)


@mcp.tool()
def sync_app(name: str, revision: str = "", prune: bool = False) -> str:
    """Trigger a sync for an Argo CD application."""
    body: dict = {}
    if revision:
        body["revision"] = revision
    if prune:
        body["prune"] = True
    data = _post(f"/api/v1/applications/{name}/sync", body)
    if "error" in data:
        return json.dumps({"error": data["error"]})
    op = data.get("status", {}).get("operationState", {})
    return json.dumps({
        "synced": True,
        "app": name,
        "phase": op.get("phase"),
        "message": op.get("message", ""),
    }, default=str)


@mcp.tool()
def rollback_app(name: str, revision_id: int) -> str:
    """Rollback an application to a specific history revision id."""
    data = _post(f"/api/v1/applications/{name}/rollback", {"id": revision_id})
    if "error" in data:
        return json.dumps({"error": data["error"]})
    return json.dumps({"rolledBack": True, "app": name, "revision_id": revision_id}, default=str)


@mcp.tool()
def get_app_history(name: str) -> str:
    """Get deployment history for an application."""
    data = _get(f"/api/v1/applications/{name}/revisions")
    if "error" in data:
        return json.dumps({"error": data["error"], "history": []})
    history = data.get("items") or data.get("history") or []
    result = [
        {
            "id": h.get("id"),
            "revision": h.get("revision"),
            "deployed_at": h.get("deployedAt"),
            "source": h.get("source", {}),
        }
        for h in history
    ]
    return json.dumps({"history": result})


@mcp.tool()
def get_app_logs(name: str, namespace: str = "", container: str = "", group: str = "", kind: str = "Pod", resource_name: str = "") -> str:
    """Get logs for a resource managed by an Argo CD app."""
    params = {"namespace": namespace or "", "container": container}
    if group:
        params["group"] = group
    if kind:
        params["kind"] = kind
    if resource_name:
        params["resourceName"] = resource_name
    try:
        data = _get(f"/api/v1/applications/{name}/logs", params)
        entries = data.get("result", {}).get("content", "") or str(data)
        return entries[:5000]
    except Exception as exc:
        return f"Error fetching logs: {exc}"


@mcp.tool()
def list_projects() -> str:
    """List all Argo CD projects."""
    data = _get("/api/v1/projects")
    projects = data.get("items") or []
    return json.dumps({
        "projects": [
            {
                "name": p["metadata"]["name"],
                "description": p["spec"].get("description", ""),
                "source_repos": p["spec"].get("sourceRepos", []),
            }
            for p in projects
        ]
    })


@mcp.tool()
def get_cluster_info() -> str:
    """List registered clusters in Argo CD."""
    data = _get("/api/v1/clusters")
    clusters = data.get("items") or []
    return json.dumps({
        "clusters": [
            {
                "name": c.get("name"),
                "server": c.get("server"),
                "connection_state": c.get("connectionState", {}).get("status"),
            }
            for c in clusters
        ]
    })


if __name__ == "__main__":
    print(f"Starting Argo CD MCP server on http://0.0.0.0:3003/mcp")
    print(f"Connecting to Argo CD at: {ARGOCD_URL}")
    mcp.run(transport="streamable-http")
