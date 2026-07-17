"""Pulse CLI — Typer + Rich.

Commands:
  init                 zero-config setup wizard
  doctor               self-check
  chat <task>          run a task through the orchestrator
  tui                  interactive terminal chat
  serve                start all gateways + scheduler (TUI + Telegram + cron)
  fork <task>          decompose a complex task into parallel sub-agents
  memory recall|add    FTS5 cross-session memory
  memory profile       dialectical user model refinement
  skills list|install|eval|promote|rollback
  cron list|add|remove|pause|resume  manage scheduled jobs
  rl export            export trajectories for RL training
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from pulse.cli import skills_cli
from pulse.cli.doctor import run_doctor
from pulse.cli.init_wizard import run_init
from pulse.cli.runtime import bootstrap

app = typer.Typer(help="Pulse — a Hermes-style self-improving personal agent (reliability-first).", no_args_is_help=True)
skills_app = typer.Typer(help="Manage skills.")
cron_app = typer.Typer(help="Manage scheduled cron jobs.")
rl_app = typer.Typer(help="RL training data pipeline.")
plugin_app = typer.Typer(help="Manage plugins.")
web_app = typer.Typer(help="Web UI — session management dashboard on port 10000.")
app.add_typer(skills_app, name="skills")
app.add_typer(cron_app, name="cron")
app.add_typer(rl_app, name="rl")
app.add_typer(plugin_app, name="plugin")
app.add_typer(web_app, name="web")

mcp_app = typer.Typer(help="Manage Model Context Protocol (MCP) servers.")
app.add_typer(mcp_app, name="mcp")
console = Console()

# persistent cron store (JSON file in config dir)
_CRON_FILE = "cron_jobs.json"


def _cron_path(rt) -> str:
    return str(rt.settings.config_dir / _CRON_FILE)


def _load_cron(rt) -> dict[str, dict]:
    p = _cron_path(rt)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_cron(rt, jobs: dict) -> None:
    with open(_cron_path(rt), "w") as f:
        json.dump(jobs, f, indent=2)


@app.command()
def init(
    provider: str = typer.Option(None, help="ollama|openai|openrouter|deepseek|mock"),
    model: str = typer.Option(None, help="model name, e.g. qwen2.5:7b"),
    api_key: str = typer.Option(None, help="API key for cloud providers"),
    base_url: str = typer.Option(None, "--base-url", help="Custom OpenAI-compatible endpoint base URL (e.g. https://my-gateway.example.com/v1)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="non-interactive with defaults"),
):
    """Configure Pulse (zero-config, defaults to local Ollama).

    Use ``--base-url`` to point at any OpenAI-protocol-compatible endpoint:
    a self-hosted gateway, a proxy, or an alternative vendor. Built-in
    ``openai``/``openrouter``/``deepseek`` will then call your endpoint
    instead of the official vendor URL.
    """
    from pulse.config.settings import load_settings

    run_init(load_settings(), provider=provider, model=model, api_key=api_key, base_url=base_url, non_interactive=yes)


@app.command()
def doctor():
    """Run a self-check."""
    rt = bootstrap()
    checks = run_doctor(rt.settings)
    ok = all(c.ok for c in checks)
    for c in checks:
        mark = "[green]✓[/green]" if c.ok else "[red]✗[/red]"
        console.print(f"  {mark} {c.name}: {c.detail}")
    color = "green" if ok else "red"
    msg = "All checks passed" if ok else "Some checks failed"
    console.print(f"\n[bold {color}]{msg}[/bold {color}]")


@app.command()
def chat(
    task: str = typer.Argument(..., help="the task or message"),
    session: str = typer.Option(None, help="resume a session id"),
    stream: bool = typer.Option(False, "--stream", "-s", help="Show streaming output as LLM responds"),
):
    """Run a task through the orchestrator."""
    rt = bootstrap(load_mcp=True)
    if stream:
        # Streaming mode: show tokens as they arrive
        console.print("[dim]Streaming...[/dim]")
        answer_parts = []
        for chunk in rt.orchestrator.run_stream(task, session_id=session):
            if chunk.content:
                console.print(chunk.content, end="", soft_wrap=True, style="cyan")
                answer_parts.append(chunk.content)
            if chunk.tool_calls:
                for tc in chunk.tool_calls:
                    console.print(f"\n[dim]→ tool: {tc.name}({tc.arguments})[/dim]")
        console.print()  # newline
    else:
        # Non-streaming mode with spinner
        with console.status("[cyan]Thinking…[/cyan]"):
            res = rt.orchestrator.run(task, session_id=session)
        if res.used_skills:
            console.print(f"[dim]skills:[/dim] {', '.join(res.used_skills)}")
        if res.candidate_skill:
            console.print(f"[cyan]↳ proposed candidate skill:[/cyan] {res.candidate_skill} (run `pulse skills eval {res.candidate_skill}`)")
        if res.success:
            console.print(Panel(res.answer or "(no content)", title="Pulse", border_style="green"))
        else:
            console.print(Panel(res.error or "failed", title="Pulse", border_style="red"))
        console.print(f"[dim]tokens={res.token_usage} trace={res.trace_id}[/dim]")


@app.command()
def tui():
    """Start interactive terminal chat."""
    from pulse.gateways.tui import TuiGateway

    TuiGateway().start(bootstrap(load_mcp=True))


@app.command()
def serve(
    tui_flag: bool = typer.Option(True, "--tui/--no-tui", help="enable TUI gateway"),
    telegram_flag: bool = typer.Option(False, "--telegram/--no-telegram", help="enable Telegram gateway"),
):
    """Start all configured gateways + scheduler (TUI + Telegram + cron)."""
    from pulse.gateways.base import GatewayManager
    from pulse.gateways.telegram import TelegramGateway
    from pulse.gateways.tui import TuiGateway
    from pulse.scheduler.cron import Scheduler

    rt = bootstrap(load_mcp=True)
    mgr = GatewayManager()
    if tui_flag:
        mgr.add(TuiGateway())
    if telegram_flag:
        mgr.add(TelegramGateway())

    sched = Scheduler()
    cron_jobs = _load_cron(rt)
    for name, spec in cron_jobs.items():
        interval = spec.get("interval", 3600)
        task = spec.get("task", name)

        def _make_job(t: str):
            return lambda: rt.orchestrator.run(t)

        sched.add(name, interval, _make_job(task))

    if mgr.gateways:
        console.print(f"[cyan]Starting gateways:[/cyan] {', '.join(g.name for g in mgr.gateways)}")
        mgr.start_all(rt)
    if cron_jobs:
        console.print(f"[cyan]Starting cron jobs:[/cyan] {len(cron_jobs)}")
        sched.start()
    console.print("[dim]Ctrl-C to stop[/dim]")
    try:
        # signal.pause() is unavailable on Windows; use an Event instead.
        import threading
        threading.Event().wait()
    except (KeyboardInterrupt, AttributeError):
        pass
    sched.stop()
    mgr.stop_all()
    console.print("[dim]shut down[/dim]")


@app.command()
def fork(
    task: str = typer.Argument(..., help="complex task to decompose and parallelise"),
    workers: int = typer.Option(5, help="max parallel sub-agents"),
):
    """Decompose a complex task into parallel sub-agents, merge results."""
    from pulse.orchestrator.subagent import (
        RecursionContext,
        SubagentPool,
        SubagentTask,
        decompose,
        merge_results,
    )

    rt = bootstrap(load_mcp=True)
    console.print(f"[cyan]Decomposing:[/cyan] {task[:80]}")
    subs = decompose(task, llm=rt.router.primary)
    console.print(f"[dim]{len(subs)} sub-tasks → {workers} workers[/dim]")
    pool = SubagentPool(max_workers=workers)
    tasks = [
        SubagentTask(id=f"sub_{i}", description=s, context=f"Part {i+1}/{len(subs)}") for i, s in enumerate(subs)
    ]
    with console.status("[cyan]Sub-agents running…[/cyan]"):
        results = pool.run(tasks, primary=rt.router.primary, tools=rt.tools, recursive=RecursionContext(router=rt.router, tools=rt.tools))
    for r in results:
        icon = "[green]✓[/green]" if r.success else "[red]✗[/red]"
        console.print(f"  {icon} {r.task_id}  tokens={r.tokens}  {r.elapsed:.1f}s")
    console.print("[cyan]Merging…[/cyan]")
    merged = merge_results(task, results, llm=rt.router.primary)
    console.print(Panel(merged[:3000], title="Pulse (forked)", border_style="blue"))


@app.command()
def team(
    task: str = typer.Argument(..., help="complex task for the multi-agent team"),
    rounds: int = typer.Option(2, help="max build-review-refine rounds"),
    workers: int = typer.Option(3, help="max parallel builders"),
):
    """Run a multi-agent team (Builder → Reviewer → Ship)."""
    from pulse.team.orchestrator import TeamOrchestrator

    rt = bootstrap(load_mcp=True)
    console.print(f"[cyan]Team running:[/cyan] {task[:80]}")
    tm = TeamOrchestrator(max_rounds=rounds, max_workers=workers)
    with console.status("[cyan]Builder agents working…[/cyan]"):
        result = tm.run(task, primary=rt.router.primary, tools=rt.tools)
    console.print(
        Panel(
            result.answer[:3000] if result.success else f"[red]Reviewer:[/red] {result.reviewer_notes[:2000]}",
            title=f"Team result (rounds={result.rounds} {'✓' if result.success else '✗'})",
            border_style="green" if result.success else "yellow",
        )
    )
    if result.reviewer_notes:
        console.print(f"[dim]reviewer: {result.reviewer_notes[:200]}[/dim]")


# ---- skills subcommands ----
@skills_app.command("list")
def skills_list():
    """List installed skills."""
    skills_cli.cmd_list(bootstrap())


@skills_app.command("install")
def skills_install(location: str = typer.Argument(..., help="path or git URL to a skill")):
    """Install a skill from the ecosystem."""
    skills_cli.cmd_install(bootstrap(), location)


@skills_app.command("eval")
def skills_eval(
    name: str = typer.Argument(...),
    golden: str = typer.Option(None, help="file with one task per line"),
    baseline: str = typer.Option(None, help="baseline skill name to compare against"),
):
    """Evaluate a candidate skill against a golden task set."""
    skills_cli.cmd_eval(bootstrap(), name, golden, baseline)


@skills_app.command("promote")
def skills_promote(name: str = typer.Argument(...)):
    """Promote a skill to production status."""
    skills_cli.cmd_promote(bootstrap(), name)


@skills_app.command("rollback")
def skills_rollback(name: str = typer.Argument(...), to: str = typer.Option(None, "--to")):
    """Roll a skill back to a previous version."""
    skills_cli.cmd_rollback(bootstrap(), name, to)


# ---- cron subcommands ----
@cron_app.command("list")
def cron_list():
    """List scheduled cron jobs."""
    rt = bootstrap()
    jobs = _load_cron(rt)
    if not jobs:
        console.print("[yellow]No cron jobs.[/yellow]")
        return
    for name, spec in jobs.items():
        console.print(f"  [bold]{name}[/bold]  every {spec['interval']}s  task: {spec.get('task','')[:80]}")


@cron_app.command("add")
def cron_add(
    task: str = typer.Argument(..., help="the task text to run periodically"),
    interval: int = typer.Argument(..., help="interval in seconds"),
    name: str = typer.Option("", help="job name (auto-generated if empty)"),
):
    """Add a scheduled cron job."""
    rt = bootstrap()
    jobs = _load_cron(rt)
    job_name = name or task.replace(" ", "-")[:40].lower()
    jobs[job_name] = {"task": task, "interval": interval}
    _save_cron(rt, jobs)
    console.print(f"[green]✓ added:[/green] {job_name} every {interval}s")


@cron_app.command("remove")
def cron_remove(name: str = typer.Argument(..., help="job name to remove")):
    """Remove a scheduled cron job."""
    rt = bootstrap()
    jobs = _load_cron(rt)
    if name not in jobs:
        console.print(f"[red]not found:[/red] {name}")
        return
    del jobs[name]
    _save_cron(rt, jobs)
    console.print(f"[green]✓ removed:[/green] {name}")


@cron_app.command("pause")
def cron_pause(name: str = typer.Argument(..., help="job name to pause")):
    """Pause a cron job (it will not fire until resumed)."""
    rt = bootstrap()
    jobs = _load_cron(rt)
    if name not in jobs:
        console.print(f"[red]not found:[/red] {name}")
        return
    jobs[name]["paused"] = True
    _save_cron(rt, jobs)
    console.print(f"[yellow]⏸ paused:[/yellow] {name}")


@cron_app.command("resume")
def cron_resume(name: str = typer.Argument(..., help="job name to resume")):
    """Resume a paused cron job."""
    rt = bootstrap()
    jobs = _load_cron(rt)
    if name not in jobs:
        console.print(f"[red]not found:[/red] {name}")
        return
    jobs[name].pop("paused", None)
    _save_cron(rt, jobs)
    console.print(f"[green]▶ resumed:[/green] {name}")


@app.command()
def memory(
    action: str = typer.Argument(..., help="recall|add|profile"),
    query: str = typer.Argument(None, help="query (recall/add) or sub-action (profile: reflect|history|rollback)"),
    limit: int = typer.Option(5, help="recall result limit"),
    version: int = typer.Option(None, help="version number for rollback"),
):
    """Cross-session memory (FTS5) and dialectical user modeling."""
    rt = bootstrap()
    if action == "recall":
        hits = rt.memory.recall(query or "", limit=limit)
        if not hits:
            console.print("[yellow]No memory matches.[/yellow]")
        for h in hits:
            console.print(f"[dim]{h.get('session_id','?')}[/dim] {h.get('content','')[:160]}")
    elif action == "add":
        rt.memory.add_note(query or "")
        console.print("[green]✓ noted.[/green]")
    elif action == "profile":
        from pulse.memory.dialectic import DialecticEngine

        eng = DialecticEngine(rt.memory, rt.storage, rt.router.primary)
        sub = (query or "").strip().lower()
        if sub in ("reflect", "refine", ""):
            console.print("[cyan]Dialectical reflection…[/cyan]")
            result = eng.reflect()
            if result:
                console.print(Panel(result[:2000], title="Updated USER.md", border_style="cyan"))
                console.print("[green]✓ profile refined (previous version snapshot kept)[/green]")
            else:
                console.print("[yellow]No changes (profile unchanged)[/yellow]")
        elif sub == "history":
            hist = eng.history()
            if not hist:
                console.print("[yellow]No version history[/yellow]")
            for h in hist:
                console.print(f"  v{h['version']}  {h['size']}B  {h['path']}")
        elif sub == "rollback":
            eng.rollback(version)
            console.print(f"[green]✓ rolled back to v{version or 'latest snapshot'}[/green]")
        else:
            console.print("[red]profile action must be: reflect, history, rollback[/red]")
    else:
        console.print("[red]action must be 'recall', 'add', or 'profile'[/red]")


# ---- rl subcommands ----
@rl_app.command("export")
def rl_export(
    out: str = typer.Option("trajectories.jsonl", "--out", "-o", help="output file path"),
    fmt: str = typer.Option("jsonl", "--format", "-f", help="jsonl|sharegpt"),
    since: str = typer.Option(None, help="ISO date filter (e.g. 2026-01-01)"),
    outcome: bool = typer.Option(None, help="filter by outcome (True=success)"),
    skill: str = typer.Option(None, help="filter by skill name"),
    limit: int = typer.Option(500, help="max records"),
):
    """Export stored trajectories for RL fine-tuning."""
    from pulse.rl.export import export_jsonl, export_sharegpt

    rt = bootstrap()
    if fmt == "sharegpt":
        n = export_sharegpt(rt.storage, out, since=since, outcome=outcome, skill=skill, limit=limit)
    else:
        n = export_jsonl(rt.storage, out, since=since, outcome=outcome, skill=skill, limit=limit)
    console.print(f"[green]✓ exported {n} trajectories → {out}[/green]")


# ---- analytics subcommands ----
analytics_app = typer.Typer(help="Usage analytics and insights.")
app.add_typer(analytics_app, name="insights")


@analytics_app.command()
def insights(
    days: int = typer.Option(30, "--days", "-d", help="Number of days to analyze"),
):
    """Display usage analytics (sessions, tokens, success rate)."""
    from pulse.analytics import UsageInsights

    rt = bootstrap()
    usage = UsageInsights(rt.storage, rt.settings)
    console.print(Panel(usage.insights_text(days), title="Pulse Analytics", border_style="cyan"))


@analytics_app.command("curator")
def curator(
    action: str = typer.Option("status", help="status|run|archive"),
    name: str = typer.Option(None, help="skill name"),
):
    """Skill curator: background maintenance for agent-created skills."""
    from pulse.skills.curator import SkillCurator

    rt = bootstrap()
    curator = SkillCurator(rt.settings.skills_dir)
    if action == "status":
        stats = curator.get_stats(name)
        if name:
            if stats:
                console.print(f"[bold]{name}[/bold]")
                for k, v in stats.items():
                    console.print(f"  {k}: {v}")
            else:
                console.print(f"[yellow]No stats for {name}[/yellow]")
        else:
            all_stats = curator.get_stats()
            if not all_stats:
                console.print("[yellow]No skills tracked yet.[/yellow]")
            for s in all_stats:
                console.print(f"  [bold{s['name']}[/bold] state={s['state']} uses={s['use_count']}")
    elif action == "run":
        report = curator.run_maintenance(registry=rt.registry)
        console.print(f"[green]✓ maintenance complete:[/green] {report}")
    elif action == "archive":
        if not name:
            console.print("[red]--name required[/red]")
            return
        curator.pin(name)  # Use pin as "do not archive" toggle


@plugin_app.command("list")
def plugin_list():
    """List available plugins."""
    from pulse.plugins.loader import PluginLoader

    rt = bootstrap()
    pl = PluginLoader(rt.settings.config_dir / "plugins")
    plugins = pl.discover()
    if not plugins:
        console.print("[yellow]No plugins found.[/yellow]")
        return
    for p in plugins:
        console.print(f"  [bold]{p.name}[/bold]  {p.description}  [dim]{p.path}[/dim]")


@plugin_app.command("install")
def plugin_install(path: str = typer.Argument(..., help="path to plugin directory or .py file")):
    """Install a plugin (copy to plugins dir)."""
    import shutil

    rt = bootstrap()
    dest = rt.settings.config_dir / "plugins"
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    if src.is_file() and src.suffix == ".py":
        shutil.copy(src, dest / src.name)
    elif src.is_dir():
        shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
    else:
        console.print(f"[red]cannot find plugin:[/red] {path}")
        return
    console.print(f"[green]✓ installed:[/green] {src.name}")


@plugin_app.command("activate")
def plugin_activate(name: str = typer.Argument(..., help="plugin name to activate")):
    """Activate a discovered plugin (call its register function)."""
    from pulse.plugins.loader import PluginLoader

    rt = bootstrap()
    pl = PluginLoader(rt.settings.config_dir / "plugins")
    activated = pl.activate(rt, names=[name])
    if activated:
        console.print(f"[green]✓ activated:[/green] {', '.join(activated)}")
    else:
        console.print(f"[red]plugin not found or failed:[/red] {name}")


# ---- MCP commands -------------------------------------------------------
@mcp_app.command("list")
def mcp_list():
    """List configured MCP servers."""
    from pulse.cli.mcp_cli import cmd_list
    from pulse.config.settings import load_settings

    cmd_list(load_settings())


@mcp_app.command("add")
def mcp_add(
    name: str = typer.Argument(..., help="unique server name, used as tool prefix"),
    invocation: str = typer.Argument(
        ...,
        help='full server command as one string, e.g. "npx -y @modelcontextprotocol/server-filesystem /tmp"',
    ),
):
    """Add an MCP server (stdio).

    Pass the whole command (executable + args) as a single quoted string so
    flags like ``-y`` are preserved literally instead of being parsed as CLI options.
    """
    import shlex

    from pulse.cli.mcp_cli import cmd_add
    from pulse.config.settings import load_settings

    parts = shlex.split(invocation)
    if not parts:
        console.print("[red]empty command[/red]")
        return
    cmd_add(load_settings(), name, parts[0], parts[1:])


@mcp_app.command("remove")
def mcp_remove(name: str = typer.Argument(..., help="server name to remove")):
    """Remove an MCP server config."""
    from pulse.cli.mcp_cli import cmd_remove
    from pulse.config.settings import load_settings

    cmd_remove(load_settings(), name)


@mcp_app.command("test")
def mcp_test(name: str = typer.Argument(None, help="optional server name to filter")):
    """Connect to server(s) and list exposed tools."""
    from pulse.cli.mcp_cli import cmd_test
    from pulse.config.settings import load_settings

    cmd_test(load_settings(), name)


@mcp_app.command("export")
def mcp_export():
    """Export MCP server configs as JSON."""
    from pulse.cli.mcp_cli import cmd_export
    from pulse.config.settings import load_settings

    cmd_export(load_settings())


@web_app.command("start")
def web_start(
    port: int = typer.Option(10000, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    debug: bool = typer.Option(False, "--debug", help="Enable Flask debug mode"),
):
    """Start the Web UI dashboard on port 10000."""
    from pulse.web.server import main as web_main
    import sys
    sys.argv = ["pulse-web", "--port", str(port), "--host", host] + (["--debug"] if debug else [])
    web_main()


# ---- profile subcommands ----
profile_app = typer.Typer(help="Manage named profiles (isolated configs/sessions/skills).")
app.add_typer(profile_app, name="profile")


@profile_app.command("list")
def profile_list():
    """List available profiles."""
    profiles = ["default"]
    profiles_dir = Path.home() / ".pulse" / "profiles"
    if profiles_dir.exists():
        for d in sorted(profiles_dir.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists():
                profiles.append(d.name)
    for p in profiles:
        marker = "→ " if p == "default" else "  "
        console.print(f"{marker}{p}")


@profile_app.command("create")
def profile_create(
    name: str = typer.Argument(..., help="profile name (lowercase-hyphen)"),
):
    """Create a new profile with default config."""
    from pulse.config.settings import get_profile_dir, save_settings, Settings

    profile_dir = get_profile_dir(name)
    if profile_dir.exists():
        console.print(f"[red]profile '{name}' already exists[/red]")
        return
    profile_dir.mkdir(parents=True, exist_ok=True)
    s = Settings(config_dir=profile_dir)
    s.ensure_dirs()
    path = save_settings(s)
    console.print(f"[green]✓ created profile:[/green] {name} ({path})")


@profile_app.command("switch")
def profile_switch(
    name: str = typer.Argument(..., help="profile name"),
):
    """Show how to switch to a profile (use PULSE_PROFILE env var)."""
    console.print(f"Switch to profile '{name}' by running:")
    console.print(f"  [bold]PULSE_PROFILE={name} pulse[/bold]")
    console.print("Or set it permanently:")
    console.print(f"  [bold]echo 'export PULSE_PROFILE={name}' >> ~/.bashrc[/bold]")


# ---- docs subcommands ----
docs_app = typer.Typer(help="Open embedded documentation & tutorials.")
app.add_typer(docs_app, name="docs")


TUTORIALS = {
    "quickstart": {
        "title": "Quickstart",
        "content": """
