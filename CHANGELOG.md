# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-13

### Added
- CONTRIBUTING.md with development setup, coding standards, commit convention, and PR flow.
- Dockerfile for containerized deployment (python:3.11-slim based).
- Makefile with common targets (install, test, coverage, lint, clean, docker).
- 54 new tests covering compactor, session_index, hub, tools/base, provider, cron edges, doctor, settings, skills_cli.

### Improved
- Test coverage: 66% → 73% (96 tests total, up from 42).
- Docstring coverage: 19% → 75% (200/265 definitions documented).
- Exception handling: 28 bare `except Exception` → 15 (remaining are in error classifier and last-resort guards).
- Exception specificity: plugin loader, telegram gateway, skill registry, subagent pool now catch specific exceptions (ImportError, URLError, OSError, etc.).

## [0.0.2] — 2026-07-13

### Fixed
- Version number inconsistency: `pyproject.toml` and `pulse/__init__.py` now report `0.0.2`, matching the release tag.

### Added
- GitHub Actions CI workflow (`.github/workflows/ci.yml`): runs pytest + coverage on Python 3.11/3.12, uploads to Codecov, plus ruff lint.
- Real CI/coverage/release badges in README (replaced placeholder URLs).
- This CHANGELOG.md.

## [0.0.1] — 2026-07-13

### Added — M1: Core orchestrator (reliability-first)
- Error classification (`TRANSIENT` / `TOOL_FAIL` / `CTX_OVERFLOW` / `LLM_REFUSE`) + exponential backoff retry policy.
- Rolling token budget with soft-threshold compaction and hard-cap overflow guard.
- Structured JSON observability bus with `trace_id` and event replay.
- Memory system: `MEMORY.md` + `USER.md` (Hermes-compatible) + SQLite FTS5 cross-session search.
- Skill system: agentskills.io + Hermes format loader (preserves extension fields), registry with progressive loading.
- **Skill evaluation loop**: golden-task replay → success-rate/token comparison → `promote / quarantine / rollback / deprecate` state machine with versioning.
- LLM adapter: `OpenAICompatProvider` (Ollama/vLLM/OpenRouter/OpenAI/DeepSeek) + `AnthropicProvider` + `MockProvider` (offline).
- Built-in tools: `read_file`, `list_dir`, `calc` with recovery-aware invocation.
- CLI: `init` wizard (zero-config Ollama detection), `doctor` self-check, `chat`, `skills` lifecycle, `memory` recall/add.
- Bundled starter skill (`summarize-text`) and example Hermes-style skill (`research-paper-writing`).
- 17 tests covering loader compat, evaluation loop, recovery, budget, orchestrator, memory.

### Added — M2: Multi-platform gateways + scheduler
- `Gateway` abstraction + `GatewayManager` for unified multi-thread lifecycle.
- Rich-powered TUI gateway with slash commands (`/help /skills /memory /model /clear /quit`).
- Telegram polling gateway (stdlib `urllib`, zero heavy deps, long-text chunking).
- Background cron scheduler (0.5s tick, job isolation, execution history).
- CLI: `tui`, `serve` (multi-gateway + scheduler), `cron list/add/remove/pause/resume`.
- 4 new tests.

### Added — M3: Sub-agent parallelism + cron enhancement
- `SubagentPool`: `ThreadPoolExecutor` with per-task timeout, token budget, and error isolation (single-point failure won't crash siblings).
- `decompose` (LLM + heuristic) and `merge_results` pipeline.
- Enhanced cron: 5-field expression matching, natural-language parsing (`"every 5 min"`, `"hourly"`, `"every morning at 8"`), pause/resume, job history.
- CLI: `fork` (decompose → parallel → merge).
- 10 new tests.

### Added — M4: RL trajectory export + dialectic user modeling
- `export_jsonl` (ChatML format) and `export_sharegpt` (ShareGPT JSON array) with filtering by date/outcome/skill.
- `DialecticEngine`: self-hosted dialectical user profiling (thesis → antithesis → synthesis), replacing Honcho cloud dependency. Versioned snapshots with rollback.
- CLI: `rl export`, `memory profile reflect/history/rollback`.
- 6 new tests.

### Added — M5: Plugin system + multi-agent team
- `PluginLoader`: dynamic discovery from bundled + user dirs, `activate` calls `register(runtime)`.
- Bundled `weather` plugin example.
- `TeamOrchestrator`: Builder → Reviewer → Ship pipeline with handoff protocol (what/where/verify/issues/next). Max-round refinement loop.
- CLI: `plugin list/install/activate`, `team`.
- 5 new tests.

### Statistics
- **42 tests**, all passing.
- **~4500 lines** of Python across 53 modules.
- **66% test coverage**.
- **96% type annotation** coverage.
- MIT license, fully self-hosted default stack (Ollama + SQLite FTS5).
