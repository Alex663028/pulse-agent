"""TUI gateway — Rich-powered interactive terminal chat.

Slash commands:
  /help   /skills   /memory recall|add   /model   /clear   /quit  /exit
"""
from __future__ import annotations

import shlex
import textwrap

from rich.console import Console
from rich.panel import Panel

from pulse.cli.runtime import Runtime
from pulse.gateways.base import Gateway

BANNER = r"""
  ┌── Pulse ──────────────────────────────┐
  │   Hermes-style self-improving agent   │
  │   type /help for commands             │
  └───────────────────────────────────────┘
"""


def _wrap(text: str, width: int = 80) -> str:
    return "\n".join(textwrap.fill(line, width) for line in text.splitlines())


class TuiGateway(Gateway):
    name = "tui"

    def __init__(self):
        self._active = False
        self._console = Console()

    def start(self, runtime: Runtime) -> None:
        from pulse.skills.states import DECISION_TO_STATUS

        self._active = True
        console = self._console
        console.print(Panel.fit(BANNER.strip(), border_style="cyan"))
        mem_len = len(runtime.memory.read_memory())
        skills = runtime.registry.list()
        console.print(f"[dim]memory={mem_len}B  skills={len(skills)}  provider={runtime.settings.model.provider}[/dim]")
        session: str | None = None

        while self._active:
            try:
                raw = console.input("[bold cyan]>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not raw:
                continue
            if raw.startswith("/"):
                self._handle_slash(raw, runtime, console)
                continue
            console.print("[dim]…[/dim]", end="\r")
            res = runtime.orchestrator.run(raw, session_id=session)
            session = session or res.session_id
            if res.success:
                panel = Panel(_wrap(res.answer or "(empty)"), title="Pulse", border_style="green")
                console.print(panel)
                if res.candidate_skill:
                    console.print(f"[cyan]↳ proposed candidate skill:[/cyan] {res.candidate_skill}  [dim](pulse skills eval {res.candidate_skill})[/dim]")
            else:
                console.print(f"[red]error:[/red] {res.error or 'failed'}")
            console.print(f"[dim]tokens={res.token_usage}  trace={res.trace_id}[/dim]")

        self._active = False

    def stop(self) -> None:
        self._active = False

    def _handle_slash(self, raw: str, runtime: Runtime, console: Console) -> None:
        parts = shlex.split(raw)
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd in ("/quit", "/exit", "/q"):
            self._active = False
            console.print("[dim]bye[/dim]")
        elif cmd == "/help":
            console.print("  /help  /skills  /memory recall|add <text>  /model  /clear  /quit")
        elif cmd == "/skills":
            rows = runtime.registry.list()
            if not rows:
                console.print("[yellow]no skills[/yellow]")
            else:
                for r in rows:
                    flag = {"promoted": "[green]★[/green]", "candidate": "[yellow]◦[/yellow]", "deprecated": "[dim]✗[/dim]"}.get(r["status"], "?")
                    console.print(f"  {flag} [bold]{r['name']}[/bold]@{r['version']}  {r['description'][:60]}")
        elif cmd == "/memory":
            sub = args[0] if args else ""
            val = " ".join(args[1:]) if len(args) > 1 else ""
            if sub == "recall":
                hits = runtime.memory.recall(val, limit=5)
                for h in hits:
                    console.print(f"  [dim]{h.get('session_id','?')}[/dim] {h.get('content','')[:200]}")
            elif sub == "add":
                runtime.memory.add_note(val)
                console.print("[green]✓ noted.[/green]")
            else:
                console.print("[yellow]usage: /memory recall|add <text>[/yellow]")
        elif cmd == "/model":
            m = runtime.settings.model
            console.print(f"  provider={m.provider}  model={m.model}  base_url={m.base_url}")
        elif cmd == "/clear":
            console.print("[dim]session reset[/dim]")
        else:
            console.print(f"[red]unknown: {cmd} — /help[/red]")
