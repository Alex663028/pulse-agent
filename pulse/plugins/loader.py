"""Plugin loader — discover and activate plugins from the user's plugins dir.

A plugin is a Python module in ``~/.pulse/plugins/<name>/plugin.py``
(or a single-file ``~/.pulse/plugins/<name>.py``) that exposes a
``register(runtime: Runtime)`` function and optionally a
``__permissions__: list[str]`` declaration.

Plugins run inside a sandbox that restricts imports and builtins.
Permissions (``tools.register``, ``memory.read``, etc.) must be declared
in the source and granted at activation time.

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
from pulse.plugins.sandbox import (
    PluginSandbox,
    parse_permissions_declaration,
)

logger = logging.getLogger("pulse.plugins")
BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"

# Default permissions granted to bundled (trusted) plugins.
BUNDLED_PERMISSIONS: set[str] = {
    "tools.register",
    "memory.read",
    "memory.write",
    "skills.install",
    "scheduler.add",
    "fs.read",
    "network",
}

# Default permissions for user-installed plugins (conservative).
USER_DEFAULT_PERMISSIONS: set[str] = {
    "tools.register",
    "memory.read",
    "fs.read",
}


class PluginInfo:
    """Metadata for a discovered plugin: name, path, description, permissions, and enabled flag."""

    def __init__(
        self,
        name: str,
        path: Path,
        description: str = "",
        enabled: bool = True,
        permissions: Optional[set[str]] = None,
        bundled: bool = False,
    ):
        self.name = name
        self.path = path
        self.description = description
        self.enabled = enabled
        self.permissions: set[str] = permissions or set()
        self.bundled = bundled


class PluginLoader:
    """Discovers and activates plugins from the bundled and user plugin directories.

    Plugins run in a :class:`PluginSandbox` that enforces import restrictions
    and permission checks.
    """

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.plugins: dict[str, PluginInfo] = {}

    def discover(self) -> list[PluginInfo]:
        """Scan both bundled and user plugin dirs and return the list of discovered plugins.

        Each plugin's ``__permissions__`` are parsed from source without execution.
        """
        self.plugins.clear()
        for base, is_bundled in ((BUNDLED_DIR, True), (self.plugins_dir, False)):
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
                    perms: set[str] = set()
                    try:
                        src = mod_path.read_text()
                        for line in src.splitlines()[:5]:
                            if line.strip().startswith("description"):
                                desc = line.split('"', 2)[1] if '"' in line else ""
                                break
                        perms = parse_permissions_declaration(src)
                    except (OSError, UnicodeDecodeError):
                        pass
                    self.plugins[name] = PluginInfo(
                        name=name,
                        path=mod_path,
                        description=desc,
                        permissions=perms,
                        bundled=is_bundled,
                    )
        return list(self.plugins.values())

    def activate(
        self,
        runtime: Runtime,
        names: Optional[list[str]] = None,
        extra_permissions: Optional[set[str]] = None,
    ) -> list[str]:
        """Import and register the named plugins (or all if ``names`` is None).

        Each plugin runs inside a :class:`PluginSandbox` with permissions
        based on whether it is bundled (trusted) or user-installed.

        ``extra_permissions`` can grant additional permissions to user plugins.

        Returns the list of successfully activated plugin names.
        """
        self.discover()
        activated: list[str] = []
        for name in names or list(self.plugins.keys()):
            info = self.plugins.get(name)
            if not info or not info.enabled:
                continue

            # Determine granted permissions.
            if info.bundled:
                granted = set(BUNDLED_PERMISSIONS)
            else:
                granted = set(USER_DEFAULT_PERMISSIONS)
                if extra_permissions:
                    granted |= extra_permissions

            try:
                sandbox = PluginSandbox(granted_permissions=granted)
                mod = sandbox.exec_module(f"pulse_plugin_{name}", info.path)
                if hasattr(mod, "register"):
                    mod.register(runtime)
                activated.append(name)
                logger.info(
                    "Activated plugin '%s' (bundled=%s, perms=%s)",
                    name,
                    info.bundled,
                    sorted(info.permissions),
                )
            except PermissionError as pe:
                logger.warning("Plugin '%s' permission denied: %s", name, pe)
            except (ImportError, SyntaxError, AttributeError) as e:
                logger.warning("Plugin '%s' failed: %s", name, e)
        return activated


def _import_from_path(name: str, path: Path) -> Any:
    """Load a module from a file path (used for non-sandboxed imports in tests)."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
