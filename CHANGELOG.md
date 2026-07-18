# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] — 2026-07-18

### Added — Enterprise features
- **Audit logging** (`pulse/enterprise/__init__.py`): `AuditLogger` writes every user action to a file with user ID, action, resource, result, timestamp, and detail. Supports querying by user or action.
- **RBAC/ABAC** (`pulse/enterprise/__init__.py`): 5 predefined roles (viewer, operator, developer, admin, auditor) with 13 granular permissions across skill/memory/tool/session/admin domains. `User.attributes` enables attribute-based access control.
- **AuthManager**: session-based authentication with token management. `login`, `logout`, `get_user`, `check_permission`.
- **SSOProvider**: stub for OIDC/SAML integration. `get_login_url`, `exchange_code`. Replace with a real provider (Auth0, Okta, Keycloak) for production SSO.

### Added — Internationalization (i18n)
- **pulse/i18n/__init__.py**: `I18n` class with `t(key, default)` translation. Supports `en` (English) and `zh` (Chinese). 70+ translated strings covering chat, skills, memory, settings, auth, audit, and evolution modules. Falls back to English for missing keys.

### Added — HTTP utilities
- **pulse/net.py**: `http_request()` with exponential backoff retry (configurable `max_retries`, `backoff`). `safe_parse_json()` helper that handles JSON strings, dicts, and failure gracefully.

### Added — PyPI publishing
- **.github/workflows/release.yml**: automatic build + publish to PyPI on tag push using GitHub Actions Trusted Publishing (OIDC, no API tokens needed).

### Improved — Documentation
- **README.md**: refactored from 24-item feature dump into 3 core pillars (Reliability, Self-improving Skills, Enterprise-Ready) + Ecosystem table. Clear "Why Pulse?" differentiation from Hermes.
- **SECURITY.md**: security model (command approval, secret redaction, checkpoints, RBAC), supported versions, vulnerability reporting process, best practices, known limitations.

### Fixed — Version alignment
- All version references aligned to `0.7.0`: `pyproject.toml`, `pulse/__init__.py`, `README.md`, `Makefile`, `Dockerfile`, `pulse/mcp/client.py` fallback version.

### Added — Tests
- `test_enterprise.py`: 10 tests for `AuditLogger`, RBAC roles, `AuthManager`, `SSOProvider`.
- `test_i18n.py`: 5 tests for English/Chinese translation and fallback.

### Stats
- 424 tests, ruff clean, 75% coverage.

## [0.6.1] — 2026-07-17

### Added
- **Secret redaction** (`pulse/security/__init__.py`): auto-redact API keys, bearer tokens, private keys in tool output. Always-on, no configuration needed.
- **Command approval** (`pulse/security/__init__.py`): `requires_approval()` detects dangerous commands (rm -rf, git reset --hard, chmod 777, dd, shred, chown root, fork bombs). Three modes: `manual`, `smart`, `off`.
- **Filesystem checkpoints** (`pulse/security/__init__.py`): `create_checkpoint()`, `restore_checkpoint()`, `list_checkpoints()`. Automatic snapshots before `write_file`/`edit_file` modifications.
- **Session search** (`pulse/storage/engine.py`): `search_sessions()` performs FTS5 full-text search across all session memory. `sessions_for_query()` returns matching session IDs.
- **Skill curator** (`pulse/skills/curator.py`): `SkillCurator` tracks usage, marks stale skills, archives inactive ones, creates tar.gz backups.
- **Usage analytics** (`pulse/analytics.py`): `UsageInsights` computes sessions, tokens, success rate, top skills. `pulse insights` CLI command.

### Improved
- **Context quality**: FTS5 rank ordering for relevance, compaction via LLM summarization.
- **Router circuit breaker**: per-provider failure tracking (5 failures → 30s cooldown).

### Fixed
- GitHub Issue #2: `SkillEvaluator.apply()` now invokes `versioning.rollback()` for rollback decisions. `versioning.rollback()` restores SKILL.md bytes from immutable `content_snapshot`.
- Schema migration: `skill_versions` table gains `content_snapshot` column on existing databases.

