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

    # Build server configs for the client
    server_configs: dict[str, dict] = {}
    for name, cfg in servers.items():
        url = expand_env_vars(cfg.get("url", ""))
        transport = cfg.get("transport", "streamable_http")
        server_configs[name] = {
            "url": url,
            "transport": transport,
        }

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
            url = cfg.get("url", "unknown")
            status[name] = f"unreachable: {exc}"
            logger.warning("MCP server '%s' unreachable at %s: %s", name, url, exc)

    return all_tools, status


def load_mcp_tools_sync(
    server_names: list[str] | None = None,
) -> tuple[list[BaseTool], dict[str, str]]:
    """Synchronous wrapper around load_mcp_tools_async.

    Handles the case where an event loop is already running via nest_asyncio.
    """
    try:
        loop = asyncio.get_running_loop()
        # Event loop already running — use nest_asyncio
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
        return asyncio.run(load_mcp_tools_async(server_names))
    except RuntimeError:
        # No event loop running — safe to use asyncio.run()
        return asyncio.run(load_mcp_tools_async(server_names))
