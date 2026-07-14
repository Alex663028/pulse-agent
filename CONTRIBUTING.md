# Contributing to Pulse

Thanks for your interest in improving Pulse! This guide covers setup, development workflow, and coding standards.

## Development Setup

```bash
git clone https://github.com/Alex663028/pulse-agent.git
cd pulse-agent
pip install -e ".[dev]"
python -m pytest -q   # verify 96 tests pass
```

## Project Structure

```
pulse/
├── cli/           # Typer commands and init wizard
├── config/        # Settings, pydantic models
├── orchestrator/  # Core loop, error recovery, token budget, sub-agents
├── llm/           # Provider abstraction (OpenAI-compat, Anthropic, Mock)
├── memory/        # MEMORY.md/USER.md, FTS5, dialectic profiling
├── skills/        # agentskills.io loader, evaluation loop, versioning
├── tools/         # Built-in tools, tool registry
├── plugins/       # Plugin discovery and activation
├── gateways/      # TUI, Telegram, gateway manager
├── scheduler/     # Cron scheduler
├── team/          # Multi-agent team orchestration
├── rl/            # RL trajectory export
└── storage/       # SQLite + FTS5 engine
```

## Coding Standards

- **Python 3.11+** — use type hints on all public functions.
- **Docstrings** — every public class and function must have a docstring.
- **Exception handling** — avoid bare `except Exception`. Catch specific exceptions. If a broad catch is unavoidable, add a `# noqa: BLE001` comment explaining why.
- **Testing** — new features must include tests. Aim for ≥80% coverage on new code.
- **No new dependencies** without justification. Prefer stdlib.

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new gateway
fix: resolve token budget overflow
docs: update README
test: add compactor tests
chore: bump version
```

## Pull Request Flow

1. Fork → create a feature branch (`feat/my-feature`)
2. Write code + tests
3. Ensure `python -m pytest -q` passes
4. Ensure `ruff check pulse/ tests/` passes
5. Open a PR with a clear description

## Running Tests with Coverage

```bash
pip install pytest-cov
python -m pytest --cov=pulse --cov-report=term-missing
```

## Adding a New LLM Provider

1. Subclass `LLMProvider` in `pulse/llm/provider.py`
2. Implement `chat(messages, tools, tool_choice, **kwargs) -> LLMResponse`
3. Register in `pulse/llm/config.py`'s `build_router()`
4. Add tests using `MockProvider` patterns

## Adding a New Tool

1. Subclass `Tool` in `pulse/tools/base.py`
2. Set `name`, `description`, `parameters` (JSON schema)
3. Implement `run(**kwargs) -> ToolResult`
4. Register in `pulse/tools/builtin.py`

## Adding a Plugin

1. Create `~/.pulse/plugins/myplugin.py`
2. Define a `register(runtime)` function
3. Call `runtime.tools.register(MyTool())` inside it
4. Test with `pulse plugin activate myplugin`