## [0.6.0] — 2026-07-17

### Added
- **Async support** (`pulse/llm/async_provider.py`): `AsyncLLMProvider` wraps sync providers using `asyncio.to_thread`.
- **Optimistic locking** (`pulse/storage/lock.py`): `with_optimistic_lock()` for concurrent-safe updates via version column CAS.
- **Tool filtering** (`pulse/tools/registry.py`): `allowlist` / `blocklist` on `ToolRegistry`. `allowed_names` property, `set_allowlist()`, `set_blocklist()`.
- **Web UI** (`pulse/web/app.py`): React 18 SPA with sidebar navigation, chat/sessions/tools/skills pages. No build step — pure CDN React.

## [0.5.2] — 2026-07-15

### Added
- **Social gateways** (`pulse/gateways/social.py`): `FeishuGateway`, `WechatGateway`, `WhatsAppGateway` — webhook-mode bridges with signature verification and encryption support.
- **Dynamic tools**: drop `.yaml`, `.json`, `.py` into `~/.pulse/tools/` — auto-registered at startup.
- **Recursive sub-agents**: `SubagentPool` with `RecursionContext` enables full recovery-enabled loop for sub-agent tasks.

## [0.5.1] — 2026-07-15

### Added
- **Dockerfile**: python:3.11-slim based, multi-stage build.
- **E2E tests**: full-stack scenario tests.
- **File logging**: `~/.pulse/logs/pulse.log` with daily rotation (7 days retained).
- **Plugin sandbox**: restricted `__builtins__`, permission whitelist system.

## [0.5.0] — 2026-07-15

### Added
- **Web UI**: Flask-based session management dashboard on port 10000.
- **Streaming**: `Orchestrator.run_stream()` yields token chunks.
- **Session memory**: multi-turn conversations; previous turns auto-injected as context.
- **Feedback loop**: `add_correction("...")` → remembered in future system prompts.

## [0.4.1] — 2026-07-15

### Fixed
- P0-P2 reliability audit: fixed bare `except Exception`, added specific exception handling across all modules.

## [0.4.0] — 2026-07-15

### Added
- **Anthropic provider**: `AnthropicProvider` with native Messages API support.
- **Rate limiter**: token-bucket rate limiter per provider.
- **Bad-response fallback**: router walks fallback chain when primary provider returns empty content.

## [0.3.1] — 2026-07-16

### Added
- **`pulse init --base-url`**: point any provider at a custom OpenAI-compatible endpoint.
- Any OpenAI-protocol endpoint now honors an explicitly-set `base_url`.

### Fixed
- `_make_compat()` ignored `model.base_url` for built-in cloud providers.

## [0.3.0] — 2026-07-15

### Added — MCP (Model Context Protocol) integration
- Lightweight MCP stdio client (`pulse/mcp/client.py`).
- Tool adapter (`MCPTool`), manager (`MCPManager`), CLI (`pulse mcp list|add|remove|test|export`).

### Stats
- 23 MCP/doctor tests. 107 → 130 total.

## [0.2.0] — 2026-07-14

### Added — Plugin sandbox, security, benchmarks, docs
- Plugin sandbox (`pulse/plugins/sandbox.py`).
- `.env` chmod 600.
- Benchmark suite (`scripts/benchmark.py`).

## [0.1.0] — 2026-07-13

### Added
- CONTRIBUTING.md, Dockerfile, Makefile.
- 54 new tests. 66% → 73% coverage.

## [0.0.2] — 2026-07-13

### Added
- GitHub Actions CI workflow.
- CI/coverage/release badges.

## [0.0.1] — 2026-07-13

### Added — M1: Core orchestrator (reliability-first)
- Error classification + exponential backoff retry policy.
- Rolling token budget with soft-threshold compaction.
- Memory system, skill evaluation loop, LLM adapters.
- CLI: `init`, `doctor`, `chat`, `skills`, `memory`.

### Statistics
- 42 tests, ~4500 lines, 66% coverage.
