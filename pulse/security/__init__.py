"""Security module: secret redaction, command approval, and filesystem checkpoints."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Optional

# --- Secret Redaction ---

# Patterns for common secrets
SECRET_PATTERNS = [
    # API keys
    (re.compile(r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{16,64})["\']?'), r'\1=***'),
    (re.compile(r'(?i)(secret[_-]?key|secretkey)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{16,64})["\']?'), r'\1=***'),
    (re.compile(r'(?i)(access[_-]?token|auth[_-]?token)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{16,64})["\']?'), r'\1=***'),
    # Bearer tokens
    (re.compile(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}'), r'bearer ***'),
    # Private keys
    (re.compile(r'-----BEGIN (RSA |EC |DSA |OPENSSH |PRIVATE )?PRIVATE KEY-----.*?-----END', re.DOTALL), r'[PRIVATE KEY REDACTED]'),
    # Generic hex/hash tokens (32+ hex chars)
    (re.compile(r'\b[a-f0-9]{32,}\b', re.IGNORECASE), lambda m: m.group(0)[:4] + '***' if len(m.group(0)) > 16 else m.group(0)),
    # Password in URL
    (re.compile(r'(?i)://[^:\s]+:([^@]+)@'), r'://***:***@'),
]

# Environment variable names that should always be redacted
SENSITIVE_ENV_VARS = {
    'API_KEY', 'APIKEY', 'SECRET_KEY', 'SECRETKEY', 'ACCESS_TOKEN', 'AUTH_TOKEN',
    'PASSWORD', 'PASSWD', 'CREDENTIALS', 'PRIVATE_KEY', 'API_SECRET', 'TOKEN',
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY',
    'GOOGLE_API_KEY', 'GEMINI_API_KEY', 'XAI_API_KEY', 'MINIMAX_API_KEY',
}


def redact_secrets(text: str, enabled: bool = True) -> str:
    """Redact sensitive strings from tool output.

    Replaces API keys, tokens, private keys, and passwords with ***.
    Works on arbitrary text (tool output, logs, captured stdout).
    """
    if not enabled or not text:
        return text
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_env(env_dict: Optional[dict] = None, enabled: bool = True) -> dict:
    """Return a copy of env dict with sensitive values masked."""
    if not enabled:
        return env_dict or {}
    result = env_dict.copy() if env_dict else {}
    for key in result:
        if any(s in key.upper() for s in SENSITIVE_ENV_VARS):
            val = str(result[key])
            result[key] = val[:4] + '***' if len(val) > 4 else '***'
    return result


# --- Command Approval ---

# Commands that require user confirmation
DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+(-[rfRF]+\s+)*\s*[/\*]'),          # rm -rf /
    re.compile(r'\brm\s+-fr\s+'),                           # rm -fr
    re.compile(r'\brm\s+-rf\s+'),                           # rm -rf
    re.compile(r'\bgit\s+reset\s+--hard'),                  # git reset --hard
    re.compile(r'\bgit\s+push\s+--force'),                  # git push --force
    re.compile(r'\bgit\s+push\s+-f\b'),                     # git push -f
    re.compile(r'\bgit\s+clean\s+-ff?d'),                   # git clean -ffd
    re.compile(r'\bdd\s+'),                                 # dd
    re.compile(r'\bmkfs\s+'),                               # mkfs
    re.compile(r'\bshred\s+'),                              # shred
    re.compile(r'\bchmod\s+(-[rRfF]+\s+)?777\b'),           # chmod 777
    re.compile(r'\bchown\s+(-[rRfF]+\s+)?\s*root\b'),         # chown root
    re.compile(r'>\s*/dev/sd[a-z]'),                        # direct disk writes
    re.compile(r'\b:()\s*\{\s*:\s*::\s*-\s*\}\s*;'),           # fork bomb
]

# Commands that are always blocked
BLOCKED_PATTERNS = [
    re.compile(r'\brm\s+-rf\s+/\s*(/|#|$)'),                # rm -rf / (root)
    re.compile(r'\bdd\s+if=/dev/zero\s+of=/dev/sd'),        # overwrite disk
]


class ApprovalMode:
    OFF = "off"           # no approval needed (yolo)
    MANUAL = "manual"     # always prompt for dangerous
    SMART = "smart"       # skip obvious safe, prompt on dangerous


def requires_approval(command: str, mode: str = ApprovalMode.MANUAL) -> bool:
    """Check if a shell command requires user approval."""
    if mode == ApprovalMode.OFF:
        return False
    if not command or not command.strip():
        return False
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return True
    if mode == ApprovalMode.MANUAL:
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(command):
                return True
    elif mode == ApprovalMode.SMART:
        # Smart mode: only flag truly destructive ops
        for pattern in DANGEROUS_PATTERNS[:6]:  # rm -rf, git reset --hard, etc.
            if pattern.search(command):
                return True
    return False


def is_blocked(command: str) -> bool:
    """Check if a command is always blocked (too dangerous to run even with approval)."""
    if not command:
        return False
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return True
    return False


# --- Filesystem Checkpoints ---

def create_checkpoint(path: Path, label: str = "", max_snapshots: int = 50) -> Optional[Path]:
    """Create a snapshot of a file or directory.

    Returns the snapshot path, or None if the source doesn't exist.
    Snapshots are stored in ~/.pulse/checkpoints/<hash>/<timestamp>/
    """
    path = Path(path)
    if not path.exists():
        return None

    base = Path.home() / ".pulse" / "checkpoints"
    content_hash = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    ts = int(__import__('time').time() * 1000)
    suffix = f"_{label}" if label else ""
    dest = base / content_hash / f"{ts}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    # Prune old snapshots
    snapshots = sorted(dest.parent.iterdir())
    while len(snapshots) > max_snapshots:
        old = snapshots.pop(0)
        if old.is_dir():
            shutil.rmtree(old)
        else:
            old.unlink()

    return dest


def restore_checkpoint(source: Path, dest: Path) -> bool:
    """Restore a file or directory from a checkpoint snapshot."""
    source = Path(source)
    dest = Path(dest)
    if not source.exists():
        return False
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    if source.is_dir():
        shutil.copytree(source, dest)
    else:
        shutil.copy2(source, dest)
    return True


def list_checkpoints(path: Optional[Path] = None) -> list[dict]:
    """List all available checkpoints, optionally filtered by original path."""
    base = Path.home() / ".pulse" / "checkpoints"
    if not base.exists():
        return []
    results = []
    if path is not None:
        content_hash = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]
        search_dirs = [base / content_hash] if (base / content_hash).exists() else []
    else:
        search_dirs = sorted(base.iterdir())
    for dir_ in search_dirs:
        if not dir_.is_dir():
            continue
        for snap in sorted(dir_.iterdir()):
            stat = snap.stat()
            results.append({
                "path": str(snap),
                "original_hash": dir_.name,
                "created_at": stat.st_mtime,
                "is_dir": snap.is_dir(),
            })
    return results


__all__ = [
    "redact_secrets", "redact_env",
    "requires_approval", "is_blocked", "ApprovalMode",
    "create_checkpoint", "restore_checkpoint", "list_checkpoints",
]
