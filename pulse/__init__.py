"""Pulse — a Hermes-style self-improving personal AI agent.

Rebuilt with a lightweight, reliability-first core that fixes three of Hermes'
weak spots:
  1. Reliability/stability  -> orchestrator with error recovery + token budget
  2. Skill self-evolution quality -> an *evaluated* skill loop (promote/rollback)
  3. Onboarding/UX          -> zero-config `pulse init` wizard + Rich CLI

Compatible with the agentskills.io open standard and Hermes' extended skill
format, so existing ecosystem skills can be reused directly.
"""

__version__ = "0.1.0"
__codename__ = "Pulse"
