"""Settings & configuration.

The single source of truth for provider/model/base_url lives in
``~/.pulse/config.yaml``; secrets live in ``~/.pulse/.env`` (API keys).
Everything defaults to a fully local, self-hosted setup (Ollama).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_BASE_URL = "http://localhost:11434/v1"


def default_config_dir() -> Path:
    """Return the Pulse config directory (``$PULSE_HOME`` or ``~/.pulse``)."""
    return Path(os.environ.get("PULSE_HOME", Path.home() / ".pulse"))


def default_data_dir(cfg: Optional[Path] = None) -> Path:
    """Return the data directory under ``cfg`` (or the default config dir)."""
    return (cfg or default_config_dir()) / "data"


class ModelSettings(BaseModel):
    """Provider/model/base_url and fallback configuration."""

    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    # auxiliary models for routing (vision / web). "auto" = same as main.
    auxiliary_provider: str = "auto"
    auxiliary_model: str = "auto"
    # fallback chain, e.g. ["openai:gpt-4o-mini", "anthropic:claude-3-5-haiku"]
    fallback: list[str] = Field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 4096


class Settings(BaseModel):
    """Top-level application settings: paths, model config, auto-evolution and session limits."""

    config_dir: Path = Field(default_factory=default_config_dir)
    model: ModelSettings = Field(default_factory=ModelSettings)
    api_key_env: str = ""
    auto_evolve: bool = True
    max_session_tokens: int = 12000
    log_level: str = "INFO"

    @property
    def data_dir(self) -> Path:
        """Return the data directory (``<config_dir>/data``)."""
        return self.config_dir / "data"

    @property
    def skills_dir(self) -> Path:
        """Return the skills directory (``<data_dir>/skills``)."""
        return self.data_dir / "skills"

    @property
    def memory_dir(self) -> Path:
        """Return the memories directory (``<data_dir>/memories``)."""
        return self.data_dir / "memories"

    @property
    def db_path(self) -> Path:
        """Return the SQLite database path (``<data_dir>/pulse.db``)."""
        return self.data_dir / "pulse.db"

    @property
    def env_path(self) -> Path:
        """Return the ``.env`` path under the config dir."""
        return self.config_dir / ".env"

    def ensure_dirs(self) -> None:
        """Create the config, data, skills and memory directories if missing."""
        for d in (self.config_dir, self.data_dir, self.skills_dir, self.memory_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(config_dir: Optional[Path] = None) -> Settings:
    """Load settings from ``config.yaml`` if present, else defaults."""
    cfg = Path(config_dir) if config_dir else default_config_dir()
    path = cfg / "config.yaml"
    if not path.exists():
        s = Settings(config_dir=cfg)
        s.ensure_dirs()
        return s
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Pull nested model settings.
    model_raw = raw.pop("model", {}) or {}
    settings = Settings(**{k: v for k, v in raw.items() if k in Settings.model_fields})
    if model_raw:
        merged = settings.model.model_dump()
        merged.update({k: v for k, v in model_raw.items() if k in ModelSettings.model_fields})
        settings.model = ModelSettings(**merged)
    settings.ensure_dirs()
    return settings


def save_settings(s: Settings) -> Path:
    """Persist settings to ``config.yaml`` (secrets are NOT written here)."""
    s.ensure_dirs()
    payload = s.model_dump(exclude={"config_dir", "data_dir"})
    # data_dir is derived; store only if non-default for clarity
    payload["data_dir"] = str(s.data_dir)
    path = s.config_dir / "config.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def load_env(s: Settings) -> dict[str, str]:
    """Load API keys from ``.env`` into a dict (does not touch os.environ).

    If the file has overly permissive permissions (anything beyond 0o600),
    a warning is logged but loading continues.
    """
    env: dict[str, str] = {}
    if not s.env_path.exists():
        return env
    # Warn if .env permissions are too open.
    try:
        st = s.env_path.stat()
        if st.st_mode & 0o077:  # any group/other access bits
            import logging
            logging.getLogger("pulse.config").warning(
                f"Permissions on {s.env_path} are too open ({oct(st.st_mode)[-3:]}). "
                f"Consider running: chmod 600 {s.env_path}"
            )
    except OSError:
        pass
    for line in s.env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env
