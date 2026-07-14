"""Plugin system with sandbox isolation and permission whitelist."""

from pulse.plugins.loader import BUNDLED_PERMISSIONS, USER_DEFAULT_PERMISSIONS, PluginInfo, PluginLoader
from pulse.plugins.sandbox import ALL_PERMISSIONS, PluginSandbox

__all__ = [
    "PluginLoader",
    "PluginInfo",
    "PluginSandbox",
    "ALL_PERMISSIONS",
    "BUNDLED_PERMISSIONS",
    "USER_DEFAULT_PERMISSIONS",
]
