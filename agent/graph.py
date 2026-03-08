"""LangGraph graph definition and runner for the SRE agent.

The graph wires together memory injection, reasoning, tool execution,
memory command processing, and conversation persistence.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Iterator

from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.nodes import (
    inject_memory,
    process_memory_commands,
    reason,
    save_conversation,
    set_active_tools,
    should_continue,
)
from agent.state import AgentState

logger = logging.getLogger(__name__)

# Module-level compiled graph reference (set by build_graph)
_ACTIVE_TOOLS: list[BaseTool] = []


def set_active_tools_ref(tools: list[BaseTool]) -> None:
    """Store tools reference at module level and in nodes module."""
    global _ACTIVE_TOOLS
    _ACTIVE_TOOLS = tools
    set_active_tools(tools)


def get_active_tools() -> list[BaseTool]:
    """Return the currently active tools list."""
    return _ACTIVE_TOOLS


def build_graph(tools: list[BaseTool]):
    """Compile and return the LangGraph agent graph with the given tools.

    Uses SqliteSaver for checkpointing so sessions can be resumed.
    """
    # Register tools in the nodes module
    set_active_tools_ref(tools)

    graph = StateGraph(AgentState)

    graph.add_node("inject_memory", inject_memory)
    graph.add_node("reason", reason)
    graph.add_node("tools", ToolNode(tools) if tools else ToolNode([]))
    graph.add_node("process_memory_commands", process_memory_commands)
    graph.add_node("save_conversation", save_conversation)

    graph.set_entry_point("inject_memory")

    graph.add_edge("inject_memory", "reason")
    graph.add_conditional_edges(
        "reason",
        should_continue,
        {"tools": "tools", "end": "process_memory_commands"},
    )
    graph.add_edge("tools", "reason")
    graph.add_edge("process_memory_commands", "save_conversation")
    graph.add_edge("save_conversation", END)

    # Set up SQLite checkpointer
    checkpoint_path = Path.home() / ".sre_agent" / "checkpoints.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    checkpointer = None
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async def _make_checkpointer():
            conn = await aiosqlite.connect(str(checkpoint_path))
            saver = AsyncSqliteSaver(conn=conn)
            await saver.setup()
            return saver

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Inside an async context — schedule as a task and run it now
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                checkpointer = pool.submit(asyncio.run, _make_checkpointer()).result()
        else:
            checkpointer = asyncio.run(_make_checkpointer())
    except (ImportError, Exception) as exc:
        logger.warning("AsyncSqliteSaver unavailable — falling back to MemorySaver: %s", exc)
        try:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
        except Exception:
            checkpointer = None

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


async def _run_graph_async(graph, user_message: str, config: dict) -> str:
    """Async implementation of graph invocation (required for async MCP tools)."""
    from langchain_core.messages import HumanMessage

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=user_message)]},
        config=config,
    )
    messages = result.get("messages", [])
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if content and msg.__class__.__name__ == "AIMessage":
            return content if isinstance(content, str) else str(content)
    return ""


def run_graph(graph, user_message: str, config: dict) -> str:
    """Invoke the graph with a user message and return the last assistant response."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (e.g. Jupyter) — create a task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run_graph_async(graph, user_message, config))
            return future.result()
    else:
        return asyncio.run(_run_graph_async(graph, user_message, config))


async def _stream_graph_async(graph, user_message: str, config: dict):
    """Async generator that yields AIMessage content chunks."""
    from langchain_core.messages import HumanMessage

    seen: set[str] = set()
    async for event in graph.astream(
        {"messages": [HumanMessage(content=user_message)]},
        config=config,
        stream_mode="values",
    ):
        messages = event.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if last_msg.__class__.__name__ == "AIMessage":
                content = getattr(last_msg, "content", "")
                if isinstance(content, str) and content and content not in seen:
                    seen.add(content)
                    yield content


def stream_graph(graph, user_message: str, config: dict) -> Iterator[str]:
    """Stream the graph output, yielding text chunks from the reason node."""

    async def _collect():
        chunks = []
        async for chunk in _stream_graph_async(graph, user_message, config):
            chunks.append(chunk)
        return chunks

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _collect())
            chunks = future.result()
    else:
        chunks = asyncio.run(_collect())

    yield from chunks
