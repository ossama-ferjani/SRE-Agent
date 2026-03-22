"""MCP server connection management — loads tools from all configured servers.

Provides both async and sync interfaces. Gracefully handles unreachable servers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def expand_env_vars(url: str) -> str:
    """Expand ${VAR:-default} patterns in a URL string using os.environ."""
    pattern = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default_val = match.group(2) or ""
        return os.environ.get(var_name, default_val)

    return pattern.sub(replacer, url)


def _load_config() -> dict[str, Any]:
    """Load and return the mcp/config.yaml as a dict."""
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_server_descriptions() -> str:
    """Return a markdown list of server names and descriptions from config."""
    config = _load_config()
    servers = config.get("servers", {})
    lines = []
    for name, cfg in servers.items():
        desc = cfg.get("description", "")
        lines.append(f"- **{name}**: {desc}")
    return "\n".join(lines)


async def load_mcp_tools_async(
    server_names: list[str] | None = None,
) -> tuple[list[BaseTool], dict[str, str]]:
    """Connect to MCP servers and return (tools_list, status_dict).

    Unreachable servers are logged as warnings but do not crash.
    """
    config = _load_config()
    servers = config.get("servers", {})

    if server_names:
        servers = {k: v for k, v in servers.items() if k in server_names}

    all_tools: list[BaseTool] = []
    status: dict[str, str] = {}

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.error(
            "langchain-mcp-adapters not installed. Run: pip install langchain-mcp-adapters"
        )
        for name in servers:
            status[name] = "error: langchain-mcp-adapters not installed"
        return [], status

    # Optional gateway mode:
    # - If MCP_GATEWAY_URL is set, try loading all tools through one federated endpoint.
    # - If gateway connection fails, gracefully fall back to direct server config.
    gateway_url = os.environ.get("MCP_GATEWAY_URL", "").strip()
    if gateway_url:
        gateway_cfg = {
            "agentgateway": {
                "url": gateway_url,
                "transport": "streamable_http",
            }
        }
        try:
            client = MultiServerMCPClient(gateway_cfg)
            tools = await client.get_tools()
            shared_status = f"connected via gateway ({len(tools)} tools)"
            for name in servers:
                status[name] = shared_status
            status["agentgateway"] = f"connected ({len(tools)} tools)"
            logger.info("MCP gateway '%s': connected with %d tools", gateway_url, len(tools))
            return tools, status
        except Exception as exc:
            logger.warning(
                "MCP gateway '%s' unreachable (%s). Falling back to direct MCP servers.",
                gateway_url,
                exc,
            )

    # Direct HTTP mode (ports 3001/3002/3003 by default):
    # try explicit MCP endpoints first, then fall back to config.yaml (stdio).
    direct_http_configs = {
        "kubernetes": {
            "url": os.environ.get("MCP_KUBERNETES_URL", "http://localhost:3001"),
            "transport": "streamable_http",
        },
        "prometheus": {
            "url": os.environ.get("MCP_PROMETHEUS_URL", "http://localhost:3002"),
            "transport": "streamable_http",
        },
        "argo": {
            "url": os.environ.get("MCP_ARGO_URL", "http://localhost:3003"),
            "transport": "streamable_http",
        },
    }
    if server_names:
        direct_http_configs = {
            k: v for k, v in direct_http_configs.items() if k in server_names
        }
    try:
        direct_client = MultiServerMCPClient(direct_http_configs)
        direct_tools = await direct_client.get_tools()
        for name in direct_http_configs:
            status[name] = f"connected ({len(direct_tools)} tools via direct MCP)"
        logger.info("Direct MCP servers connected with %d tools", len(direct_tools))
        return direct_tools, status
    except Exception as exc:
        logger.warning(
            "Direct MCP endpoints unavailable (%s). Falling back to configured MCP transports.",
            exc,
        )

    # Build server configs for the client
    server_configs: dict[str, dict] = {}
    for name, cfg in servers.items():
        transport = cfg.get("transport", "streamable_http")
        if transport == "stdio":
            entry: dict = {
                "transport": "stdio",
                "command": cfg["command"],
                "args": cfg.get("args", []),
            }
            # Inherit the full process environment (preserves PATH, HOME, etc.)
            # then overlay any server-specific env vars from config.
            raw_env = cfg.get("env", {})
            entry["env"] = {**os.environ, **{k: expand_env_vars(v) for k, v in raw_env.items()}}
        else:
            entry = {
                "url": expand_env_vars(cfg.get("url", "")),
                "transport": transport,
            }
        server_configs[name] = entry

    # Connect to each server individually to handle failures gracefully.
    # langchain-mcp-adapters >=0.1.0 dropped context-manager support;
    # use client.get_tools() directly instead of async with.
    for name, cfg in server_configs.items():
        try:
            client = MultiServerMCPClient({name: cfg})
            tools = await client.get_tools()
            all_tools.extend(tools)
            status[name] = f"connected ({len(tools)} tools)"
            logger.info("MCP server '%s': connected with %d tools", name, len(tools))
        except Exception as exc:
            label = cfg.get("url") or cfg.get("command", "unknown")
            status[name] = f"unreachable: {exc}"
            logger.warning("MCP server '%s' unreachable (%s): %s", name, label, exc)

    return all_tools, status


def load_mcp_tools_sync(
    server_names: list[str] | None = None,
) -> tuple[list[BaseTool], dict[str, str]]:
    """Synchronous wrapper around load_mcp_tools_async.

    Handles the case where an event loop is already running via nest_asyncio.
    """
    try:
        loop = asyncio.get_running_loop()
        # Event loop already running — use nest_asyncio to re-enter the same loop
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            logger.warning("nest_asyncio not installed; using new thread for async execution")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run, load_mcp_tools_async(server_names)
                )
                return future.result()
        # Run on the *existing* loop (not a new one) to avoid "bound to different loop" errors
        return loop.run_until_complete(load_mcp_tools_async(server_names))
    except RuntimeError:
        # No event loop running — safe to use asyncio.run()
        return asyncio.run(load_mcp_tools_async(server_names))
