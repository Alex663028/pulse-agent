"""Build a provider/router from application settings."""

from __future__ import annotations

from pulse.config.settings import DEFAULT_BASE_URL, Settings, load_env
from pulse.llm.provider import (
    LLMError,
    LLMProvider,
    OpenAICompatProvider,
)
from pulse.llm.router import Router


def _make_compat(settings: Settings, env: dict[str, str], provider: str) -> LLMProvider:
    ms = settings.model
    if provider == "ollama":
        return OpenAICompatProvider(
            base_url=ms.base_url, api_key="ollama", model=ms.model
        )
    if provider == "anthropic":
        try:
            from pulse.llm.provider import AnthropicProvider

            key = env.get("ANTHROPIC_API_KEY") or env.get(settings.api_key_env, "")
            return AnthropicProvider(
                base_url=ms.base_url
                if ms.base_url and ms.base_url != DEFAULT_BASE_URL
                else "https://api.anthropic.com",
                api_key=key,
                model=ms.model or "claude-3-5-sonnet-20241022",
            )
        except ImportError:
            raise LLMError(
                "anthropic package not installed; pip install git+https://github.com/Alex663028/pulse-agent.git#egg=pulse-agent[anthropic]"
            )
    key = env.get(settings.api_key_env) or env.get(f"{provider.upper()}_API_KEY", "")
    base_urls = {
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "deepseek": "https://api.deepseek.com/v1",
    }
    if ms.base_url and ms.base_url != DEFAULT_BASE_URL:
        base = ms.base_url
    else:
        base = base_urls.get(provider, ms.base_url)
    return OpenAICompatProvider(base_url=base, api_key=key, model=ms.model)


def build_router(settings: Settings) -> Router:
    """Construct a Router from settings."""
    from pulse.orchestrator.rate_limiter import RateLimiter

    env = load_env(settings)
    ms = settings.model
    primary = _make_compat(settings, env, ms.provider)

    fallbacks: list[LLMProvider] = []
    for fb in ms.fallback:
        prov = fb.split(":", 1)[0]
        if prov in ("ollama", "openai", "openrouter", "deepseek", "anthropic"):
            fallbacks.append(_make_compat(settings, env, prov))

    limiter = RateLimiter(default_rate=1.0, default_burst=5)
    if ms.provider == "ollama":
        limiter.configure(ms.provider, rate=10.0, burst=20)
    elif ms.provider == "openrouter":
        limiter.configure(ms.provider, rate=2.0, burst=10)
    elif ms.provider == "anthropic":
        limiter.configure(ms.provider, rate=1.0, burst=5)

    return Router(primary=primary, fallbacks=fallbacks, rate_limiter=limiter)
