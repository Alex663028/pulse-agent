# Security Policy

Pulse is an AI agent that can execute shell commands, read/write files, and connect to external APIs. This document describes the security model, supported versions, and how to report vulnerabilities.

---

## Security Model

Pulse provides defense in depth with four layers:

### 1. Command Approval

Dangerous shell commands require user confirmation before execution:

| Mode | Behavior |
|------|----------|
| `manual` | Prompt on `rm -rf`, `git reset --hard`, `chmod 777`, `dd`, `shred`, etc. |
| `smart` | Prompt only on destructive ops (rm -rf, disk wipes) |
| `off` | No prompts (not recommended) |

**Always-blocked commands** (cannot be overridden):
- `rm -rf /` (filesystem wipe)
- `dd if=/dev/zero of=/dev/sda` (disk overwrite)
- Fork bombs

### 2. Secret Redaction

API keys, bearer tokens, and private keys are automatically redacted in tool output:
- `API_KEY=xxx` → `API_KEY=***`
- `Bearer xxx` → `Bearer ***`
- Private key blocks → `[PRIVATE KEY REDACTED]`

### 3. Filesystem Checkpoints

Before write_file or edit_file modifies an existing file, Pulse automatically creates a checkpoint snapshot in `~/.pulse/checkpoints/`. Files can be restored via the `restore_checkpoint()` API.

### 4. Role-Based Access Control (RBAC)

Predefined roles with granular permissions:

| Role | Permissions |
|------|-------------|
| viewer | Read-only (skill/read, memory/read, session/read) |
| operator | Day-to-day operations + tool use + eval |
| developer | Full write access + tool management |
| admin | All permissions |
| auditor | Audit log read + read-only access |

---

## Configuration

Enable security features in `~/.pulse/config.yaml`:

```yaml
# Command approval mode: off | manual | smart
approval_mode: manual

# Automatic secret redaction in tool output
redact_secrets: true

# Enable filesystem checkpoints
checkpoints_enabled: true
```

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.7.x   | ✅ Active development |
| 0.6.x   | ✅ Bug fixes only |
| < 0.6   | ❌ Upgrade recommended |

---

## Reporting a Security Vulnerability

Please **do not** disclose security vulnerabilities publicly (GitHub issues, Discord, etc.).

Instead, report them via:
- Email: (set up a dedicated security email)
- GitHub Security Advisories: https://github.com/Alex663028/pulse-agent/security/advisories

We will:
1. Acknowledge receipt within 48 hours
2. Investigate and provide an initial assessment within 7 days
3. Work on a fix and coordinate disclosure

---

## Best Practices

1. **Use `manual` approval mode** in production environments
2. **Enable secret redaction** to prevent credential leakage in logs
3. **Use checkpoints** before batch file operations
4. **Run with minimal required permissions** — do not run as root
5. **Use multi-profile** to isolate different trust contexts
6. **Review audit logs** regularly (`pulse insights`)
7. **Keep dependencies updated** — run `pip-audit` periodically

---

## Known Limitations

- **Prompt injection**: Like all LLM-based agents, Pulse may be susceptible to prompt injection from untrusted input. Use RBAC to limit blast radius.
- **Credential storage**: API keys are stored in `~/.pulse/.env`. Ensure this file has `0o600` permissions.
- **Network egress**: Tools can make outbound HTTP requests. Use network policies to restrict egress if needed.
- **No end-to-end encryption**: Communication between CLI/TUI and the LLM provider uses standard TLS but is not additionally encrypted.
