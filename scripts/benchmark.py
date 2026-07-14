#!/usr/bin/env python3
"""Pulse Agent Benchmark Suite.

Measures key performance indicators:
1. **Orchestrator latency** — time to complete a single-turn task (ms).
2. **Token consumption** — average tokens used per task (input + output).
3. **Sub-agent pool throughput** — tasks completed per second with N workers.
4. **Skill evaluation speed** — time to evaluate a candidate skill (ms).
5. **Memory recall latency** — time to query FTS5 memory store (ms).

Usage::

    python scripts/benchmark.py                  # all benchmarks (mock provider)
    python scripts/benchmark.py --provider mock  # explicit mock
    python scripts/benchmark.py --provider ollama --model qwen2.5:7b  # local LLM
    python scripts/benchmark.py --quick          # fewer iterations (smoke test)
    python scripts/benchmark.py --bench latency  # only run a specific bench
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pulse.cli.runtime import Runtime

# Ensure the project root is on sys.path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------

BENCHMARKS: dict[str, str] = {
    "latency": "Orchestrator single-turn latency",
    "token": "Token consumption per task",
    "throughput": "Sub-agent pool throughput",
    "skill_eval": "Skill evaluation speed",
    "memory": "Memory recall latency",
}

TASKS = [
    "write a function that checks if a number is prime",
    "explain the difference between list and tuple in Python",
    "sort a list of dictionaries by a key",
    "calculate the factorial of 10",
    "convert a string to title case",
]


def format_ms(ms: float) -> str:
    """Format milliseconds with appropriate precision."""
    if ms < 1:
        return f"{ms * 1000:.1f}μs"
    if ms < 1000:
        return f"{ms:.1f}ms"
    return f"{ms / 1000:.2f}s"


def run_latency_bench(runtime, iterations: int = 20) -> dict:
    """Measure orchestrator single-turn latency."""
    orch = runtime.orchestrator

    times: list[float] = []
    for i, task in enumerate(TASKS * (iterations // len(TASKS) + 1)):
        if i >= iterations:
            break
        start = time.perf_counter()
        orch.run(task)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)

    return {
        "name": "orchestrator_latency",
        "iterations": len(times),
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "p95_ms": _percentile(times, 95),
        "p99_ms": _percentile(times, 99),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def run_token_bench(runtime, iterations: int = 20) -> dict:
    """Measure token consumption per task via observability events."""
    orch = runtime.orchestrator

    tokens_per_task: list[int] = []
    for i, task in enumerate(TASKS * (iterations // len(TASKS) + 1)):
        if i >= iterations:
            break
        orch.run(task)
        # Estimate tokens from the last observability token event.
        tok = 0
        for ev in reversed(runtime.obs.events):
            if ev.kind == "token_usage":
                tok = ev.data.get("total", 0)
                break
        tokens_per_task.append(tok)

    return {
        "name": "token_consumption",
        "iterations": len(tokens_per_task),
        "mean_tokens": statistics.mean(tokens_per_task),
        "median_tokens": statistics.median(tokens_per_task),
        "p95_tokens": _percentile(tokens_per_task, 95),
        "min_tokens": min(tokens_per_task),
        "max_tokens": max(tokens_per_task),
    }


def run_throughput_bench(runtime, workers: int = 4, iterations: int = 40) -> dict:
    """Measure sub-agent pool throughput (tasks/sec)."""
    from pulse.orchestrator.subagent import SubagentPool, SubagentTask, decompose

    task_descs = decompose(
        "research Python async patterns, compare asyncio vs trio, "
        "summarize pros and cons, list best practices",
        llm=runtime.router.primary,
    )

    tasks = [
        SubagentTask(
            id=f"bench-{i}",
            description=desc,
            role="researcher",
            context="Benchmark task",
            timeout=30,
        )
        for i, desc in enumerate(task_descs)
    ]

    pool = SubagentPool(max_workers=workers)
    start = time.perf_counter()

    completed = 0
    failures = 0
    total = 0
    for _ in range(iterations):
        results = pool.run(tasks, primary=runtime.router.primary, tools=runtime.tools)
        completed += len([r for r in results if r.success])
        failures += len([r for r in results if not r.success])
        total += len(results)

    elapsed = time.perf_counter() - start
    throughput = total / elapsed if elapsed > 0 else 0

    return {
        "name": "subagent_throughput",
        "workers": workers,
        "total_tasks": total,
        "completed": completed,
        "failures": failures,
        "elapsed_s": round(elapsed, 3),
        "throughput_tasks_per_sec": round(throughput, 2),
        "avg_time_per_task_ms": round((elapsed / total) * 1000, 1) if total else 0,
    }


def run_skill_eval_bench(runtime, iterations: int = 10) -> dict:
    """Measure skill evaluation speed."""
    from pulse.skills.evaluator import RunOutcome, SkillEvaluator
    from pulse.skills.loader import SkillRecord

    tmp_dir = Path(tempfile.mkdtemp(prefix="pulse_skill_bench_"))
    record = SkillRecord(
        id="bench-prime-check",
        name="bench-prime-check",
        path=tmp_dir / "SKILL.md",
        version="0.1.0",
        status="candidate",
        frontmatter={"description": "Check if a number is prime"},
        body="To check if a number is prime, test divisibility up to sqrt(n).",
    )

    golden_tasks = [
        "check if 17 is prime",
        "check if 4 is prime",
    ]

    def mock_runner(skill: SkillRecord, task: str) -> RunOutcome:
        return RunOutcome(success=True, tokens=50, steps=3)

    evaluator = SkillEvaluator(registry=runtime.registry)

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        evaluator.evaluate(record, runner=mock_runner, golden_tasks=golden_tasks)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    return {
        "name": "skill_evaluation",
        "iterations": len(times),
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "p95_ms": _percentile(times, 95),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def run_memory_bench(runtime, iterations: int = 100) -> dict:
    """Measure memory recall (FTS5) latency."""
    store = runtime.memory
    # Pre-populate with notes.
    for i in range(50):
        store.add_note(f"benchmark note {i}: the quick brown fox jumps over the lazy dog")

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        store.recall("quick brown fox")
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    return {
        "name": "memory_recall",
        "iterations": len(times),
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "p95_ms": _percentile(times, 95),
        "min_ms": min(times),
        "max_ms": max(times),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(data: list, p: float) -> float:
    """Calculate the p-th percentile of data using linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (p / 100.0) * (len(sorted_data) - 1)
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
    return sorted_data[f]


