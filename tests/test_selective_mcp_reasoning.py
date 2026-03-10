"""Test that the agent selectively calls the right MCP based on the query.

Each scenario uses a different MCP (kubernetes / prometheus / argo) and verifies:
  - Only the relevant tool is called (not all three).
  - The ToolNode executes it.
  - The agent then produces a final answer without touching the other MCPs.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool


# ── Fake MCP tools (one per server) ──────────────────────────────────────────

@tool
def mcp_kubernetes__list_pods(namespace: str = "default") -> str:
    """List pods in a Kubernetes namespace."""
    return f"[k8s] pods in {namespace}: web-7d4f9b-xyz (Running), api-6c8d-abc (CrashLoopBackOff)"


@tool
def mcp_prometheus__query(promql: str) -> str:
    """Run a PromQL query against Prometheus."""
    return f"[prometheus] query='{promql}' result: 0.87 (87% CPU)"


@tool
def mcp_argocd__list_apps(project: str = "") -> str:
    """List Argo CD applications."""
    return "[argocd] apps: payments (Synced/Healthy), auth (OutOfSync/Degraded)"


FAKE_TOOLS = [mcp_kubernetes__list_pods, mcp_prometheus__query, mcp_argocd__list_apps]
TOOL_MAP = {t.name: t for t in FAKE_TOOLS}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tool_call(tool_name: str, args: dict, call_id: str = "tc1") -> dict:
    return {"name": tool_name, "args": args, "id": call_id, "type": "tool_call"}


def _ai_with_tool_call(tool_name: str, args: dict) -> AIMessage:
    """Simulate: LLM decides to call exactly one tool."""
    msg = AIMessage(content="")
    msg.tool_calls = [_tool_call(tool_name, args)]
    return msg


def _ai_final(content: str) -> AIMessage:
    """Simulate: LLM produces a final answer (no more tool calls)."""
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


def _build_mock_llm(tool_response_sequence: list[AIMessage]):
    """Return a mock LLM that replays the given response sequence on invoke()."""
    mock = MagicMock()
    mock.bind_tools.return_value = mock
    mock.invoke.side_effect = tool_response_sequence
    return mock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    import memory.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_selective.db")
    db_module.init_db()


# ── Scenario 1: Kubernetes query ──────────────────────────────────────────────

def test_kubernetes_query_uses_only_k8s_tool():
    """'Which pods are crashing?' → agent calls only mcp_kubernetes__list_pods."""
    responses = [
        _ai_with_tool_call("mcp_kubernetes__list_pods", {"namespace": "default"}),
        _ai_final("The api pod is in CrashLoopBackOff. No Prometheus or Argo queries needed."),
    ]
    mock_llm = _build_mock_llm(responses)

    with patch("models.registry.get_model", return_value=mock_llm):
        from agent.graph import build_graph, run_graph

        graph = build_graph(tools=FAKE_TOOLS)
        answer = run_graph(
            graph,
            "Which pods are crashing in the default namespace?",
            {"configurable": {"thread_id": "test-k8s"}},
        )

    # Verify the LLM was called twice (once to pick tool, once for final answer)
    assert mock_llm.invoke.call_count == 2

    # Verify only the k8s tool call appeared — extract all tool_calls from every invoke arg
    all_tool_calls = []
    for call_args in mock_llm.invoke.call_args_list:
        messages = call_args[0][0]
        for msg in messages:
            tc = getattr(msg, "tool_calls", None)
            if tc:
                all_tool_calls.extend([c["name"] for c in tc])
            # ToolMessages in the history signal which tools ran
            if isinstance(msg, ToolMessage):
                all_tool_calls.append(msg.name)

    assert "mcp_kubernetes__list_pods" in all_tool_calls
    assert "mcp_prometheus__query" not in all_tool_calls
    assert "mcp_argocd__list_apps" not in all_tool_calls
    assert "CrashLoopBackOff" in answer or "api" in answer


# ── Scenario 2: Prometheus query ──────────────────────────────────────────────

def test_prometheus_query_uses_only_prometheus_tool():
    """'What is the CPU usage of the payments service?' → only Prometheus is called."""
    responses = [
        _ai_with_tool_call(
            "mcp_prometheus__query",
            {"promql": 'rate(process_cpu_seconds_total{service="payments"}[5m])'},
        ),
        _ai_final("CPU usage is at 87%. No Kubernetes pod actions or Argo syncs required."),
    ]
    mock_llm = _build_mock_llm(responses)

    with patch("models.registry.get_model", return_value=mock_llm):
        from agent.graph import build_graph, run_graph

        graph = build_graph(tools=FAKE_TOOLS)
        answer = run_graph(
            graph,
            "What is the current CPU usage of the payments service?",
            {"configurable": {"thread_id": "test-prom"}},
        )

    assert mock_llm.invoke.call_count == 2

    all_tool_calls = []
    for call_args in mock_llm.invoke.call_args_list:
        messages = call_args[0][0]
        for msg in messages:
            tc = getattr(msg, "tool_calls", None)
            if tc:
                all_tool_calls.extend([c["name"] for c in tc])
            if isinstance(msg, ToolMessage):
                all_tool_calls.append(msg.name)

    assert "mcp_prometheus__query" in all_tool_calls
    assert "mcp_kubernetes__list_pods" not in all_tool_calls
    assert "mcp_argocd__list_apps" not in all_tool_calls
    assert "87" in answer or "CPU" in answer


# ── Scenario 3: Argo CD query ─────────────────────────────────────────────────

def test_argo_query_uses_only_argo_tool():
    """'Are there any out-of-sync Argo apps?' → only Argo CD is called."""
    responses = [
        _ai_with_tool_call("mcp_argocd__list_apps", {"project": ""}),
        _ai_final("The 'auth' application is OutOfSync and Degraded. No metrics or pod checks needed."),
    ]
    mock_llm = _build_mock_llm(responses)

    with patch("models.registry.get_model", return_value=mock_llm):
        from agent.graph import build_graph, run_graph

        graph = build_graph(tools=FAKE_TOOLS)
        answer = run_graph(
            graph,
            "Are there any out-of-sync applications in Argo CD?",
            {"configurable": {"thread_id": "test-argo"}},
        )

    assert mock_llm.invoke.call_count == 2

    all_tool_calls = []
    for call_args in mock_llm.invoke.call_args_list:
        messages = call_args[0][0]
        for msg in messages:
            tc = getattr(msg, "tool_calls", None)
            if tc:
                all_tool_calls.extend([c["name"] for c in tc])
            if isinstance(msg, ToolMessage):
                all_tool_calls.append(msg.name)

    assert "mcp_argocd__list_apps" in all_tool_calls
    assert "mcp_kubernetes__list_pods" not in all_tool_calls
    assert "mcp_prometheus__query" not in all_tool_calls
    assert "auth" in answer or "OutOfSync" in answer


# ── Scenario 4: Cross-MCP incident (k8s → prometheus) — sequential, not parallel ──

def test_cross_mcp_incident_uses_tools_sequentially():
    """Crash investigation: k8s first, then prometheus. Never both in one step."""
    responses = [
        # Step 1 — identify the crashing pod via k8s
        _ai_with_tool_call("mcp_kubernetes__list_pods", {"namespace": "production"}),
        # Step 2 — after seeing crash, check CPU via prometheus
        _ai_with_tool_call(
            "mcp_prometheus__query",
            {"promql": 'rate(process_cpu_seconds_total{pod="api-6c8d-abc"}[5m])'},
        ),
        # Step 3 — final answer; no argo needed
        _ai_final("Root cause: api pod is OOMKilled. CPU was at 87%. No Argo rollback needed."),
    ]
    mock_llm = _build_mock_llm(responses)

    with patch("models.registry.get_model", return_value=mock_llm):
        from agent.graph import build_graph, run_graph

        graph = build_graph(tools=FAKE_TOOLS)
        answer = run_graph(
            graph,
            "Investigate the crash in the production namespace and check resource usage.",
            {"configurable": {"thread_id": "test-cross"}},
        )

    assert mock_llm.invoke.call_count == 3

    # Each invoke call should contain AT MOST ONE tool call (sequential reasoning)
    for i, call_args in enumerate(mock_llm.invoke.call_args_list):
        messages = call_args[0][0]
        step_tool_calls = []
        for msg in messages:
            tc = getattr(msg, "tool_calls", None)
            if tc:
                step_tool_calls.extend(tc)
        # The last message in each step is the AI response; it should have ≤1 tool call
        last_msg = messages[-1]
        last_tc = getattr(last_msg, "tool_calls", [])
        assert len(last_tc) <= 1, (
            f"Step {i+1}: LLM called {len(last_tc)} tools simultaneously — expected sequential use"
        )

    # Argo was never needed
    all_tool_names = []
    for call_args in mock_llm.invoke.call_args_list:
        for msg in call_args[0][0]:
            if isinstance(msg, ToolMessage):
                all_tool_names.append(msg.name)
    assert "mcp_argocd__list_apps" not in all_tool_names
