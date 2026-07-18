# Pulse — A Self-improving AI Agent You Can Trust

[![CI](https://github.com/Alex663028/pulse-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Alex663028/pulse-agent/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pulse-agent)](https://pypi.org/project/pulse-agent/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Release](https://img.shields.io/badge/release-v0.7.0-blue)](https://github.com/Alex663028/pulse-agent/releases/tag/v0.7.0)

A **self-improving personal AI agent**, rebuilt with a reliability-first core. Fully self-hostable by default — local LLM + SQLite FTS5, zero cloud dependency.

**Why Pulse?** Most AI agents are unreliable black boxes. Pulse is the first agent where:
1. **Reliability is the core feature** — every LLM/tool call wrapped in classified error recovery, circuit breaker, token budget guardrail.
2. **Skills are verified, not vibes** — auto-generated skills must pass a golden-task replay before promotion. `promote / quarantine /rollback` is a versioned state machine.
3. **Zero-config onboarding** — `pulse init --yes` gets you running on a local LLM with no API key. No Python knowledge needed.

---

## Three Pillars

### 1. Reliability & Safety
- **Error Recovery**: classified errors (transient/tool/overflow) with automatic retry + exponential backoff
- **Circuit Breaker**: per-provider failover (5 failures → 30s cooldown)
- **Context Budget**: hard guardrail triggers LLM-based compaction before overflow
- **Command Approval**: manual/smart/off modes for shell commands; dangerous ops always require confirmation
- **Secret Redaction**: automatic API key / token redaction in tool output

### 2. Self-improving Skills
- **Evaluated Evolution**: skills start as candidates; golden-task replay determines promotion/rollback
- **Versioned State Machine**: `candidate → promoted → quarantined → deprecated`, each with immutable content snapshots
- **Self-Evolution**: `pulse evolve analyze` detects repeated failures, skill gaps, and prompt drift — proposes concrete improvements
- **Skill Curator**: background maintenance — stale detection, auto-archive

### 3. Enterprise-Ready
- **RBAC**: 5 predefined roles (viewer / operator / developer / admin / auditor), 13 granular permissions
- **Audit Logging**: every user action recorded with user, action, resource, result, timestamp
- **Multi-Profile**: isolated configs / sessions / skills per profile via `PULSE_PROFILE`
- **SSO Stub**: pluggable OIDC/SAML integration point
- **i18n**: English / Chinese UI with 70+ translated strings

---

## Ecosystem

What ships in the box:

| Layer | Components |
|-------|------------|
| **Entry Points** | CLI, TUI, Web UI (:10000 React SPA), Telegram, Feishu, WeChat, WhatsApp |
| **LLM** | OpenAI / Anthropic / Ollama / OpenRouter / DeepSeek + Mock (offline) |
| **Tools** | 7 built-in (web_search, web_fetch, write_file, edit_file, python_exec, shell_exec, http_client) + dynamic YAML/JSON/Python tools + MCP servers + skill-declared tools |
| **Memory** | FTS5 full-text search, cross-session recall, user notes, dialectic profiling |
| **Scheduling** | Cron with job isolation and execution history |
| **Observability** | Structured traces to LangSmith/LangFuse, usage analytics |

---

## Quick Start

### Install

```bash
# From PyPI (recommended)
pip install pulse-agent

# Or install from source
pip install git+https://github.com/Alex663028/pulse-agent.git
# Or: git clone https://github.com/Alex663028/pulse-agent.git && cd pulse-agent && pip install -e ".[dev]"
```

### Run

```bash
# Zero-config (local Ollama — no API key needed)
pulse init --yes --provider ollama --model qwen2.5:7b

# Or use any OpenAI-compatible API
pulse init --yes --provider openai --model gpt-4o

# Start chatting
pulse chat "hello"              # one-shot
pulse chat "hello" --stream    # streaming
pulse tui                       # interactive terminal
pulse web start                 # browser UI at http://127.0.0.1:10000

# Self-check
pulse doctor
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [SECURITY.md](SECURITY.md) | Security model, vulnerability reporting, best practices |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, coding standards, commit conventions |
| [LICENSE](LICENSE) | Apache 2.0 |

---

## Version History

| Version | Release Date | Key Changes |
|---------|-------------|-------------|
| v0.7.0 | 2025-07-18 | PyPI support, enterprise RBAC, audit logging, SSO stub, i18n |
| v0.6.1 | 2025-07-17 | Security redaction, command approval, checkpoints, session search, curator, analytics |
| v0.6.0 | 2025-07-17 | Circuit breaker, optimistic lock, async, tool filtering, React SPA |
| v0.5.x | 2025-07-15 | Social gateways, Web UI, streaming, memory, feedback loop |
| v0.4.x | 2025-07-15 | Anthropic provider, rate limiter, reliability audit |
| v0.3.0 | 2025-07-15 | Core orchestrator, memory, skill eval loop |

---

## License

Apache 2.0 — see [LICENSE](LICENSE). Free for personal, academic, and commercial use.
