# Twitter / X thread

**1/ (hook)**
Built Pulse — a self-improving AI agent that fixes the 4 things I hated about the Hermes-Agent concept: it broke on long tasks, shipped unverified skills, was a pain to set up, and leaned on the cloud.

Runs fully local (Ollama + SQLite). Apache 2.0. 🧵

**2/**
Reliability-first core: every LLM/tool call goes through classified error recovery + exponential backoff + a hard token-budget guardrail. Long tasks stop silently falling over.

**3/**
Skills are *verified*, not vibes: a generated skill can only be promoted after passing a golden-task replay. promote / quarantine / rollback is a versioned state machine.

**4/**
v0.3.0 adds MCP: connect ANY stdio MCP server and its tools become first-class agent tools — no SDK dependency. Lazy/parallel loading, auto-reconnect, inputSchema validation.

`pulse mcp add fs "npx -y @modelcontextprotocol/server-filesystem /tmp"`

**5/**
Zero-config, self-hosted: `pulse init --yes` with Ollama auto-detect + `pulse doctor` self-check. Plus multi-agent fork/team, dialectic user modeling, plugin sandbox, cron.

130 tests on Py 3.11/3.12, ruff clean.

GitHub: https://github.com/Alex663028/pulse-agent

Feedback welcome 👇
