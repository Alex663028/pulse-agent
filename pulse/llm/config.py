"""Build a provider/router from application settings."""
from __future__ import annotations

from pulse.config.settings import Settings, load_env
from pulse.llm.provider import (
    LLMProvider,
    MockProvider,
    OpenAICompatProvider,
)
from pulse.llm.router import Router


def _make_compat(settings: Settings, env: dict[str, str], provider: str) -> OpenAICompatProvider:
    ms = settings.model
    if provider == "ollama":
        return OpenAICompatProvider(base_url=ms.base_url, api_key="", model=ms.model)
    # cloud providers resolve base_url + key from env
    key = env.get(settings.api_key_env) or env.get(f"{provider.upper()}_API_KEY", "")
    base_urls = {
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "deepseek": "https://api.deepseek.com/v1",
    }
    base = base_urls.get(provider, ms.base_url)
    return OpenAICompatProvider(base_url=base, api_key=key, model=ms.model)


def build_router(settings: Settings) -> Router:
    """Construct a ``Router`` from settings: MockProvider for ``mock``, otherwise an OpenAICompatProvider chain including configured fallbacks."""
    env = load_env(settings)
    ms = settings.model
    if ms.provider == "mock":
        primary: LLMProvider = MockProvider(model=ms.model)
    else:
        primary = _make_compat(settings, env, ms.provider)

    fallbacks: list[LLMProvider] = []
    for fb in ms.fallback:
        prov = fb.split(":", 1)[0]
        if prov in ("ollama", "openai", "openrouter", "deepseek"):
            fallbacks.append(_make_compat(settings, env, prov))
    return Router(primary=primary, fallbacks=fallbacks)
