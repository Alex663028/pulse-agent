# Show HN — Pulse: a self-improving AI agent that fixes Hermes' weak spots

**Title:** Show HN: Pulse – a self-improving AI agent that fixes Hermes' weak spots (reliability, verified skills, self-hosted)

**Body:**

I kept reaching for the Hermes Agent idea — an autonomous, self-improving personal agent — but kept getting stopped by the same four things: it broke on long tasks, its auto-generated skills shipped unverified, setup was fiddly, and it leaned on the cloud. So I rebuilt the concept as **Pulse** (Apache 2.0, Python CLI).

What's different:

- **Reliability-first core** — every LLM/tool call goes through classified error recovery + exponential backoff + a hard token-budget guardrail, so long tasks don't silently fall over.
- **Verified skill self-evolution** — a skill can only be *promoted* after passing a golden-task replay. `promote / quarantine / rollback` is a versioned state machine, not vibes.
- **Zero-config, self-hosted by default** — `pulse init --yes` with Ollama auto-detection, `pulse doctor` self-check. No mandatory cloud. Runs fully on Ollama + local SQLite FTS5.
- **MCP in v0.3.0** — connect any stdio Model Context Protocol server; its tools become first-class Pulse tools with **no SDK dependency**. Lazy/parallel loading, auto-reconnect, inputSchema validation, and a live health view in `pulse mcp list`.

Also: multi-agent `fork`/`team` pipelines, dialectic user modeling (a self-hosted Honcho alternative), a plugin sandbox, cron scheduling, and an RL trajectory export pipeline.

130 tests passing on Python 3.11 + 3.12, ruff clean.

- Repo: https://github.com/Alex663028/pulse-agent
- Quick start: `pip install -e . && pulse init --yes --provider ollama && pulse mcp add fs "npx -y @modelcontextprotocol/server-filesystem /tmp"`

Would love feedback from anyone who's hit the same Hermes frustrations — especially on the skill-evaluation loop and MCP ergonomics.
