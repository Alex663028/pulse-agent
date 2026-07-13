# Pulse — Hermes-style Self-improving AI Agent (Reliability-First)

[![Tests](https://img.shields.io/badge/tests-42%20passed-brightgreen)](https://github.com)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Lines](https://img.shields.io/badge/code-4500%2B%20lines-blue)](https://github.com)

A **self-improving personal AI agent** rebuilt from the ground up — inspired by
[Nous Research's Hermes Agent](https://github.com/nousresearch/hermes-agent),
with its three biggest weaknesses fixed as first-class concerns, while
remaining **fully compatible with the [agentskills.io](https://agentskills.io)
open standard and Hermes' skill format**.

**Default stack is fully self-hosted** — Ollama + SQLite FTS5, zero cloud dependency.

---

## Why Pulse (vs Hermes)

| Hermes weakness | Pulse's fix |
|---|---|
| **Reliability** — early version, 780+ issues, fragile sub-agents | Every LLM/tool call wrapped in classified error recovery + exponential backoff + hard token budget |
| **Skill quality unverified** — auto-generated skills promoted blindly | **Evaluation loop**: golden-task replay → success-rate/token comparison → `promote / quarantine / rollback` state machine |
| **Steep onboarding** — complex setup, long time-to-value | `pulse init --yes` zero-config, Rich visual feedback, starter skills, `pulse doctor` self-check |
| **Cloud lock-in** (Honcho / Modal / Nous Portal) | Default Ollama + local SQLite FTS5; any cloud API is opt-in |
| **Single-agent ceiling** | Multi-agent team (Builder→Reviewer→Ship), sub-agent pool with failure isolation |

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

Pulse loads any skill that follows the [agentskills.io](https://agentskills.io) standard or Hermes' extended format:

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
python -m pytest -q   # 42 tests, all pass
```

Tests cover: Hermes skill loading | evaluation loop (promote/deprecate/rollback) |
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

MIT — same as Hermes.
