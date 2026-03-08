"""Dynamic system prompt builder combining static SRE instructions with live memory.

The system prompt is rebuilt on every reasoning cycle so it always reflects the
latest incidents and patterns stored in the SQLite memory layer.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage
from langchain_core.messages import messages_from_dict

from agent.state import AgentState
from memory.store import memory_summary
from memory.store import get_context
from mcp_servers.servers import get_server_descriptions

_STATIC_INSTRUCTIONS = """\
You are an expert Site Reliability Engineer (SRE) AI assistant.
You have live access to infrastructure tools via MCP servers:

{server_descriptions}

## Core Responsibilities
1. DIAGNOSE — investigate alerts, pod crashes, OOMKills, failed deployments
2. REMEDIATE — restart pods, scale deployments, rollback Argo apps
3. EXPLAIN — root-cause analysis backed by real data from tools
4. REMEMBER — save every resolved incident to memory

## Rules
- ALWAYS query real tool data before drawing any conclusion. Never guess.
- ALWAYS confirm with the user before any destructive action.
- When you find a root cause, output a memory_save block immediately.
- When a new incident looks familiar, check memory_search first.
- If a tool returns empty or errors, say so and try an alternative.

## Memory Commands
Output these blocks in your response to interact with memory:

To save an incident:
```memory_save
{{
  "title": "short title",
  "severity": "critical|high|medium|low",
  "service": "service-name",
  "namespace": "kubernetes-namespace",
  "symptoms": "observed symptoms",
  "root_cause": "identified root cause",
  "resolution": "how it was fixed"
}}
```

To search past incidents:
```memory_search
{{
  "query": "search terms",
  "service": "optional",
  "limit": 5
}}
```

## Incident History & Patterns
{memory_context}
"""


def build_system_prompt(state: AgentState) -> str:
    """Build the full system prompt from static instructions + live memory context."""
    server_descriptions = get_server_descriptions()
    memory_context = state.get("memory_context") or memory_summary()

    return _STATIC_INSTRUCTIONS.format(
        server_descriptions=server_descriptions,
        memory_context=memory_context,
    )


def build_initial_state(
    model_name: str,
    tools: list,
    server_status: dict[str, str],
) -> dict:
    """Build the initial AgentState dict for a new session.

    Restores last 40 messages from persistent context storage.
    """
    mem_context = memory_summary()
    active_tools = [t.name for t in tools]

    # Restore conversation history
    messages: list[BaseMessage] = []
    raw_messages = get_context("messages", [])
    if raw_messages:
        try:
            messages = messages_from_dict(raw_messages[-40:])
        except Exception:
            messages = []

    return {
        "messages": messages,
        "model_name": model_name,
        "memory_context": mem_context,
        "active_tools": active_tools,
        "investigation_notes": "",
        "last_incident_id": None,
        "server_status": server_status,
    }
