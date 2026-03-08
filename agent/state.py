"""LangGraph state definition for the SRE agent."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph nodes."""

    messages: Annotated[list[BaseMessage], add_messages]
    model_name: str
    memory_context: str
    active_tools: list[str]
    investigation_notes: str
    last_incident_id: int | None
    server_status: dict[str, str]