[bold]Welcome to Pulse Agent[/bold]

1. Initialize:
   [cyan]pulse init[/cyan]
   (interactive setup wizard — defaults to local Ollama)

2. Chat:
   [cyan]pulse chat "Hello, what can you do?"[/cyan]

3. Start the Web UI:
   [cyan]pulse web start[/cyan]

4. Check health:
   [cyan]pulse doctor[/cyan]

5. Install a skill:
   [cyan]pulse skills install <path-or-url>[/cyan]

For the full feature list, see [cyan]pulse docs features[/cyan]
"""
    },
    "features": {
        "title": "Feature List",
        "content": """
[bold]Core Features:[/bold]
• Self-improving skills: candidate → promoted → rollback lifecycle
• Cross-session memory with FTS5 full-text search
• Multi-LLM routing with fallback chain
• Circuit breaker per provider (auto-failover)
• Sub-agents with parallel execution & merge
• Cron-scheduled tasks
• MCP (Model Context Protocol) server integration

[bold]Security:[/bold]
• Shell command approval (manual/smart/off modes)
• Automatic secret redaction in tool output
• Filesystem checkpoints (snapshot/restore)

[bold]Observability:[/bold]
• Usage analytics: [cyan]pulse insights[/bold]
• Skill curator: [cyan]pulse insights curator[/cyan]
• Structured traces to LangSmith/LangFuse

