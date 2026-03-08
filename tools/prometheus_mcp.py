"""Prometheus MCP server — exposes PromQL and alert tools via FastMCP streamable-HTTP.

Run: python3 tools/prometheus_mcp.py
Listens on: http://localhost:3002/mcp
"""

from __future__ import annotations

import json
import os
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

mcp = FastMCP("prometheus", host="0.0.0.0", port=3002)


def _get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the Prometheus HTTP API."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.reason}", "data": {}}
    except requests.exceptions.RequestException as e:
        return {"error": f"Connection error: {e}", "data": {}}


@mcp.tool()
def query(promql: str, time: str = "") -> str:
    """Run an instant PromQL query. Returns the result vector."""
    params = {"query": promql}
    if time:
        params["time"] = time
    data = _get("/api/v1/query", params)
    return json.dumps(data.get("data", {}), default=str)


@mcp.tool()
def query_range(promql: str, start: str, end: str, step: str = "60s") -> str:
    """Run a range PromQL query. start/end are Unix timestamps or RFC3339."""
    data = _get("/api/v1/query_range", {"query": promql, "start": start, "end": end, "step": step})
    return json.dumps(data.get("data", {}), default=str)


@mcp.tool()
def get_alerts() -> str:
    """Get all currently firing alerts."""
    data = _get("/api/v1/alerts")
    alerts = data.get("data", {}).get("alerts", [])
    result = [
        {
            "name": a.get("labels", {}).get("alertname"),
            "state": a.get("state"),
            "severity": a.get("labels", {}).get("severity"),
            "summary": a.get("annotations", {}).get("summary", ""),
            "labels": a.get("labels", {}),
            "active_at": a.get("activeAt"),
        }
        for a in alerts
    ]
    return json.dumps({"alerts": result, "count": len(result)})


@mcp.tool()
def get_alert_rules() -> str:
    """Get all configured alerting rules and their current state."""
    data = _get("/api/v1/rules", {"type": "alert"})
    groups = data.get("data", {}).get("groups", [])
    result = []
    for g in groups:
        for r in g.get("rules", []):
            result.append({
                "group": g["name"],
                "name": r.get("name"),
                "state": r.get("state"),
                "query": r.get("query"),
                "severity": r.get("labels", {}).get("severity"),
                "annotations": r.get("annotations", {}),
            })
    return json.dumps({"rules": result, "count": len(result)})


@mcp.tool()
def get_targets() -> str:
    """Get all scrape targets and their health status."""
    data = _get("/api/v1/targets")
    active = data.get("data", {}).get("activeTargets", [])
    result = [
        {
            "job": t.get("labels", {}).get("job"),
            "instance": t.get("labels", {}).get("instance"),
            "health": t.get("health"),
            "last_scrape": t.get("lastScrape"),
            "last_error": t.get("lastError", ""),
        }
        for t in active
    ]
    return json.dumps({"targets": result, "count": len(result)})


@mcp.tool()
def get_metric_metadata(metric: str = "") -> str:
    """Get metadata (type, help text) for metrics. Leave metric blank to list all."""
    params = {}
    if metric:
        params["metric"] = metric
    data = _get("/api/v1/metadata", params)
    return json.dumps(data.get("data", {}), default=str)


@mcp.tool()
def label_values(label_name: str, match: str = "") -> str:
    """Get all values for a given label name (e.g. 'job', 'namespace')."""
    params = {}
    if match:
        params["match[]"] = match
    data = _get(f"/api/v1/label/{label_name}/values", params)
    return json.dumps({"values": data.get("data", [])})


@mcp.tool()
def get_tsdb_status() -> str:
    """Get TSDB head stats — series count, chunk count, memory usage."""
    data = _get("/api/v1/status/tsdb")
    return json.dumps(data.get("data", {}), default=str)


@mcp.tool()
def get_runtime_info() -> str:
    """Get Prometheus runtime info — version, uptime, storage retention."""
    data = _get("/api/v1/status/runtimeinfo")
    return json.dumps(data.get("data", {}), default=str)


if __name__ == "__main__":
    print(f"Starting Prometheus MCP server on http://0.0.0.0:3002/mcp")
    print(f"Connecting to Prometheus at: {PROMETHEUS_URL}")
    mcp.run(transport="streamable-http")
