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
from rich.syntax import Syntax
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

console = Console()
logging.basicConfig(level=logging.WARNING)


class ResponseFormatter:
    """Format agent responses with rich styling and structure."""

    @staticmethod
    def format_response(response: str) -> None:
        """Format and display the agent's final response."""
        response = response.strip()
        if not response:
            console.print("[dim]No response generated.[/dim]")
            return

        # Check if response is JSON-like
        if response.startswith("{") or response.startswith("["):
            try:
                parsed = json.loads(response)
                formatted = json.dumps(parsed, indent=2)
                syntax = Syntax(formatted, "json", theme="monokai", line_numbers=False)
                console.print(Panel(
                    syntax,
                    title="[bold cyan]📊 Response[/bold cyan]",
                    border_style="cyan",
                    padding=(1, 2),
                ))
                return
            except json.JSONDecodeError:
                pass

        # Check for code blocks
        if "```" in response:
            parts = response.split("```")
            console.print()
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    # Regular text
                    if part.strip():
                        console.print(part.strip())
                else:
                    # Code block
                    lines = part.strip().split("\n")
                    lang = lines[0] if lines and lines[0] and not any(c in lines[0] for c in " \t") else "python"
                    code = "\n".join(lines[1:] if lines and lines[0] else lines).strip()
                    syntax = Syntax(code, lang, theme="monokai", line_numbers=True)
                    console.print(Panel(
                        syntax,
                        border_style="green",
                        padding=(1, 2),
                    ))
            return

        # For plain text, extract key sections for better presentation
        lines = response.split("\n")
        formatted_lines = []
        in_list = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if formatted_lines:
                    formatted_lines.append("")
                in_list = False
            elif stripped.startswith(("- ", "* ", "• ")):
                if not in_list:
                    in_list = True
                formatted_lines.append(f"  [green]→[/green] {stripped[2:]}")
            elif stripped.startswith(("#", "1.", "2.", "3.")):
                in_list = False
                formatted_lines.append(f"\n[bold yellow]{stripped}[/bold yellow]")
            elif ":" in stripped and len(stripped) < 100:
                in_list = False
                key, val = stripped.split(":", 1)
                formatted_lines.append(f"[bold cyan]{key}:[/bold cyan] {val.strip()}")
            else:
                in_list = False
                formatted_lines.append(stripped)

        content = "\n".join(formatted_lines)
        console.print(Panel(
            content,
            title="[bold cyan]💡 Response[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))


console = Console()
logging.basicConfig(level=logging.WARNING)


def _print_startup_header() -> None:
    """Print the ASCII banner with improved styling."""
    header = """
    [bold cyan]
    ╔════════════════════════════════════════════════════════════════╗
    ║                                                                ║
    ║              🚀  SRE AGENT  •  Powered by LangGraph   🚀      ║
    ║                                                                ║
    ║         Intelligent Infrastructure Troubleshooting             ║
    ║                                                                ║
    ╚════════════════════════════════════════════════════════════════╝
    [/bold cyan]
    """
    console.print(header)


def _print_checklist(model_info: dict, server_status: dict, thread_id: str) -> None:
    """Print the startup checklist with enhanced styling."""
    from memory.store import get_recent_incidents, get_top_patterns

    console.print("[bold]📋 Initialization Status[/bold]\n")

    provider = model_info.get("provider", "?")
    model = model_info.get("model", "?")
    source = model_info.get("source", "?")
    console.print(f"  [green]✅[/green]  [bold white]Model:[/bold white]  {provider}/{model}  [dim](source: {source})[/dim]")

    try:
        incidents = get_recent_incidents(limit=999)
        patterns = get_top_patterns(limit=999)
        db_path = Path.home() / ".sre_agent" / "memory.db"
        console.print(
            f"  [green]✅[/green]  [bold white]Memory:[/bold white] {db_path}  "
            f"[dim]({len(incidents)} incidents · {len(patterns)} patterns)[/dim]"
        )
    except Exception as exc:
        console.print(f"  [yellow]⚠️[/yellow]   [bold white]Memory:[/bold white] error — {exc}")

    for name, status in server_status.items():
        if status.startswith("connected"):
            console.print(f"  [green]✅[/green]  [bold white]MCP {name}:[/bold white] [green]{status}[/green]")
        else:
            console.print(f"  [yellow]⚠️[/yellow]   [bold white]MCP {name}:[/bold white] [yellow]{status}[/yellow]")

    console.print(f"  [green]✅[/green]  [bold white]Thread:[/bold white] [cyan]{thread_id}[/cyan]")
    console.print("\n  [dim]Type [bold]/help[/bold] for commands • Ctrl+C to exit[/dim]\n")


def _print_help() -> None:
    """Print a Rich table of all slash commands with enhanced styling."""
    table = Table(
        title="[bold cyan]🔧 SRE Agent — Slash Commands[/bold cyan]",
        show_lines=True,
        border_style="cyan",
    )
    table.add_column("Command", style="bold magenta", width=20)
    table.add_column("Description", style="white")

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
    console.print(Panel(
        summary,
        title="[bold cyan]📚 Memory Summary[/bold cyan]",
        border_style="blue",
        padding=(1, 2),
    ))


def _cmd_incidents(args: list[str]) -> None:
    """Display recent incidents in a Rich table."""
    from memory.store import get_recent_incidents
    limit = int(args[0]) if args else 10
    incidents = get_recent_incidents(limit=limit)

    if not incidents:
        console.print("[yellow]⚠️  No incidents found.[/yellow]")
        return

    table = Table(
        title=f"[bold cyan]📋 Recent Incidents (last {limit})[/bold cyan]",
        show_lines=True,
        border_style="cyan",
    )
    table.add_column("ID", style="bright_cyan", width=5)
    table.add_column("Date", width=12)
    table.add_column("Title", width=25)
    table.add_column("Sev", width=10, style="bold")
    table.add_column("Service", width=15)
    table.add_column("Root Cause", width=40)
    table.add_column("Status", width=12)

    for inc in incidents:
        status = "[green]✅ Resolved[/green]" if inc.get("resolved") else "[red]🔥 Open[/red]"
        sev = inc.get("severity", "?")
        sev_style = {"critical": "bold red", "high": "orange3", "medium": "yellow", "low": "green"}.get(sev, "white")
        table.add_row(
            str(inc["id"]),
            (inc.get("ts") or "")[:10],
            inc.get("title", "")[:25],
            f"[{sev_style}]{sev.upper()}[/{sev_style}]",
            inc.get("service", "")[:15],
            (inc.get("root_cause") or "")[:40],
            status,
        )
    console.print(table)


def _cmd_patterns() -> None:
    """Display top failure patterns in a Rich table."""
    from memory.store import get_top_patterns
    patterns = get_top_patterns(limit=20)

    if not patterns:
        console.print("[yellow]⚠️  No patterns found.[/yellow]")
        return

    table = Table(
        title="[bold cyan]📊 Top Failure Patterns[/bold cyan]",
        show_lines=True,
        border_style="cyan",
    )
    table.add_column("Rank", style="bright_cyan bold", width=5)
    table.add_column("Frequency", style="bold red", width=12)
    table.add_column("Pattern", width=50)
    table.add_column("Last Seen", width=12)

    for i, pat in enumerate(patterns, 1):
        table.add_row(
            f"#{i}",
            f"[bold]{pat.get('frequency', 1)}[/bold]x",
            (pat.get("pattern") or "")[:50],
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
        console.print(f"[yellow]⚠️  No incidents matching '{query}'.[/yellow]")
        return

    table = Table(
        title=f"[bold cyan]🔍 Search Results: '{query}'[/bold cyan]",
        show_lines=True,
        border_style="cyan",
    )
    table.add_column("ID", style="bright_cyan", width=5)
    table.add_column("Date", width=12)
    table.add_column("Title", width=25)
    table.add_column("Sev", width=10, style="bold")
    table.add_column("Service", width=15)
    table.add_column("Root Cause", width=35)

    for inc in results:
        sev = inc.get("severity", "?")
        sev_style = {"critical": "bold red", "high": "orange3", "medium": "yellow", "low": "green"}.get(sev, "white")
        table.add_row(
            str(inc["id"]),
            (inc.get("ts") or "")[:10],
            inc.get("title", "")[:25],
            f"[{sev_style}]{sev.upper()}[/{sev_style}]",
            inc.get("service", "")[:15],
            (inc.get("root_cause") or "")[:35],
        )
    console.print(table)


def _cmd_save() -> None:
    """Interactively collect incident fields and save to memory."""
    from memory.store import save_incident
    console.print(Panel(
        "[bold cyan]Save New Incident[/bold cyan]\nPress [dim]Enter[/dim] to skip optional fields\n",
        border_style="cyan",
        padding=(1, 2),
    ))

    try:
        title = Prompt.ask("[cyan]Title[/cyan]")
        if not title:
            console.print("[red]❌ Title is required.[/red]")
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
        console.print(f"\n[green]✅ Incident #{incident_id} saved successfully![/green]")
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Save cancelled.[/yellow]")


def _cmd_servers(server_status: dict[str, str]) -> None:
    """Display MCP server statuses in a Rich table."""
    from mcp_servers.servers import _load_config, expand_env_vars

    config = _load_config()
    servers_cfg = config.get("servers", {})

    table = Table(
        title="[bold cyan]⚙️  MCP Servers Status[/bold cyan]",
        show_lines=True,
        border_style="cyan",
    )
    table.add_column("Server", style="bright_cyan bold", width=15)
    table.add_column("URL", width=40)
    table.add_column("Status", width=20)
    table.add_column("Tools", style="bold yellow", width=8)

    for name, cfg in servers_cfg.items():
        transport = cfg.get("transport", "streamable_http")
        if transport == "stdio":
            cmd = cfg.get("command", "")
            args = " ".join(cfg.get("args", []))
            endpoint = f"stdio: {cmd} {args}".strip()
        else:
            endpoint = expand_env_vars(cfg.get("url", ""))
        status = server_status.get(name, "unknown")
        if status.startswith("connected"):
            import re
            m = re.search(r"\((\d+) tools\)", status)
            tool_count = m.group(1) if m else "?"
            status_display = "[green]✅ Connected[/green]"
        else:
            tool_count = "0"
            status_display = f"[yellow]⚠️  {status}[/yellow]"

        table.add_row(name, endpoint, status_display, tool_count)
    console.print(table)


def _cmd_export() -> None:
    """Export all incidents to incidents_export.json."""
    from memory.store import search_incidents
    results = search_incidents(limit=9999)
    output_path = Path.cwd() / "incidents_export.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    console.print(Panel(
        f"[green]✅ Successfully exported {len(results)} incidents[/green]\n\n"
        f"[bold cyan]File:[/bold cyan] {output_path}",
        title="[bold cyan]📤 Export Complete[/bold cyan]",
        border_style="green",
        padding=(1, 2),
    ))


async def _main_async(thread_id: str, model_override: str | None) -> None:
    """Async REPL — runs entirely in one event loop so MCP stdio sessions stay alive."""
    import asyncio

    # ── Load MCP tools (async — sessions stay alive in this loop) ──
    console.print("[dim]Connecting to MCP servers...[/dim]")
    try:
        from mcp_servers.servers import load_mcp_tools_async
        tools, server_status = await load_mcp_tools_async()
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
    import os
    model_name = model_override or os.environ.get("MODEL") or f"{model_info['provider']}/{model_info['model']}"

    # ── REPL loop ──
    config = {"configurable": {"thread_id": thread_id}}
    loop = asyncio.get_event_loop()

    while True:
        try:
            # Run blocking prompt in executor so the event loop stays free
            user_input = await loop.run_in_executor(
                None, lambda: Prompt.ask("\n[bold cyan]You[/bold cyan]", console=console)
            )
        except KeyboardInterrupt:
            console.print("\n[dim]👋 Ctrl+C — exiting.[/dim]")
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
                        console.print(Panel(f"[red]❌ {exc}[/red]", title="Error", border_style="red"))
                case "patterns":
                    try:
                        _cmd_patterns()
                    except Exception as exc:
                        console.print(Panel(f"[red]❌ {exc}[/red]", title="Error", border_style="red"))
                case "search":
                    try:
                        _cmd_search(cmd_args)
                    except Exception as exc:
                        console.print(Panel(f"[red]❌ {exc}[/red]", title="Error", border_style="red"))
                case "save":
                    try:
                        _cmd_save()
                    except Exception as exc:
                        console.print(Panel(f"[red]❌ {exc}[/red]", title="Error", border_style="red"))
                case "servers":
                    try:
                        _cmd_servers(server_status)
                    except Exception as exc:
                        console.print(Panel(f"[red]❌ {exc}[/red]", title="Error", border_style="red"))
                case "thread":
                    if cmd_args:
                        thread_id = cmd_args[0]
                        config = {"configurable": {"thread_id": thread_id}}
                        console.print(f"[green]✅ Switched to thread: [bold]{thread_id}[/bold][/green]")
                    else:
                        console.print(f"[cyan]Current thread: [bold]{thread_id}[/bold][/cyan]")
                case "reset":
                    config = {"configurable": {"thread_id": thread_id}}
                    console.print(
                        f"[yellow]⚠️  Thread '[bold]{thread_id}[/bold]' conversation cleared (memory kept).[/yellow]"
                    )
                case "export":
                    try:
                        _cmd_export()
                    except Exception as exc:
                        console.print(Panel(f"[red]❌ {exc}[/red]", title="Export Error", border_style="red"))
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
                            console.print(Panel(f"[red]❌ {exc}[/red]", title="Model Switch Error", border_style="red"))
                    else:
                        console.print(f"[cyan]Current model: [bold]{model_name}[/bold][/cyan]")
                case "quit" | "exit":
                    console.print("[dim]👋 Goodbye![/dim]")
                    sys.exit(0)
                case _:
                    console.print(
                        f"[yellow]❓ Unknown command: /{cmd}. Type [bold]/help[/bold] for commands.[/yellow]"
                    )

            continue

        # ── Normal chat message — stream directly in this event loop ──
        try:
            from agent.graph import _stream_graph_async

            full_response = ""
            with console.status("[bold cyan]⚙️  Processing your request...[/bold cyan]", spinner="dots"):
                async for chunk in _stream_graph_async(graph, user_input, config):
                    full_response = chunk

            console.print()
            ResponseFormatter.format_response(full_response)

        except ValueError as exc:
            if "API_KEY" in str(exc) or "env var" in str(exc):
                console.print(
                    Panel(
                        f"[red]❌ {exc}[/red]\n\nSet the key in your [bold].env[/bold] file and restart.",
                        title="API Key Required",
                        border_style="red",
                        padding=(1, 2),
                    )
                )
            else:
                console.print(Panel(f"[red]❌ {exc}[/red]", title="Error", border_style="red", padding=(1, 2)))
        except Exception as exc:
            console.print(Panel(f"[red]❌ {exc}[/red]", title="Agent Error", border_style="red", padding=(1, 2)))


def main() -> None:
    """Entry point — parse args, load env, run the async REPL."""
    import asyncio
    load_dotenv()

    parser = argparse.ArgumentParser(description="SRE Agent — LangGraph-powered CLI")
    parser.add_argument("--model", default=None, help="Model string (e.g. gemini/gemini-2.0-flash)")
    parser.add_argument("--thread", default="default", help="LangGraph thread ID")
    args = parser.parse_args()

    asyncio.run(_main_async(args.thread, args.model))


if __name__ == "__main__":
    main()
