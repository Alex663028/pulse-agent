"""Skills subcommands: list / install / eval / promote / rollback."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from pulse.cli.runtime import Runtime
from pulse.llm.provider import LLMMessage
from pulse.skills.evaluator import RunOutcome, SkillEvaluator
from pulse.skills.hub import install_skill
from pulse.skills.versioning import rollback as do_rollback
from pulse.skills.versioning import snapshot as do_snapshot

console = Console()

BUILTIN_GOLDEN = [
    "summarize the quarterly report",
    "draft a follow-up email to the client",
    "plan a 3-step migration of the database",
]


def _est(text: str) -> int:
    import re

    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return max(1, cjk + (len(text) - cjk) // 4)


def default_runner(rt: Runtime):
    """Build a default ``Runner`` that evaluates a skill by chatting with ``rt.router``."""
    def run(skill, task: str) -> RunOutcome:
        try:
            resp = rt.router.chat(
                [
                    LLMMessage(role="system", content=skill.body or skill.description),
                    LLMMessage(role="user", content=task),
                ]
            )
            return RunOutcome(success=bool(resp.content.strip()), tokens=resp.usage.total or _est(resp.content), steps=1)
        except (RuntimeError, OSError, ValueError):
            return RunOutcome(success=False, tokens=0, steps=1)

    return run


def cmd_list(rt: Runtime) -> None:
    """Print the table of registered skills."""
    rows = rt.registry.list()
    if not rows:
        console.print("[yellow]No skills found. Install one or run a task to evolve one.[/yellow]")
        return
    t = Table(title="Skills")
    t.add_column("name")
    t.add_column("status")
    t.add_column("version")
    t.add_column("description")
    for r in rows:
        t.add_row(r["name"], r["status"], r["version"], r["description"][:60])
    console.print(t)


def cmd_install(rt: Runtime, location: str) -> None:
    """Install a skill from ``location`` (path or git URL) and print the result."""
    name = install_skill(rt.registry, location, rt.settings)
    console.print(f"[green]✓ Installed skill:[/green] {name}")


def cmd_eval(rt: Runtime, name: str, golden: Optional[str], baseline: Optional[str]) -> None:
    """Evaluate ``name`` against golden tasks (optional ``baseline``), apply the decision and print the report."""
    rec = rt.registry.get(name)
    if not rec:
        console.print(f"[red]Skill not found:[/red] {name}")
        return
    tasks = BUILTIN_GOLDEN
    if golden and Path(golden).exists():
        tasks = [l.strip() for l in Path(golden).read_text(encoding="utf-8").splitlines() if l.strip()]
    base_rec = rt.registry.get(baseline) if baseline else None
    evaluator = SkillEvaluator(rt.registry)
    result = evaluator.evaluate(rec, default_runner(rt), tasks, base_rec)
    evaluator.apply(result, rec)
    console.print(f"\n[bold]Eval:[/bold] {name}")
    console.print(f"  runs={result.runs}  success_rate={result.success_rate:.2f}  "
                  f"avg_tokens={result.avg_tokens:.0f}  avg_steps={result.avg_steps:.1f}")
    if result.baseline_success_rate is not None:
        console.print(f"  baseline={result.baseline_success_rate:.2f}  delta={result.delta_success:+.2f}")
    color = {"promote": "green", "quarantine": "yellow", "rollback": "red", "deprecate": "red", "refine": "cyan"}[result.decision]
    console.print(f"  [bold {color}]decision: {result.decision}[/bold {color}] — {result.reason}")


def cmd_promote(rt: Runtime, name: str) -> None:
    """Snapshot ``name`` and mark it as promoted."""
    rec = rt.registry.get(name)
    if not rec:
        console.print(f"[red]Skill not found:[/red] {name}")
        return
    do_snapshot(rt.registry, name)
    rt.registry.update_status(name, "promoted")
    console.print(f"[green]✓ Promoted:[/green] {name} (status=promoted)")


def cmd_rollback(rt: Runtime, name: str, to_version: Optional[str]) -> None:
    """Roll the skill ``name`` back to ``to_version`` (or the latest promoted) and print the result."""
    rec = do_rollback(rt.registry, name, to_version)
    if rec:
        console.print(f"[green]✓ Rolled back:[/green] {name} -> {rec.version} (status=promoted)")
    else:
        console.print(f"[red]No version to roll back to for[/red] {name}")
