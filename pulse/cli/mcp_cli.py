"""``pulse mcp`` command group — manage MCP (Model Context Protocol) server configs."""

from __future__ import annotations

import json

from rich.console import Console
from rich.table import Table

from pulse.config.settings import MCPServerConfig, save_settings

console = Console()


def _load_settings():
    from pulse.config.settings import load_settings

    return load_settings()


def cmd_list(settings) -> None:
    """List configured MCP servers."""
    servers = settings.mcp_servers
    if not servers:
        console.print("[yellow]No MCP servers configured.[/yellow]")
        console.print("Add one with: [bold]pulse mcp add <name> <command> [args...][/bold]")
        return
    table = Table(title="MCP Servers")
    table.add_column("Name", style="cyan")
    table.add_column("Command")
    table.add_column("Args")
    table.add_column("Enabled")
    for s in servers:
        table.add_row(s.name, s.command, " ".join(s.args), "yes" if s.enabled else "no")
    console.print(table)


def cmd_add(settings, name: str, command: str, args: list[str]) -> None:
    """Add a new MCP server config and persist it."""
    if any(s.name == name for s in settings.mcp_servers):
        console.print(f"[red]A server named '{name}' already exists.[/red]")
        return
    cfg = MCPServerConfig(name=name, command=command, args=list(args), enabled=True)
    settings.mcp_servers.append(cfg)
    save_settings(settings)
    console.print(f"[green]✓ Added MCP server[/green] '{name}' → {command} {' '.join(args)}")


def cmd_remove(settings, name: str) -> None:
    """Remove an MCP server config by name."""
    before = len(settings.mcp_servers)
    settings.mcp_servers = [s for s in settings.mcp_servers if s.name != name]
    if len(settings.mcp_servers) == before:
        console.print(f"[red]No server named '{name}' found.[/red]")
        return
    save_settings(settings)
    console.print(f"[green]✓ Removed MCP server[/green] '{name}'")


def cmd_test(settings, name: str | None = None) -> None:
    """Attempt to connect to (a) server(s) and list their tools."""
    from pulse.mcp import MCPClient, MCPError

    targets = [s for s in settings.mcp_servers if s.enabled and (name is None or s.name == name)]
    if not targets:
        console.print("[yellow]No matching enabled MCP servers.[/yellow]")
        return
    for s in targets:
        console.print(f"[bold cyan]{s.name}[/bold cyan] ({s.command} {' '.join(s.args)})")
        try:
            with MCPClient(command=s.command, args=list(s.args)) as client:
                specs = client.list_tools()
                if not specs:
                    console.print("  [dim]no tools exposed[/dim]")
                    continue
                for spec in specs:
                    console.print(f"  • [green]{spec.get('name')}[/green]: {spec.get('description', '')[:60]}")
        except MCPError as e:
            console.print(f"  [red]connection failed:[/red] {e}")
        except Exception as e:  # noqa: BLE001
            console.print(f"  [red]error:[/red] {e}")


def cmd_export(settings) -> None:
    """Print the MCP server configs as JSON (for sharing / backup)."""
    data = [s.model_dump() for s in settings.mcp_servers]
    console.print(json.dumps(data, indent=2, ensure_ascii=False))
