"""Tests for agent/graph.py — graph compilation and node logic."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    """Use temp DB for all graph tests."""
    import memory.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_graph.db")
    db_module.init_db()


def test_build_graph_compiles_without_errors():
    from agent.graph import build_graph
    graph = build_graph(tools=[])
    assert graph is not None


def test_should_continue_returns_tools_when_tool_calls():
    from agent.nodes import should_continue
    msg = AIMessage(content="I need to call a tool")
    msg.tool_calls = [{"name": "some_tool", "args": {}, "id": "tc1"}]
    state = {"messages": [msg]}
    result = should_continue(state)
    assert result == "tools"


def test_should_continue_returns_end_when_no_tool_calls():
    from agent.nodes import should_continue
    msg = AIMessage(content="Here is my answer.")
    state = {"messages": [msg]}
    result = should_continue(state)
    assert result == "end"


def test_inject_memory_returns_memory_context():
    from agent.nodes import inject_memory
    state = {
        "messages": [],
        "model_name": "gemini/gemini-2.0-flash",
        "memory_context": "",
        "active_tools": [],
        "investigation_notes": "",
        "last_incident_id": None,
        "server_status": {},
    }
    result = inject_memory(state)
    assert "memory_context" in result
    assert isinstance(result["memory_context"], str)


def test_process_memory_commands_saves_incident():
    from agent.nodes import process_memory_commands
    import json

    save_json = json.dumps({
        "title": "Test incident from node",
        "severity": "high",
        "service": "test-svc",
        "namespace": "default",
        "symptoms": "pods crashing",
        "root_cause": "OOMKill",
        "resolution": "increased memory limit",
    })
    content = f"Analysis done.\n```memory_save\n{save_json}\n```"
    msg = AIMessage(content=content)

    state = {
        "messages": [msg],
        "model_name": "gemini/gemini-2.0-flash",
        "memory_context": "",
        "active_tools": [],
        "investigation_notes": "",
        "last_incident_id": None,
        "server_status": {},
    }
    result = process_memory_commands(state)
    tool_msgs = result.get("messages", [])
    assert any("saved" in (getattr(m, "content", "") or "").lower() for m in tool_msgs)
    assert result.get("last_incident_id") is not None


def test_process_memory_commands_handles_malformed_json():
    from agent.nodes import process_memory_commands

    content = "```memory_save\n{this is not valid json\n```"
    msg = AIMessage(content=content)
    state = {
        "messages": [msg],
        "model_name": "gemini/gemini-2.0-flash",
        "memory_context": "",
        "active_tools": [],
        "investigation_notes": "",
        "last_incident_id": None,
        "server_status": {},
    }
    # Should not raise
    result = process_memory_commands(state)
    tool_msgs = result.get("messages", [])
    assert any("Could not save" in (getattr(m, "content", "") or "") for m in tool_msgs)


def test_full_graph_run_with_mocked_llm(tmp_path, monkeypatch):
    """End-to-end graph run using a mocked LLM."""
    import memory.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_full.db")
    db_module.init_db()

    mock_response = AIMessage(content="I have analysed the situation. Everything looks fine.")

    mock_model = MagicMock()
    mock_model.bind_tools.return_value = mock_model
    mock_model.invoke.return_value = mock_response

    # reason() does a lazy `from models.registry import get_model` — patch at source
    with patch("models.registry.get_model", return_value=mock_model):
        from agent.graph import build_graph, run_graph
        graph = build_graph(tools=[])
        result = run_graph(
            graph,
            "Is everything okay?",
            {"configurable": {"thread_id": "test-thread-e2e"}},
        )
        assert isinstance(result, str)
