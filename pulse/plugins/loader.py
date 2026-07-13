"""Plugin loader — discover and activate plugins from the user's plugins dir.

A plugin is a Python module in ``~/.pulse/plugins/<name>/plugin.py``
(or a single-file ``~/.pulse/plugins/<name>.py``) that exposes a
``register(runtime: Runtime)`` function.

Plugins can register custom tools, add skills to the registry, or hook into
the orchestrator lifecycle (pre/post run callbacks).
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from pulse.cli.runtime import Runtime

logger = logging.getLogger("pulse.plugins")
BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"


class PluginInfo:
    def __init__(self, name: str, path: Path, description: str = "", enabled: bool = True):
        self.name = name
        self.path = path
        self.description = description
        self.enabled = enabled


class PluginLoader:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = Path(plugins_dir)
        self.plugins: dict[str, PluginInfo] = {}

    def discover(self) -> list[PluginInfo]:
        self.plugins.clear()
        for base in (BUNDLED_DIR, self.plugins_dir):
            if not base.exists():
                continue
            for entry in sorted(base.iterdir()):
                name, mod_path = None, None
                if entry.is_dir():
                    p = entry / "plugin.py"
                    if p.exists():
                        name, mod_path = entry.name, p
                elif entry.suffix == ".py" and entry.stem != "__init__":
                    name, mod_path = entry.stem, entry
                if name and mod_path:
                    desc = ""
                    try:
                        src = mod_path.read_text()
                        for line in src.splitlines()[:5]:
                            if line.strip().startswith("description"):
                                desc = line.split('"', 2)[1] if '"' in line else ""
                                break
                    except Exception:
                        pass
                    self.plugins[name] = PluginInfo(name=name, path=mod_path, description=desc)
        return list(self.plugins.values())

    def activate(self, runtime: Runtime, names: Optional[list[str]] = None) -> list[str]:
        self.discover()
        activated: list[str] = []
        for name in (names or list(self.plugins.keys())):
            info = self.plugins.get(name)
            if not info or not info.enabled:
                continue
            try:
                mod = _import_from_path(f"pulse_plugin_{name}", info.path)
                if hasattr(mod, "register"):
                    mod.register(runtime)
                activated.append(name)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"plugin '{name}' failed: {e}")
        return activated


def _import_from_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
