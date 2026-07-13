"""Zero-config `pulse init` wizard.

Minimizes questions: defaults to a fully local Ollama setup, auto-detects a
running Ollama, and only asks for an API key when a cloud provider is chosen.
This is the UX fix for Hermes' steep onboarding curve.
"""
from __future__ import annotations

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
    "ollama": "Local, self-hosted (default, zero config)",
    "openai": "OpenAI (cloud, needs API key)",
    "openrouter": "OpenRouter (200+ models, needs key)",
    "deepseek": "DeepSeek (cloud, needs key)",
    "mock": "Mock provider (offline demo, no model needed)",
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
    non_interactive: bool = False,
) -> Settings:
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
        base = DEFAULT_BASE_URL
        if _ollama_reachable(base):
            console.print("[green]✓ Detected a running Ollama at[/green] " + base)
        else:
            console.print("[yellow]! No Ollama detected at[/yellow] " + base + " — start it with `ollama serve` later.")
        ms.base_url = base
        ms.model = model or Prompt.ask("Model", default=DEFAULT_MODEL) if not non_interactive else (model or DEFAULT_MODEL)
        settings.api_key_env = ""
    elif provider == "mock":
        ms.model = model or "mock-1"
    else:
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
    elif provider == "mock":
        console.print("  Run [bold]pulse chat \"hello\"[/bold] (offline mock mode).")
    else:
        console.print("  Run [bold]pulse chat \"hello\"[/bold] once your API key is set.")
    return settings


def _write_env(settings: Settings, key: str, value: str) -> None:
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    path = settings.config_dir / ".env"
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
