# Reddit — r/LocalLLaMA (primary), cross-post r/selfhosted, r/LLMDevs, r/AutoAgents

**Title:** Pulse: a self-improving local-first AI agent (Ollama + SQLite, no cloud) — now with MCP support

**Body:**

Sharing a project I've been building: **Pulse**, a self-improving personal agent that runs entirely on your own hardware by default — Ollama for the model, local SQLite FTS5 for memory. No API key required to get started.

Why another agent framework? It's aimed squarely at the Hermes-Agent-style "autonomous self-improving agent" concept, but rebuilt around reliability and local hosting:

- **Local-first**: `pulse init --yes --provider ollama` just works if Ollama is running. Cloud (OpenAI/OpenRouter/DeepSeek) is opt-in.
- **Reliability guardrails**: classified error recovery + exponential backoff + hard token budget, so multi-step tasks don't die halfway.
- **Verified skills**: auto-generated skills must pass a golden-task replay before they're promoted — `promote / quarantine / rollback` with versioning.
- **MCP (v0.3.0)**: plug in any stdio MCP server (`npx -y @modelcontextprotocol/server-filesystem`, etc.) and its tools become available to the agent. Lazy/parallel loading, auto-reconnect, argument validation.
- **Multi-agent**: `pulse fork` (parallel sub-agents) and `pulse team` (Builder→Reviewer→Ship).
- **Dialectic user modeling**: a self-hosted alternative to Honcho.

It's Apache 2.0, ~5k LOC, 130 tests on 3.11/3.12.

- GitHub: https://github.com/Alex663028/pulse-agent
- Try it: `pip install -e . && pulse init --yes --provider ollama && pulse chat "summarize my ~/notes folder"`

Curious what this community thinks — especially around local memory/retrieval and MCP tool-use patterns. What would make this actually useful day-to-day on a local box?
