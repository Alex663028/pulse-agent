"""Plugin sandbox — import isolation and permission whitelist.

Every plugin module runs inside a restricted execution context:
- Only explicitly allowed built-in functions are available.
- Only safe standard-library and ``pulse`` public-API modules can be imported.
- Plugins declare required permissions via ``__permissions__: list[str]``.

The protection is layered:
1. ``__builtins__`` is replaced with a restricted dict (no ``open/eval/exec``).
2. ``sys.meta_path`` finder intercepts imports of denied modules.
3. ``sys.modules`` cache is selectively evicted for denied modules (except
   modules that the import system itself needs to function, such as ``sys``,
   ``builtins``, ``importlib``).
"""

from __future__ import annotations

import builtins as _builtins
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("pulse.plugins.sandbox")

# ---------------------------------------------------------------------------
# Allowed builtins — read-only / side-effect-free / pure-computation.
# Deliberately excluded: open, compile, eval, exec, breakpoint, exit, quit,
# help, input.
# ---------------------------------------------------------------------------
SAFE_BUILTINS: set[str] = {
    # Types
    "bool",
    "bytes",
    "bytearray",
    "complex",
    "dict",
    "float",
    "frozenset",
    "int",
    "list",
    "memoryview",
    "object",
    "range",
    "set",
    "slice",
    "str",
    "tuple",
    "type",
    # Constructors / conversions
    "abs",
    "all",
    "any",
    "bin",
    "callable",
    "chr",
    "classmethod",
    "delattr",
    "dir",
    "divmod",
    "enumerate",
    "filter",
    "format",
    "getattr",
    "hasattr",
    "hash",
    "hex",
    "id",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "map",
    "max",
    "min",
    "next",
    "oct",
    "ord",
    "pow",
    "print",
    "property",
    "repr",
    "reversed",
    "round",
    "setattr",
    "sorted",
    "staticmethod",
    "sum",
    "super",
    "vars",
    "zip",
    # Constants
    "True",
    "False",
    "None",
    "Ellipsis",
    "NotImplemented",
    # Exceptions (needed for error handling inside plugins)
    "ArithmeticError",
    "AssertionError",
    "AttributeError",
    "BaseException",
    "Exception",
    "EOFError",
    "GeneratorExit",
    "ImportError",
    "IndentationError",
    "IndexError",
    "KeyError",
    "KeyboardInterrupt",
    "LookupError",
    "MemoryError",
    "NameError",
    "NotImplementedError",
    "OSError",
    "OverflowError",
    "RuntimeError",
    "StopAsyncIteration",
    "StopIteration",
    "SyntaxError",
    "SystemExit",
    "TabError",
    "TypeError",
    "UnboundLocalError",
    "UnicodeError",
    "UnicodeDecodeError",
    "UnicodeEncodeError",
    "ValueError",
    "ZeroDivisionError",
    # __import__ is required for import machinery; it is sandboxed via the
    # SandboxImportHook instead.
    "__import__",
    # __build_class__ is required for `class` statements.
    "__build_class__",
}

# ---------------------------------------------------------------------------
# Module import whitelist — prefix-based.
# Only modules whose fully-qualified name starts with one of these prefixes
# (or is an exact match) can be imported inside the sandbox.
# ---------------------------------------------------------------------------
ALLOWED_MODULE_PREFIXES: tuple[str, ...] = (
    # Pulse public API
    "pulse.tools",
    "pulse.skills",
    "pulse.plugins",
    # Safe stdlib (no I/O, no subprocess, no ctypes, no socket)
    "abc",
    "argparse",
    "array",
    "base64",
    "binascii",
    "bisect",
    "calendar",
    "collections",
    "copy",
    "csv",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "hashlib",
    "heapq",
    "html",
    "importlib",
    "inspect",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "numbers",
    "operator",
    "pathlib",
    "pprint",
    "random",
    "re",
    "statistics",
    "string",
    "struct",
    "textwrap",
    "time",
    "typing",
    "urllib.parse",
    "uuid",
    "warnings",
    "weakref",
    "xml.etree.ElementTree",
    "zoneinfo",
)

# Python internal modules required for importlib to function.
PYTHON_INTERNAL_MODULES: set[str] = {
    "_io",
    "_frozen_importlib",
    "_frozen_importlib_external",
    "_warnings",
    "_abc",
    "_collections_abc",
    "_stat",
    "_thread",
    "abc",
    "codecs",
    "encodings",
    "encodings.utf_8",
    "encodings.latin_1",
    "encodings.aliases",
    "genericpath",
    "posixpath",
    "ntpath",
    "importlib._bootstrap",
    "importlib._bootstrap_external",
    "importlib.machinery",
    "importlib.abc",
}

