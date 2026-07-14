"""`pulse doctor` — self-check for fast troubleshooting."""
from __future__ import annotations

import sys
import urllib.request
from typing import NamedTuple

from pulse.config.settings import Settings
from pulse.storage.engine import Storage

Check = NamedTuple("Check", [("name", str), ("ok", bool), ("detail", str)])


def run_doctor(settings: Settings) -> list[Check]:
    """Run a series of self-checks (Python, config, FTS5, storage, dirs, provider) and return the results."""
    checks: list[Check] = []
    checks.append(Check("python>=3.11", sys.version_info >= (3, 11), f"{sys.version_info.major}.{sys.version_info.minor}"))

    cfg = settings.config_dir / "config.yaml"
    checks.append(Check("config.yaml exists", cfg.exists(), str(cfg)))

    checks.append(Check("FTS5 available", Storage.has_fts5(), "SQLite FTS5" if Storage.has_fts5() else "missing"))

    # writable db
    try:
        s = Storage(settings.db_path)
        s.close()
        checks.append(Check("storage writable", True, str(settings.db_path)))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("storage writable", False, str(e)))

    # dirs
    for label, d in (("skills_dir", settings.skills_dir), ("memory_dir", settings.memory_dir)):
        checks.append(Check(label, d.exists(), str(d)))

    # provider reachability
    if settings.model.provider == "ollama":
        try:
            urllib.request.urlopen(settings.model.base_url.replace("/v1", "") + "/api/tags", timeout=1.5)
            checks.append(Check("ollama reachable", True, settings.model.base_url))
        except Exception:
            checks.append(Check("ollama reachable", False, "not running — `ollama serve`"))
    else:
        checks.append(Check(f"provider={settings.model.provider}", True, "cloud (API key in .env)"))

    return checks
