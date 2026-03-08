"""LangGraph node functions for the SRE agent graph.

Each node takes an AgentState and returns a partial state update dict.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages import messages_to_dict

from agent.state import AgentState
from memory.store import memory_summary, save_incident, search_incidents, set_context

logger = logging.getLogger(__name__)

# Module-level tools registry — populated by graph.py via set_active_tools()
_ACTIVE_TOOLS: list = []


def set_active_tools(tools: list) -> None:
    """Register the MCP tools list so the reason node can access them."""
    global _ACTIVE_TOOLS
    _ACTIVE_TOOLS = tools


def get_active_tools() -> list:
    """Return the currently registered tools list."""
    return _ACTIVE_TOOLS


def inject_memory(state: AgentState) -> dict:
    """Refresh memory context with the latest summary from the SQLite store."""
    summary = memory_summary()
    return {"memory_context": summary}


def reason(state: AgentState) -> dict:
    """Call the LLM with bound tools and the current message history."""
    from agent.prompt import build_system_prompt
    from models.registry import get_model

    model = get_model(state.get("model_name") or None)
    tools = get_active_tools()

    if tools:
        model_with_tools = model.bind_tools(tools)
    else:
        model_with_tools = model

    system_prompt = build_system_prompt(state)
    messages = [SystemMessage(content=system_prompt)] + list(state["messages"])

    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


def process_memory_commands(state: AgentState) -> dict:
    """Parse memory_save and memory_search blocks from the last assistant message."""
    messages = state["messages"]
    if not messages:
        return {}

    last_msg = messages[-1]
    content = getattr(last_msg, "content", "") or ""
    if not isinstance(content, str):
        # Handle list-of-parts content
        content = " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )

    # Use HumanMessage for injected memory results — ToolMessage requires a
    # matching tool_call_id in the conversation history, which memory blocks don't have.
    feedback_messages: list[HumanMessage] = []
    last_incident_id: int | None = None

    # Process memory_save blocks
    save_pattern = re.compile(r"```memory_save\s*(.*?)```", re.DOTALL)
    for match in save_pattern.finditer(content):
        raw_json = match.group(1).strip()
        try:
            data = json.loads(raw_json)
            incident_id = save_incident(
                title=data.get("title", "Untitled"),
                severity=data.get("severity", "unknown"),
                service=data.get("service", ""),
                namespace=data.get("namespace", ""),
                symptoms=data.get("symptoms", ""),
                root_cause=data.get("root_cause", ""),
                resolution=data.get("resolution", ""),
                tags=data.get("tags", []),
            )
            last_incident_id = incident_id
            feedback_messages.append(
                HumanMessage(content=f"[system] ✅ Incident #{incident_id} saved to memory.")
            )
            logger.info("Saved incident #%d: %s", incident_id, data.get("title"))
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to parse memory_save block: %s", exc)
            feedback_messages.append(
                HumanMessage(content=f"[system] ⚠️ Could not save incident: {exc}")
            )

    # Process memory_search blocks
    search_pattern = re.compile(r"```memory_search\s*(.*?)```", re.DOTALL)
    for match in search_pattern.finditer(content):
        raw_json = match.group(1).strip()
        try:
            data = json.loads(raw_json)
            results = search_incidents(
                query=data.get("query", ""),
                service=data.get("service", ""),
                limit=data.get("limit", 5),
            )
            if results:
                lines = ["[system] **Memory Search Results:**\n"]
                for r in results:
                    emoji = "✅" if r.get("resolved") else "🔥"
                    ts = (r.get("ts") or "")[:10]
                    lines.append(
                        f"{emoji} [{ts}] **{r['title']}** | {r['severity']} | "
                        f"{r.get('service', '')} | RC: {(r.get('root_cause') or '')[:80]}"
                    )
                result_text = "\n".join(lines)
            else:
                result_text = "[system] No matching incidents found in memory."

            feedback_messages.append(HumanMessage(content=result_text))
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to process memory_search block: %s", exc)
            feedback_messages.append(
                HumanMessage(content=f"[system] ⚠️ Memory search failed: {exc}")
            )

    update: dict = {"messages": feedback_messages}
    if last_incident_id is not None:
        update["last_incident_id"] = last_incident_id
    return update


def save_conversation(state: AgentState) -> dict:
    """Persist the last 40 messages to the context store for session resumption."""
    messages = list(state["messages"])[-40:]
    try:
        serialised = messages_to_dict(messages)
        set_context("messages", serialised)
    except Exception as exc:
        logger.warning("Could not save conversation history: %s", exc)
    return {}


def should_continue(state: AgentState) -> str:
    """Route to 'tools' if last message has tool calls, else 'end'."""
    messages = state["messages"]
    if not messages:
        return "end"
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        return "tools"
    return "end"