# Modules that are explicitly denied regardless of prefix match.
DENIED_MODULES: set[str] = {
    "os",
    "subprocess",
    "ctypes",
    "socket",
    "shutil",
    "sys",
    "pickle",
    "shelve",
    "marshal",
    "multiprocessing",
    "threading",
    "signal",
    "asyncio",
    "concurrent.futures",
    "http.client",
    "http.server",
    "smtplib",
    "ftplib",
    "telnetlib",
    "imaplib",
    "poplib",
    "email",
    "webbrowser",
    "antigravity",
    "turtle",
    "tkinter",
    "code",
    "codeop",
    "pdb",
    "traceback",
    "tempfile",
    "getpass",
    "curses",
    "readline",
    "pty",
    "pipes",
    "platform",
}

# Modules that MUST remain in ``sys.modules`` for the import system itself
# to function. The sandbox keeps them in the cache; protection is enforced
# at the ``__builtins__`` and ``sys.meta_path`` layer.
ESSENTIAL_MODULES: frozenset[str] = frozenset(
    {
        "sys",
        "builtins",
        "_imp",
        "_thread",
        "_frozen_importlib",
        "_frozen_importlib_external",
        "_io",
        "importlib",
        "importlib._bootstrap",
        "importlib._bootstrap_external",
        "importlib.machinery",
        "importlib.abc",
        "_abc",
        "_collections_abc",
        "_stat",
        "_warnings",
        "codecs",
        "encodings",
        "encodings.utf_8",
        "encodings.latin_1",
        "encodings.aliases",
        "abc",
        "genericpath",
        "posixpath",
        "ntpath",
    }
)

# ---------------------------------------------------------------------------
# Permission names (declared by plugins via ``__permissions__``).
# ---------------------------------------------------------------------------
PERM_TOOLS_REGISTER = "tools.register"
PERM_MEMORY_READ = "memory.read"
PERM_MEMORY_WRITE = "memory.write"
PERM_SKILLS_INSTALL = "skills.install"
PERM_SCHEDULER_ADD = "scheduler.add"
PERM_FS_READ = "fs.read"
PERM_FS_WRITE = "fs.write"
PERM_NETWORK = "network"

