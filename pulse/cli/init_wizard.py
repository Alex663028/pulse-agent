"""Zero-config `pulse init` wizard.

Minimizes questions: defaults to a fully local Ollama setup, auto-detects a
running Ollama, and only asks for an API key when a cloud provider is chosen.
This is the UX fix for Hermes' steep onboarding curve.
"""
from __future__ import annotations


import os
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from pulse.config.settings import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    Settings,
    save_settings,
)

console = Console()

PROVIDERS = {
    "anthropic": "Anthropic (Claude, cloud, needs API key)",
    "ollama": "Local, self-hosted (default, zero config)",
    "openai": "OpenAI (cloud, needs API key)",
    "openrouter": "OpenRouter (200+ models, needs key)",
    "deepseek": "DeepSeek (cloud, needs key)",
}


def _ollama_reachable(base_url: str) -> bool:
    try:
        urllib.request.urlopen(base_url.replace("/v1", "") + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def run_init(
    settings: Settings,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    non_interactive: bool = False,
) -> Settings:
    """Interactive (or non-interactive) wizard that configures provider/model/keys and persists settings.

    ``base_url`` overrides the endpoint for any provider, enabling targets that
    speak the OpenAI ``/v1/chat/completions`` protocol but live somewhere other
    than the official vendor URL (self-hosted gateways, proxies, alt vendors).
    """
    console.print("[bold cyan]Pulse init[/bold cyan] — configure your agent\n")

    if provider is None:
        if non_interactive:
            provider = "ollama"
        else:
            for k, v in PROVIDERS.items():
                console.print(f"  [green]{k}[/green]  {v}")
            provider = Prompt.ask("Provider", choices=list(PROVIDERS), default="ollama")

    ms = settings.model
    ms.provider = provider

    if provider == "ollama":
        base = base_url or DEFAULT_BASE_URL
        if base_url:
            console.print(f"[cyan]Using custom base URL:[/cyan] {base}")
        if _ollama_reachable(base):
            console.print("[green]✓ Detected a server at[/green] " + base)
        else:
            console.print("[yellow]! No server detected at[/yellow] " + base + " — make sure it's reachable before chatting.")
        ms.base_url = base
        ms.model = model or Prompt.ask("Model", default=DEFAULT_MODEL) if not non_interactive else (model or DEFAULT_MODEL)
        settings.api_key_env = ""
    else:
        if base_url:
            ms.base_url = base_url
        key_env = f"{provider.upper()}_API_KEY"
        if api_key:
            (settings.config_dir).mkdir(parents=True, exist_ok=True)
            _write_env(settings, key_env, api_key)
            console.print(f"[green]✓ Saved {key_env} to .env[/green]")
        elif not non_interactive:
            k = Prompt.ask(f"{key_env} (paste, or Enter to set later)", default="")
            if k:
                _write_env(settings, key_env, k)
        settings.api_key_env = key_env
        ms.model = model or Prompt.ask("Model", default=DEFAULT_MODEL) if not non_interactive else (model or DEFAULT_MODEL)

    save_settings(settings)
    console.print(f"\n[bold green]✓ Pulse configured at[/bold green] {settings.config_dir / 'config.yaml'}")
    if provider == "ollama":
        console.print("  Run [bold]pulse chat \"hello\"[/bold] to talk to your local model.")
    else:
        console.print("  Run [bold]pulse chat \"hello\"[/bold] once your API key is set.")
    return settings


def _write_env(settings: Settings, key: str, value: str) -> None:
    """Persist an environment variable to ``.env`` with restricted permissions (0o600)."""
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    path = settings.config_dir / ".env"
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Restrict permissions: owner read/write only (API keys are secrets).
    _chmod_restrict(path)


def _chmod_restrict(path: Path) -> None:
    """Set file permissions to 0o600 (owner read/write only).

    On non-POSIX systems (e.g. Windows) this is a no-op.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Non-POSIX or permission denied — best effort.