def _build_runtime(provider: str = "mock", model: str = "mock-1") -> "Runtime":
    """Build a runtime for benchmarking. Defaults to mock provider."""
    from pulse.cli.runtime import Runtime
    from pulse.config.settings import ModelSettings, Settings
    from pulse.llm.provider import MockProvider
    from pulse.llm.router import Router
    from pulse.memory.store import MemoryStore
    from pulse.orchestrator.loop import Orchestrator
    from pulse.orchestrator.observability import Observability
    from pulse.skills.registry import SkillRegistry
    from pulse.storage.engine import Storage
    from pulse.tools.builtin import register_builtin_tools
    from pulse.tools.registry import ToolRegistry

    tmp_dir = Path(tempfile.mkdtemp(prefix="pulse_bench_"))
    settings = Settings(
        config_dir=tmp_dir,
        model=ModelSettings(provider=provider, model=model),
    )
    settings.ensure_dirs()

    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)

    mock = MockProvider()
    router = Router(primary=mock)
    obs = Observability()
    orch = Orchestrator(router, memory, registry, tools, storage, settings, obs)

    return Runtime(settings, storage, memory, registry, tools, router, obs, orch)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pulse Agent Benchmark Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Available benchmarks:\n  " + "\n  ".join(f"{k}: {v}" for k, v in BENCHMARKS.items()),
    )
    parser.add_argument(
        "--bench",
        choices=list(BENCHMARKS) + ["all"],
        default="all",
        help="Which benchmark to run (default: all)",
    )
    parser.add_argument(
        "--provider",
        default="mock",
        help="LLM provider (default: mock)",
    )
    parser.add_argument(
        "--model",
        default="mock-1",
        help="Model name (default: mock-1)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run fewer iterations (smoke test mode)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    # Scale iterations for quick mode.
    scale = 0.25 if args.quick else 1.0

    runtime = _build_runtime(args.provider, args.model)

    bench_names = list(BENCHMARKS) if args.bench == "all" else [args.bench]
    results: list[dict] = []

    print(f"Pulse Benchmark Suite — provider={args.provider}, model={args.model}")
    print("=" * 60)

    for name in bench_names:
        print(f"\n[{name}] {BENCHMARKS[name]}")
        print("-" * 40)

        if name == "latency":
            r = run_latency_bench(runtime, iterations=max(5, int(20 * scale)))
        elif name == "token":
            r = run_token_bench(runtime, iterations=max(5, int(20 * scale)))
        elif name == "throughput":
            r = run_throughput_bench(runtime, workers=4, iterations=max(10, int(40 * scale)))
        elif name == "skill_eval":
            r = run_skill_eval_bench(runtime, iterations=max(3, int(10 * scale)))
        elif name == "memory":
            r = run_memory_bench(runtime, iterations=max(20, int(100 * scale)))
        else:
            continue

        results.append(r)

        if args.json:
            continue

        # Pretty-print.
        for k, v in r.items():
            if k == "name":
                continue
            if isinstance(v, float):
                if k.endswith("_ms"):
                    print(f"  {k}: {format_ms(v)}")
                else:
                    print(f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    print("\n" + "=" * 60)
    print("Benchmarks complete.")


if __name__ == "__main__":
    main()