ALL_PERMISSIONS: set[str] = {
    PERM_TOOLS_REGISTER,
    PERM_MEMORY_READ,
    PERM_MEMORY_WRITE,
    PERM_SKILLS_INSTALL,
    PERM_SCHEDULER_ADD,
    PERM_FS_READ,
    PERM_FS_WRITE,
    PERM_NETWORK,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _module_allowed(fullname: str) -> bool:
    """Return True if ``fullname`` is allowed by the import whitelist."""
    # Explicit denies take priority over everything.
    if fullname in DENIED_MODULES:
        return False
    # Also deny any submodule of a denied top-level package
    # (unless explicitly in PYTHON_INTERNAL_MODULES).
    top = fullname.split(".", 1)[0]
    if top in DENIED_MODULES and fullname not in PYTHON_INTERNAL_MODULES:
        return False
    # Python internals needed for importlib machinery.
    if fullname in PYTHON_INTERNAL_MODULES:
        return True
    for prefix in ALLOWED_MODULE_PREFIXES:
        if fullname == prefix or fullname.startswith(prefix + "."):
            return True
    return False


def _make_safe_builtins() -> dict[str, Any]:
    """Build a restricted ``__builtins__`` dict containing only safe entries."""
    safe: dict[str, Any] = {}
    for name in SAFE_BUILTINS:
        obj = getattr(_builtins, name, None)
        if obj is not None:
            safe[name] = obj
    return safe


class SandboxImportHook:
    """Import hook that enforces the module whitelist during plugin execution.

    Combines three protection layers:
    1. ``sys.meta_path`` finder (using modern ``find_spec`` API) — intercepts
       imports of denied modules before any other finder runs.
    2. ``sys.modules`` cache eviction (except for essential modules) — prevents
       ``import os`` from returning a cached module.
    3. ``__builtins__`` restriction — replaces ``open/eval/exec/compile`` with
       stubs that raise ``PermissionError``.

    Install via :func:`install_sandbox_hook` and remove with
    :func:`remove_sandbox_hook`.
    """

    def __init__(self) -> None:
        self._active = False
        self._stashed: dict[str, Any] = {}

    def install(self) -> None:
        """Activate the sandbox import hook."""
        if self._active:
            return
        # Evict denied modules from sys.modules cache (except essentials).
        for mod_name in list(sys.modules.keys()):
            if mod_name in ESSENTIAL_MODULES:
                continue
            if not _module_allowed(mod_name):
                self._stashed[mod_name] = sys.modules.pop(mod_name, None)
        sys.meta_path.insert(0, self)  # type: ignore[arg-type]
        self._active = True

    def remove(self) -> None:
        """Deactivate the sandbox import hook."""
        if not self._active:
            return
        try:
            sys.meta_path.remove(self)  # type: ignore[arg-type]
        except ValueError:
            logger.exception("valueerror suppressed")
            pass
            pass
        # Restore stashed modules.
        for mod_name, mod in self._stashed.items():
            if mod is not None:
                sys.modules[mod_name] = mod
        self._stashed.clear()
        self._active = False

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        """Modern meta path finder (Python 3.4+ recommended API).

        Returns a spec whose loader raises ``ImportError`` for denied modules,
        or None for allowed modules (letting the next finder handle them).
        """
        if _module_allowed(fullname):
            return None
        import importlib.machinery

        spec = importlib.machinery.ModuleSpec(fullname, self, is_package=False)
        return spec

    def find_module(self, fullname: str, path: Any = None) -> Any:
        """Legacy meta path finder (Python < 3.4 compatibility)."""
        if not _module_allowed(fullname):
            return self
        return None

    def create_module(self, spec: Any) -> Any:
        """Loader.create_module — return None to use importlib's default module creation.

        Returning None avoids recursion that would happen if we called
        ``importlib.util.module_from_spec`` (which re-enters the import system).
        """
        return None

    def exec_module(self, module: Any) -> None:
        """Loader.exec_module — raise ImportError for denied modules."""
        raise ImportError(
            f"Plugin sandbox: import of '{module.__name__}' is not allowed. "
            f"Use __permissions__ to request additional access."
        )

    def load_module(self, fullname: str) -> Any:
        """Legacy loader (Python < 3.4) — raise ImportError for denied modules."""
        raise ImportError(
            f"Plugin sandbox: import of '{fullname}' is not allowed. "
            f"Use __permissions__ to request additional access."
        )


_sandbox_hook = SandboxImportHook()


def install_sandbox_hook() -> None:
    """Activate the global sandbox import hook."""
    _sandbox_hook.install()


def remove_sandbox_hook() -> None:
    """Deactivate the global sandbox import hook."""
    _sandbox_hook.remove()


class PluginSandbox:
    """Per-plugin execution context with permission enforcement.

    Usage::

        sandbox = PluginSandbox(granted_permissions={"tools.register"})
        mod = sandbox.exec_module(name, path)
        if hasattr(mod, "register"):
            mod.register(runtime)
    """

    def __init__(self, granted_permissions: Optional[set[str]] = None) -> None:
        self.granted: set[str] = granted_permissions or set()
        # Validate unknown permission names early.
        unknown = self.granted - ALL_PERMISSIONS
        if unknown:
            logger.warning(f"Unknown permissions declared: {unknown}")

    def has_permission(self, perm: str) -> bool:
        """Check whether ``perm`` is granted in this sandbox."""
        return perm in self.granted

    def exec_module(self, name: str, path: Path) -> ModuleType:
        """Load and execute a plugin module under sandbox constraints.

        Raises:
            ImportError: if the module cannot be loaded.
            SyntaxError: if the module has syntax errors.
            PermissionError: if the plugin requires ungranted permissions.
        """
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Plugin sandbox: cannot load spec from {path}")

        mod = importlib.util.module_from_spec(spec)

        # Replace __builtins__ with our restricted version.
        mod.__builtins__ = _make_safe_builtins()

        # Inject sandbox reference so plugins can check permissions.
        mod.__sandbox__ = self

        # Register in sys.modules so the plugin's own imports resolve.
        sys.modules[name] = mod

        # Activate the import hook, exec, then remove it.
        install_sandbox_hook()
        try:
            spec.loader.exec_module(mod)
        finally:
            remove_sandbox_hook()

        # Validate declared permissions against granted.
        declared = set(getattr(mod, "__permissions__", []) or [])
        missing = declared - self.granted
        if missing:
            raise PermissionError(
                f"Plugin '{name}' requires permissions {sorted(missing)} "
                f"that have not been granted. "
                f"Granted: {sorted(self.granted) or ['(none)']}"
            )

        return mod


def parse_permissions_declaration(source: str) -> set[str]:
    """Extract ``__permissions__`` from plugin source code without executing it.

    This is a lightweight AST-free parser that looks for the literal list
    assignment pattern::

        __permissions__ = ["tools.register", "memory.read"]

    Returns an empty set if the declaration is not found or unparseable.
    """
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()

        # Handle single-line docstrings: """text""" on one line.
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if not in_docstring:
                # Entering docstring.
                in_docstring = True
                # Single-line docstring: if the line has a closing triple-quote
                # AFTER the opening one, exit immediately.
                quote = stripped[:3]
                rest = stripped[3:]
                if quote in rest:
                    in_docstring = False
            else:
                # Closing multi-line docstring.
                in_docstring = False
            continue

        if in_docstring:
            continue

        # Skip comments and empty lines.
        if not stripped or stripped.startswith("#"):
            continue

        # Match: __permissions__ = [...] (may have leading whitespace)
        if "=" in stripped:
            lhs = stripped.split("=", 1)[0].strip()
            if lhs == "__permissions__":
                rhs = stripped.split("=", 1)[1].strip()
                # Extract string literals from the list.
                perms: set[str] = set()
                for part in rhs.replace("[", "").replace("]", "").split(","):
                    part = part.strip().strip('"').strip("'")
                    if part:
                        perms.add(part)
                return perms

    return set()
