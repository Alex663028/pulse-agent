# Pulse — Self-improving AI Agent (Reliability-First)

[![CI](https://github.com/Alex663028/pulse-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Alex663028/pulse-agent/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-73%25-yellow)](https://github.com/Alex663028/pulse-agent)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Release](https://img.shields.io/badge/release-v0.1.0-blue)](https://github.com/Alex663028/pulse-agent/releases/tag/v0.1.0)

A **self-improving personal AI agent** with a reliability-first core.
Compatible with the [agentskills.io](https://agentskills.io) open standard.
**Fully self-hostable by default** — Ollama + SQLite FTS5, zero cloud dependency.

---

## Why Pulse

| Advantage | Detail |
|---|---|
| **Reliability-first orchestration** | Every LLM/tool call wrapped in classified error recovery + exponential backoff + hard token budget guardrail |
| **Evaluated skill self-evolution** | Auto-generated skills must pass golden-task replay before promotion. `promote / quarantine / rollback` state machine with versioning |
| **Zero-config onboarding** | `pulse init --yes` with built-in Ollama detection, Rich visual feedback, starter skills, `pulse doctor` self-check |
| **Fully self-hosted** | Default Ollama + local SQLite FTS5; any cloud API is opt-in — no mandatory external service |
| **Multi-agent orchestration** | Sub-agent parallel pool with failure isolation + result merge; Builder→Reviewer→Ship team pipeline |
| **Dialectic user modeling** | Self-hosted replacement for Honcho — thesis → antithesis → synthesis profiling with versioned rollbacks |
| **Agentskills.io compatible** | Load and run skills from the ecosystem without modification |
| **Plugin system** | Dynamic discovery and activation; plugins can register tools, skills, and lifecycle hooks |
| **RL training data pipeline** | Export execution trajectories in ChatML JSONL or ShareGPT format for fine-tuning |
| **Cron scheduling** | Natural-language scheduling (`"every 5 min"`, `"daily at 8am"`) + standard cron expressions + pause/resume with execution history |

---

## Quick Start

```bash
# 1. Install
pip install -e .

# 2. Zero-config (local Ollama — no API key needed)
pulse init --yes --provider ollama --model qwen2.5:7b

# 3. First conversation
pulse chat "write a Python sorting function"

# 4. Self-check
pulse doctor

# 5. Interactive TUI
pulse tui
```

**No Ollama?** Use the built-in mock provider for an offline demo:
```bash
pulse init --yes --provider mock
pulse chat "hello world"
```

---

## Architecture

```
CLI (Typer + Rich) → Orchestrator (ReAct / recovery / token budget / observability)
  ├── LLM adapter  (OpenAI-compat / Anthropic / Ollama / Mock)
  ├── Memory       (MEMORY.md + USER.md + SQLite FTS5 + dialectic profiling)
  ├── Skills       (agentskills.io loader + evaluation loop + versioning)
  ├── Tools / MCP  (built-in tools + plugin registry)
  ├── Gateways     (TUI + Telegram + CLI)
  ├── Scheduler    (cron expressions + natural-language scheduling)
  ├── Sub-agents   (parallel pool + failure isolation + result merge)
  ├── Team         (Builder → Reviewer → Ship pipeline)
  ├── Plugins      (dynamic discovery + activation)
  └── RL export    (ChatML JSONL + ShareGPT format)
```

---

## Commands

| Command | Description |
|---|---|
| `pulse init` | Zero-config setup wizard |
| `pulse doctor` | Self-check (Python / FTS5 / storage / Ollama reachable) |
| `pulse chat <task>` | One-shot task through the orchestrator |
| `pulse tui` | Interactive terminal chat (with slash commands) |
| `pulse serve` | Start all gateways + scheduler |
| `pulse fork <task>` | Decompose task → parallel sub-agents → merge |
| `pulse team <task>` | Multi-agent team (Builder → Reviewer → Ship) |
| `pulse skills list\|install\|eval\|promote\|rollback` | Skill lifecycle management |
| `pulse memory recall\|add\|profile` | Cross-session FTS5 memory + dialectic profiling |
| `pulse cron list\|add\|remove\|pause\|resume` | Cron job management |
| `pulse rl export` | Export trajectories for fine-tuning (JSONL / ShareGPT) |
| `pulse plugin list\|install\|activate` | Plugin system |

---

## Configuring LLM Providers

```bash
# Ollama (local, recommended)
pulse init --provider ollama --model qwen2.5:7b --yes

# OpenAI
pulse init --provider openai --model gpt-4o-mini --api-key sk-xxx --yes

# OpenRouter (200+ models)
pulse init --provider openrouter --model openai/gpt-4o-mini --api-key sk-xxx --yes

# DeepSeek
pulse init --provider deepseek --model deepseek-chat --api-key sk-xxx --yes
```

API keys are stored in `~/.pulse/.env` (never in config.yaml). Provider defaults to Ollama — no key required.

---

## Installing Skills from the Ecosystem

Pulse loads any skill that follows the [agentskills.io](https://agentskills.io) standard:

```bash
# From a local directory
pulse skills install ./examples/skills/research-paper-writing

# From a git repository
pulse skills install https://github.com/user/some-skill.git
```

---

## Skill Evaluation Loop (the key differentiator)

```
candidate ──eval(pass)──▶ promoted ──eval(regress)──▶ quarantined
    │                          │                            │
    └──eval(fail)──▶ deprecated ◀──rollback──promoted ◀─────┘
```

Every self-evolved skill MUST pass a golden-task replay before promotion.
Promotions and rollbacks are explicit, reversible, and versioned.

```bash
pulse skills eval my-candidate-skill       # evaluate against golden tasks
pulse skills promote my-candidate-skill     # bump version + set promoted
pulse skills rollback my-skill --to 1.0.0  # revert to a previous version
```

---

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest -q   # 96 tests, all pass
```

Tests cover: agentskills.io skill loading | evaluation loop (promote/deprecate/rollback) |
error classification + retry | context budget overflow | orchestrator fault tolerance |
sub-agent pool + error isolation | plugin discovery + activation | dialectic profiling |
RL trajectory export | team orchestration.

---

## Roadmap

- [x] **M1** — Core orchestrator, memory, skill eval loop, agentskills compat, CLI wizard
- [x] **M2** — Multi-platform gateways (TUI, Telegram) + scheduler
- [x] **M3** — Sub-agent parallel pool + cron enhancement
- [x] **M4** — RL trajectory export + dialectic user modeling
- [x] **M5** — Plugin system + multi-agent team orchestration

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
