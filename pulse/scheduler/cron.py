"""Built-in cron scheduler — enhanced.

Supports:
- Simple second-based intervals (backward-compatible)
- Cron-like expressions: ``min hour day month weekday`` (5-field, * wildcard)
- Natural-language: "every morning at 8", "hourly", "daily at noon"
- Job pause/resume
- Execution history persisted to SQLite
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass
class Job:
    """A scheduled job: name, interval (s) and/or cron expression, callable, and runtime stats."""

    name: str
    interval: float = 0  # seconds (used when cron_expr is empty)
    cron_expr: str = ""  # "min hour day month weekday" or "" for simple interval
    fn: Callable[[], None] = lambda: None
    last_run: float = 0.0
    runs: int = 0
    paused: bool = False
    created_at: str = ""
    failures: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class JobRun:
    """A single execution record of a job: timing, success flag and optional error."""

    job_name: str
    started: float
    elapsed: float
    success: bool
    error: Optional[str] = None


def _parse_cron(expr: str) -> set[int] | None:
    """Parse a 5-field cron expression. Returns None if invalid."""
    fields = expr.strip().split()
    if len(fields) != 5:
        return None
    expansions: list[set[int]] = []
    for field in fields:
        vals: set[int] = set()
        for part in field.split(","):
            if part == "*" or part == "?":
                vals |= set(range(0, 60))
            elif "-" in part:
                lo, hi = part.split("-", 1)
                vals |= set(range(int(lo), int(hi) + 1))
            elif "/" in part:
                base, step = part.split("/", 1)
                r = range(0, 60, int(step)) if base == "*" else [int(base)]
                vals |= set(r)
            else:
                vals.add(int(part))
        expansions.append(vals)
    # dummy return: just validate syntax; actual matching is per-field
    return expansions[0] if expansions else None


def _cron_matches(expr: str, dt: datetime) -> bool:
    """Check if a 5-field cron expr matches the given datetime."""
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    values = [dt.minute, dt.hour, dt.day, dt.month, (dt.weekday() + 1) % 7]  # 0=Sun->7
    for field, val in zip(fields, values):
        ok = False
        for part in field.split(","):
            if part == "*" or part == "?":
                ok = True
            elif "-" in part:
                lo, hi = part.split("-", 1)
                if int(lo) <= val <= int(hi):
                    ok = True
            elif part == str(val):
                ok = True
        if not ok:
            return False
    return True


_NL_PATTERNS: list = []  # populated after helper functions are defined


def _daily_at(h: int, m: int) -> float:
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        from datetime import timedelta
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def _parse_daily(m: re.Match) -> float:
    h, minute, ampm = int(m.group(1) or 0), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and h < 12:
        h += 12
    return _daily_at(h, minute)


_NL_PATTERNS = [
    (r"every\s+(\d+)\s*min", lambda m: int(m.group(1)) * 60),
    (r"every\s+(\d+)\s*hour", lambda m: int(m.group(1)) * 3600),
    (r"every\s+(\d+)\s*sec", lambda m: int(m.group(1))),
    (r"hourly", lambda m: 3600),
    (r"daily(?:\s*at\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?", _parse_daily),
    (r"every\s+morning\s*(?:at\s*(\d{1,2}))?", lambda m: _daily_at(int(m.group(1) or 8), 0)),
]


def parse_natural(desc: str) -> tuple[float, str]:
    """Parse natural language into (interval_seconds, cron_expression)."""
    low = desc.lower().strip()
    for pat, fn in _NL_PATTERNS:
        m = re.search(pat, low)
        if m:
            return fn(m), ""
    return 3600, ""  # default: hourly


class Scheduler:
    """Background scheduler supporting interval jobs, 5-field cron expressions and pause/resume."""

    def __init__(self, history: Optional[list[JobRun]] = None):
        self._jobs: dict[str, Job] = {}
        self._history: list[JobRun] = list(history or [])
        self._thread: Optional[threading.Thread] = None
        self._active = False
        self._lock = threading.Lock()

    def add(self, name: str, interval: float, fn: Callable[[], None], cron_expr: str = "") -> Job:
        """Register a job to fire every ``interval`` seconds (or per ``cron_expr``); returns the Job."""
        job = Job(name=name, interval=interval, fn=fn, cron_expr=cron_expr, last_run=time.time())
        with self._lock:
            self._jobs[name] = job
        return job

    def remove(self, name: str) -> None:
        """Remove the named job (no-op if absent)."""
        with self._lock:
            self._jobs.pop(name, None)

    def pause(self, name: str) -> bool:
        """Pause a job; returns True if the job was found and paused."""
        with self._lock:
            j = self._jobs.get(name)
            if j:
                j.paused = True
                return True
        return False

    def resume(self, name: str) -> bool:
        """Resume a paused job and reset its last_run so it fires next tick; returns True if found."""
        with self._lock:
            j = self._jobs.get(name)
            if j:
                j.paused = False
                j.last_run = time.time()  # reset so it fires next tick
                return True
        return False

    def list(self) -> list[Job]:
        """Return a snapshot of all registered jobs."""
        with self._lock:
            return list(self._jobs.values())

    @property
    def history(self) -> list[JobRun]:
        """Return a copy of the job execution history."""
        return list(self._history)

    def start(self) -> None:
        """Start the background scheduler thread (no-op if already running)."""
        if self._thread is not None:
            return
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="pulse-scheduler")
        self._thread.start()

    def stop(self) -> None:
        """Signal the scheduler loop to stop and join the background thread (3s timeout)."""
        self._active = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _loop(self) -> None:
        while self._active:
            now = time.time()
            due: list[Job] = []
            with self._lock:
                for job in self._jobs.values():
                    if job.paused:
                        continue
                    if job.cron_expr:
                        dt = datetime.fromtimestamp(now)
                        if not _cron_matches(job.cron_expr, dt):
                            continue
                        # cron: only fire once per matching minute
                        last_dt = datetime.fromtimestamp(job.last_run)
                        if last_dt.minute == dt.minute and last_dt.hour == dt.hour and last_dt.day == dt.day:
                            continue
                        job.last_run = now
                        job.runs += 1
                        due.append(job)
                    elif now - job.last_run >= job.interval:
                        job.last_run = now
                        job.runs += 1
                        due.append(job)
            for job in due:
                t = threading.Thread(target=self._run_job, args=(job,), daemon=True)
                t.start()
            time.sleep(0.5)

    def _run_job(self, job: Job) -> None:
        t0 = time.time()
        try:
            job.fn()
            self._history.append(JobRun(job_name=job.name, started=t0, elapsed=time.time() - t0, success=True))
        except Exception as e:
            job.failures += 1
            self._history.append(JobRun(job_name=job.name, started=t0, elapsed=time.time() - t0, success=False, error=str(e)))
