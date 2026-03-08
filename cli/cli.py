"""Full-featured terminal UI for the SRE agent, built with Rich.

Provides a REPL loop with slash commands, streaming output, and graceful
error handling. Never crashes on bad input or MCP server failures.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import print as rprint

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

console = Console()
logging.basicConfig(level=logging.WARNING)


def _print_startup_header() -> None:
    """Print the ASCII banner."""
    console.print(
        "\n[bold cyan]╔══════════════════════════════════════════════════════════╗[/bold cyan]"
    )
    console.print(
        "[bold cyan]║              SRE Agent  •  Powered by LangGraph          ║[/bold cyan]"
    )
    console.print(
        "[bold cyan]╚══════════════════════════════════════════════════════════╝[/bold cyan]\n"
    )


def _print_checklist(model_info: dict, server_status: dict, thread_id: str) -> None:
    """Print the startup checklist."""
    from memory.store import get_recent_incidents, get_top_patterns

    provider = model_info.get("provider", "?")
    model = model_info.get("model", "?")
    source = model_info.get("source", "?")
    console.print(f"  [green]✅[/green]  Model:  {provider}/{model}  (source: {source})")

    try:
        incidents = get_recent_incidents(limit=999)
        patterns = get_top_patterns(limit=999)
        db_path = Path.home() / ".sre_agent" / "memory.db"
        console.print(
            f"  [green]✅[/green]  Memory: {db_path}  "
            f"({len(incidents)} incidents · {len(patterns)} patterns)"
        )
    except Exception as exc:
        console.print(f"  [yellow]⚠️[/yellow]   Memory: error — {exc}")

    for name, status in server_status.items():
        if status.startswith("connected"):
            console.print(f"  [green]✅[/green]  MCP {name}: {status}")
        else:
            console.print(f"  [yellow]⚠️[/yellow]   MCP {name}: {status}")

    console.print(f"  [green]✅[/green]  Thread: {thread_id}")
    console.print("\n  Type /help for commands. Ctrl+C to exit.\n")


def _print_help() -> None:
    """Print a Rich table of all slash commands."""
    table = Table(title="SRE Agent — Slash Commands", show_lines=True)
    table.add_column("Command", style="cyan bold")
    table.add_column("Description")

    commands = [
        ("/help", "Show this help table"),
        ("/model <name>", "Switch model (e.g. /model openai/gpt-4o)"),
        ("/memory", "Show memory summary panel"),
        ("/incidents [N]", "Table of recent N incidents (default 10)"),
        ("/patterns", "Table of top failure patterns"),
        ("/search <query>", "Search incidents by keyword"),
        ("/save", "Interactively save a new incident"),
        ("/servers", "Table of MCP server statuses"),
        ("/thread <name>", "Switch conversation thread"),
        ("/reset", "Clear current thread conversation (memory kept)"),
        ("/export", "Export all incidents to incidents_export.json"),
        ("/quit or /exit", "Exit the agent"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    console.print(table)


def _cmd_memory() -> None:
    """Display the memory summary in a Rich panel."""
    from memory.store import memory_summary
    summary = memory_summary()
    console.print(Panel(summary, title="[bold]Memory Summary[/bold]", border_style="blue"))


def _cmd_incidents(args: list[str]) -> None:
    """Display recent incidents in a Rich table."""
    from memory.store import get_recent_incidents
    limit = int(args[0]) if args else 10
    incidents = get_recent_incidents(limit=limit)

    if not incidents:
        console.print("[yellow]No incidents found.[/yellow]")
        return

    table = Table(title=f"Recent Incidents (last {limit})", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Date")
    table.add_column("Title")
    table.add_column("Sev", style="bold")
    table.add_column("Service")
    table.add_column("Root Cause")
    table.add_column("Status")

    for inc in incidents:
        status = "✅ resolved" if inc.get("resolved") else "🔥 open"
        sev = inc.get("severity", "?")
        sev_style = {"critical": "red", "high": "orange3", "medium": "yellow", "low": "green"}.get(sev, "white")
        table.add_row(
            str(inc["id"]),
            (inc.get("ts") or "")[:10],
            inc.get("title", ""),
            f"[{sev_style}]{sev}[/{sev_style}]",
            inc.get("service", ""),
            (inc.get("root_cause") or "")[:60],
            status,
        )
    console.print(table)


def _cmd_patterns() -> None:
    """Display top failure patterns in a Rich table."""
    from memory.store import get_top_patterns
    patterns = get_top_patterns(limit=20)

    if not patterns:
        console.print("[yellow]No patterns found.[/yellow]")
        return

    table = Table(title="Top Failure Patterns", show_lines=True)
    table.add_column("Rank", style="cyan")
    table.add_column("Frequency", style="bold red")
    table.add_column("Pattern")
    table.add_column("Last Seen")

    for i, pat in enumerate(patterns, 1):
        table.add_row(
            str(i),
            str(pat.get("frequency", 1)),
            (pat.get("pattern") or "")[:100],
            (pat.get("last_seen") or "")[:10],
        )
    console.print(table)


def _cmd_search(args: list[str]) -> None:
    """Search incidents and display results."""
    from memory.store import search_incidents
    query = " ".join(args)
    if not query:
        console.print("[yellow]Usage: /search <query>[/yellow]")
        return

    results = search_incidents(query=query, limit=10)
    if not results:
        console.print(f"[yellow]No incidents matching '{query}'.[/yellow]")
        return

    table = Table(title=f"Search: '{query}'", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Date")
    table.add_column("Title")
    table.add_column("Sev")
    table.add_column("Service")
    table.add_column("Root Cause")

    for inc in results:
        table.add_row(
            str(inc["id"]),
            (inc.get("ts") or "")[:10],
            inc.get("title", ""),
            inc.get("severity", "?"),
            inc.get("service", ""),
            (inc.get("root_cause") or "")[:60],
        )
    console.print(table)


def _cmd_save() -> None:
    """Interactively collect incident fields and save to memory."""
    from memory.store import save_incident
    console.print("[bold]Save Incident[/bold] — press Enter to skip optional fields\n")

    try:
        title = Prompt.ask("[cyan]Title[/cyan]")
        if not title:
            console.print("[red]Title is required.[/red]")
            return
        severity = Prompt.ask(
            "[cyan]Severity[/cyan]",
            choices=["critical", "high", "medium", "low", "unknown"],
            default="unknown",
        )
        service = Prompt.ask("[cyan]Service[/cyan]", default="")
        namespace = Prompt.ask("[cyan]Namespace[/cyan]", default="")
        symptoms = Prompt.ask("[cyan]Symptoms[/cyan]", default="")
        root_cause = Prompt.ask("[cyan]Root cause[/cyan]", default="")
        resolution = Prompt.ask("[cyan]Resolution[/cyan]", default="")

        incident_id = save_incident(
            title=title,
            severity=severity,
            service=service,
            namespace=namespace,
            symptoms=symptoms,
            root_cause=root_cause,
            resolution=resolution,
        )
        console.print(f"[green]✅ Incident #{incident_id} saved.[/green]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Save cancelled.[/yellow]")


def _cmd_servers(server_status: dict[str, str]) -> None:
    """Display MCP server statuses in a Rich table."""
    from mcp_servers.servers import _load_config, expand_env_vars

    config = _load_config()
    servers_cfg = config.get("servers", {})

    table = Table(title="MCP Servers", show_lines=True)
    table.add_column("Server", style="cyan bold")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Tools")

    for name, cfg in servers_cfg.items():
        url = expand_env_vars(cfg.get("url", ""))
        status = server_status.get(name, "unknown")
        if status.startswith("connected"):
            import re
            m = re.search(r"\((\d+) tools\)", status)
            tool_count = m.group(1) if m else "?"
            status_display = "[green]✅ connected[/green]"
        else:
            tool_count = "0"
            status_display = f"[yellow]⚠️  {status}[/yellow]"

        table.add_row(name, url, status_display, tool_count)
    console.print(table)


def _cmd_export() -> None:
    """Export all incidents to incidents_export.json."""
    from memory.store import search_incidents
    results = search_incidents(limit=9999)
    output_path = Path.cwd() / "incidents_export.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    console.print(f"[green]✅ Exported {len(results)} incidents to {output_path}[/green]")


def main() -> None:
    """Entry point — parse args, load env, start the REPL loop."""
    load_dotenv()

    parser = argparse.ArgumentParser(description="SRE Agent — LangGraph-powered CLI")
    parser.add_argument("--model", default=None, help="Model string (e.g. gemini/gemini-2.0-flash)")
    parser.add_argument("--thread", default="default", help="LangGraph thread ID")
    args = parser.parse_args()

    thread_id = args.thread
    model_override = args.model

    # ── Load MCP tools ──
    console.print("[dim]Connecting to MCP servers...[/dim]")
    try:
        from mcp_servers.servers import load_mcp_tools_sync
        tools, server_status = load_mcp_tools_sync()
    except Exception as exc:
        console.print(Panel(f"[red]Failed to load MCP tools: {exc}[/red]", title="MCP Error"))
        tools, server_status = [], {}

    # ── Load model info ──
    try:
        from models.registry import get_model_info
        model_info = get_model_info(model_override)
    except ValueError as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Model Config Error"))
        sys.exit(1)

    # ── Build graph ──
    try:
        from agent.graph import build_graph
        graph = build_graph(tools)
    except Exception as exc:
        console.print(Panel(f"[red]Failed to build graph: {exc}[/red]", title="Graph Error"))
        sys.exit(1)

    # ── Print startup UI ──
    _print_startup_header()
    _print_checklist(model_info, server_status, thread_id)

    # ── Determine model_name for state ──
    model_name = model_override
    if not model_name:
        import os
        model_name = os.environ.get("MODEL")
    if not model_name:
        model_name = f"{model_info['provider']}/{model_info['model']}"

    # ── REPL loop ──
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — exiting.[/dim]")
            break
        except EOFError:
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # ── Slash commands ──
        if user_input.startswith("/"):
            parts = user_input[1:].split()
            cmd = parts[0].lower() if parts else ""
            cmd_args = parts[1:]

            match cmd:
                case "help":
                    _print_help()
                case "memory":
                    _cmd_memory()
                case "incidents":
                    try:
                        _cmd_incidents(cmd_args)
                    except Exception as exc:
                        console.print(Panel(f"[red]{exc}[/red]", title="Error"))
                case "patterns":
                    try:
                        _cmd_patterns()
                    except Exception as exc:
                        console.print(Panel(f"[red]{exc}[/red]", title="Error"))
                case "search":
                    try:
                        _cmd_search(cmd_args)
                    except Exception as exc:
                        console.print(Panel(f"[red]{exc}[/red]", title="Error"))
                case "save":
                    try:
                        _cmd_save()
                    except Exception as exc:
                        console.print(Panel(f"[red]{exc}[/red]", title="Error"))
                case "servers":
                    try:
                        _cmd_servers(server_status)
                    except Exception as exc:
                        console.print(Panel(f"[red]{exc}[/red]", title="Error"))
                case "thread":
                    if cmd_args:
                        thread_id = cmd_args[0]
                        config = {"configurable": {"thread_id": thread_id}}
                        console.print(f"[green]✅ Switched to thread: {thread_id}[/green]")
                    else:
                        console.print(f"[yellow]Current thread: {thread_id}[/yellow]")
                case "reset":
                    config = {"configurable": {"thread_id": thread_id}}
                    console.print(
                        f"[yellow]Thread '{thread_id}' conversation cleared (memory kept).[/yellow]"
                    )
                case "export":
                    try:
                        _cmd_export()
                    except Exception as exc:
                        console.print(Panel(f"[red]{exc}[/red]", title="Export Error"))
                case "model":
                    if cmd_args:
                        new_model = cmd_args[0]
                        try:
                            from models.registry import get_model_info
                            new_info = get_model_info(new_model)
                            model_name = new_model
                            from agent.graph import build_graph
                            graph = build_graph(tools)
                            console.print(
                                f"[green]✅ Switched to {new_info['provider']}/{new_info['model']}[/green]"
                            )
                        except Exception as exc:
                            console.print(Panel(f"[red]{exc}[/red]", title="Model Switch Error"))
                    else:
                        console.print(f"[yellow]Current model: {model_name}[/yellow]")
                case "quit" | "exit":
                    console.print("[dim]Goodbye.[/dim]")
                    sys.exit(0)
                case _:
                    console.print(
                        f"[yellow]Unknown command: /{cmd}. Type /help for commands.[/yellow]"
                    )

            continue

        # ── Normal chat message — stream to agent ──
        try:
            from agent.graph import stream_graph

            console.print("[bold green]Agent:[/bold green] ", end="")
            last_content = ""
            for chunk in stream_graph(graph, user_input, config):
                if chunk != last_content:
                    # Print only the new portion
                    if chunk.startswith(last_content):
                        new_part = chunk[len(last_content):]
                        console.print(new_part, end="")
                    else:
                        console.print(chunk, end="")
                    last_content = chunk
            console.print()  # newline after response

        except ValueError as exc:
            if "API_KEY" in str(exc) or "env var" in str(exc):
                console.print(
                    Panel(
                        f"[red]{exc}[/red]\n\nSet the key in your [bold].env[/bold] file and restart.",
                        title="API Key Required",
                        border_style="red",
                    )
                )
            else:
                console.print(Panel(f"[red]{exc}[/red]", title="Error", border_style="red"))
        except Exception as exc:
            console.print(Panel(f"[red]{exc}[/red]", title="Agent Error", border_style="red"))


if __name__ == "__main__":
    main()