[bold]Multi-Profile:[/bold]
• [cyan]pulse profile list[/cyan] / [cyan]pulse profile create <name>[/cyan]
• Isolated config, sessions, skills per profile

[bold]Web UI:[/bold]
• React SPA at http://127.0.0.1:10000
• Chat, sessions, tools, skills views
"""
    },
    "security": {
        "title": "Security Model",
        "content": """
[bold]Command Approval Modes:[/cyan]
[cyan]manual[/cyan] — prompt on rm -rf, git reset --hard, chmod 777, etc.
[cyan]smart[/cyan]   — prompt only on destructive ops
[cyan]off[/cyan]     — no prompts (YOLO)

Configure in [cyan]~/.pulse/config.yaml[/cyan]:
  approval_mode: manual

[bold]Secret Redaction:[/bold]
API keys, bearer tokens, private keys are automatically redacted
in tool output. Always-on, no config needed.

[bold]Blocked Commands:[/bold]
Some commands are always blocked regardless of mode:
• rm -rf / (filesystem wipe)
• dd if=/dev/zero of=/dev/sda (disk overwrite)
"""
    }
}


@docs_app.command()
def docs(
    topic: str = typer.Option("quickstart", "--topic", "-t", help="quickstart|features|security"),
):
    """Show embedded docs/tutorial for a topic."""
    tutorial = TUTORIALS.get(topic)
    if not tutorial:
        console.print(f"[red]Unknown topic:[/red] {topic}")
        console.print(f"Available: {', '.join(TUTORIALS.keys())}")
        return
    console.print(Panel(tutorial["content"].strip(), title=tutorial["title"], border_style="blue"))


if __name__ == "__main__":
    app()
