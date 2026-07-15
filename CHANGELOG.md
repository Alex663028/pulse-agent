# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] — 2026-07-16

### Added
- **`pulse init --base-url`**: point any provider at a custom OpenAI-compatible endpoint (self-hosted gateway such as vLLM/LiteLLM, a reverse proxy, or an alternative vendor).
- **Any OpenAI-protocol endpoint**: built-in `openai` / `openrouter` / `deepseek` now honor an explicitly-set `base_url`, overriding their previously-hardcoded official vendor URLs inside `_make_compat()` (`pulse/llm/config.py`). Previously these providers always called the official URL and silently discarded any `base_url` you configured — so self-hosted gateways and proxies were unreachable.
- `model.base_url` in `config.yaml` is now a first-class field: `pulse init --base-url ...` writes it, and the router reads it back on every `build_router()` call.

### Fixed
- `_make_compat()` ignored `model.base_url` for built-in cloud providers; a configured custom endpoint was silently discarded. Now an explicit `base_url` (anything other than the default local Ollama address `http://localhost:11434/v1`) takes precedence, while an unset/默认 value still falls back to the official vendor URL.

### Stats
- 8 new tests (base_url precedence, fallback-chain inheritance, init-wizard persistence). 130 → 138 total. All green on Python 3.11 & 3.12; ruff clean.

## [0.3.0] — 2026-07-15

### Added — MCP (Model Context Protocol) integration
- **Lightweight MCP stdio client** (`pulse/mcp/client.py`): newline-delimited JSON-RPC 2.0 over subprocess stdin/stdout, `initialize` handshake + `notifications/initialized`, `tools/list`, `tools/call`. No hard dependency on the official `mcp` SDK.
- **Tool adapter** (`MCPTool`): wraps any MCP server tool as a first-class `Tool`, normalizing results to `ToolResult`; names are prefixed `{server}__{tool}` to avoid collisions.
- **Manager** (`MCPManager`): starts enabled servers, registers their tools into the global `ToolRegistry`, skips disabled/broken servers gracefully.
- **CLI** (`pulse mcp list|add|remove|test|export`): full lifecycle management of MCP server configs (persisted in `config.yaml`, secrets stay in `.env`).
- **Runtime integration**: `bootstrap(load_mcp=True)` automatically connects configured servers for `chat`, `tui`, `serve`, `fork`, `team`.
- **`pulse doctor`** now probes each enabled MCP server (reachability + tool count).

### Improved — MCP reliability & UX
- **Lazy, parallel discovery**: `MCPManager.load_servers()` probes every enabled server in parallel to fetch tool specs, then disconnects — servers are only (re)spawned on first actual tool use, so startup no longer blocks on N server launches.
- **Automatic reconnection**: `MCPManager.ensure_connected()`/`reconnect()` detect a dead server process and reconnect transparently on the next call.
- **Argument validation**: `validate_tool_args()` checks each MCP tool call against the server's `inputSchema` (required fields + JSON types) before sending, returning a clean error instead of a server-side failure.
- **`pulse mcp list`** now shows a live health check per server: tool count and `ok` / `unreachable` status.
- Shared `probe_server()` helper used by both `mcp list` and `doctor` (no duplicated connection logic).
- `MCPClient` gained `is_alive()` and a context-manager protocol; `MCPTool` supports a lazy `manager` mode alongside the existing eager `client` mode.

### Fixed
- `load_settings()` now carries the requested `config_dir` through when a `config.yaml` already exists, so subsequent `save_settings()` writes to the correct location (previously reverted to the default `~/.pulse` and silently dropped changes).

### Stats
- 23 MCP/doctor tests (client, adapter, manager, CLI round-trip, lazy connect, reconnect, validation, health). 107 → 130 total.

## [0.2.0] — 2026-07-14

### Added — P2: Plugin sandbox, security, benchmarks, docs
- **Plugin sandbox** (`pulse/plugins/sandbox.py`): import isolation via `sys.meta_path` finder + `sys.modules` cache eviction; restricted `__builtins__` (removes `open`, `eval`, `exec`, `compile`); permission whitelist system (`tools.register`, `memory.read/write`, `network`, etc.); plugins declare `__permissions__` in source; bundled plugins get full permissions, user plugins get conservative defaults.
- **`.env` chmod 600**: API key files are now created with `0o600` permissions; `load_env()` warns if permissions are too open.
- **Benchmark suite** (`scripts/benchmark.py`): measures orchestrator latency, token consumption, sub-agent throughput, skill evaluation speed, and memory recall latency. Supports `--quick`, `--json`, and `--bench` flags.
- **Mermaid diagrams** in README: architecture flowchart, skill evaluation state machine, multi-agent team pipeline.
- **TUI demo** screenshot in README.
- 11 new sandbox tests (96 → 107 total).

### Improved
- Plugin loader now parses `__permissions__` from source without execution and passes permissions to sandbox.
- `load_env()` detects and warns about overly permissive `.env` file permissions.

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
