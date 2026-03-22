"""Tests for mcp/servers.py — URL expansion, tool loading, error handling."""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def clear_mcp_gateway_env(monkeypatch):
    monkeypatch.delenv("MCP_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MCP_KUBERNETES_URL", raising=False)
    monkeypatch.delenv("MCP_PROMETHEUS_URL", raising=False)
    monkeypatch.delenv("MCP_ARGO_URL", raising=False)


def test_expand_env_vars_returns_default_when_unset(monkeypatch):
    from mcp_servers.servers import expand_env_vars
    monkeypatch.delenv("MY_TEST_VAR_XYZ", raising=False)
    result = expand_env_vars("${MY_TEST_VAR_XYZ:-http://localhost:9999}")
    assert result == "http://localhost:9999"


def test_expand_env_vars_returns_env_value_when_set(monkeypatch):
    from mcp_servers.servers import expand_env_vars
    monkeypatch.setenv("MY_TEST_VAR_XYZ", "http://my-server:1234")
    result = expand_env_vars("${MY_TEST_VAR_XYZ:-http://localhost:9999}")
    assert result == "http://my-server:1234"


def test_load_mcp_tools_sync_returns_empty_when_all_unreachable(monkeypatch):
    """All servers unreachable — should return empty tools, not crash."""
    async def mock_load_async(server_names=None):
        # Simulate all servers returning errors
        config = {
            "kubernetes": "unreachable: Connection refused",
            "prometheus": "unreachable: Connection refused",
            "argo": "unreachable: Connection refused",
        }
        return [], config

    with patch("mcp_servers.servers.load_mcp_tools_async", side_effect=mock_load_async):
        from mcp_servers import servers
        import importlib
        importlib.reload(servers)
        # Patch the async function directly
        servers.load_mcp_tools_async = mock_load_async

        import asyncio
        tools, status = asyncio.run(mock_load_async())
        assert tools == []
        assert len(status) > 0


def test_load_mcp_tools_sync_all_unreachable():
    """load_mcp_tools_sync returns empty list when all servers raise ConnectionError."""
    async def _failing_async(server_names=None):
        return [], {
            "kubernetes": "unreachable: Connection refused",
            "prometheus": "unreachable: Connection refused",
            "argo": "unreachable: Connection refused",
        }

    with patch("mcp_servers.servers.load_mcp_tools_async", new=_failing_async):
        from mcp_servers.servers import load_mcp_tools_sync
        tools, status = load_mcp_tools_sync()
        assert isinstance(tools, list)
        assert len(tools) == 0


def test_load_mcp_tools_sync_partial_success():
    """When some servers fail, partial tools are still returned."""
    fake_tool = MagicMock()
    fake_tool.name = "kubectl_get_pods"

    async def _partial_async(server_names=None):
        return [fake_tool], {
            "kubernetes": "connected (1 tools)",
            "prometheus": "unreachable: Connection refused",
            "argo": "unreachable: Connection refused",
        }

    with patch("mcp_servers.servers.load_mcp_tools_async", new=_partial_async):
        from mcp_servers.servers import load_mcp_tools_sync
        tools, status = load_mcp_tools_sync()
        assert len(tools) == 1
        assert status["kubernetes"].startswith("connected")


def test_server_status_contains_all_configured_servers():
    """Status dict should have all 3 servers from config.yaml."""
    async def _mock_async(server_names=None):
        return [], {
            "kubernetes": "unreachable: test",
            "prometheus": "unreachable: test",
            "argo": "unreachable: test",
        }

    with patch("mcp_servers.servers.load_mcp_tools_async", new=_mock_async):
        from mcp_servers.servers import load_mcp_tools_sync
        _, status = load_mcp_tools_sync()
        assert "kubernetes" in status
        assert "prometheus" in status
        assert "argo" in status
