"""Enterprise features: audit logging, RBAC/ABAC, SSO integration."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---- Audit Logging ----

class AuditLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass
class AuditEntry:
    timestamp: float
    user_id: str
    action: str
    resource: str
    result: str  # "success" | "failure" | "denied"
    detail: str = ""
    ip: str = ""
    level: AuditLevel = AuditLevel.INFO

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "action": self.action,
            "resource": self.resource,
            "result": self.result,
            "detail": self.detail,
            "ip": self.ip,
            "level": self.level.value,
        }


class AuditLogger:
    """Centralized audit logger. Writes to file and optionally to external SIEM."""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.log_dir / f"audit-{int(time.time())}.log"
        self._entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        """Write an audit entry."""
        self._entries.append(entry)
        try:
            with self._file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("audit log write failed")

    def query(self, user_id: str = "", action: str = "", limit: int = 100) -> list[AuditEntry]:
        """Query audit entries."""
        results = self._entries
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if action:
            results = [e for e in results if e.action == action]
        return results[-limit:]


# ---- RBAC / ABAC ----

class Permission(str, Enum):
    # Skill permissions
    SKILL_READ = "skill:read"
    SKILL_WRITE = "skill:write"
    SKILL_DELETE = "skill:delete"
    SKILL_EVAL = "skill:eval"
    # Memory permissions
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_DELETE = "memory:delete"
    # Tool permissions
    TOOL_USE = "tool:use"
    TOOL_MANAGE = "tool:manage"
    # Session permissions
    SESSION_READ = "session:read"
    SESSION_DELETE = "session:delete"
    # Admin permissions
    ADMIN_FULL = "admin:full"
    AUDIT_READ = "audit:read"
    USER_MANAGE = "user:manage"


@dataclass
class Role:
    """RBAC role with a set of permissions."""
    name: str
    permissions: set[Permission] = field(default_factory=set)
    description: str = ""

    def has_permission(self, perm: Permission) -> bool:
        return Permission.ADMIN_FULL in self.permissions or perm in self.permissions


@dataclass
class User:
    """User with roles and optional attributes for ABAC."""
    id: str
    name: str
    roles: list[Role] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)  # department, team, clearance_level, etc.
    is_active: bool = True

    def has_permission(self, perm: Permission) -> bool:
        return any(role.has_permission(perm) for role in self.roles)

    def has_attribute(self, key: str, value: Any) -> bool:
        return self.attributes.get(key) == value


# Predefined roles
ROLES = {
    "viewer": Role(
        name="viewer",
        permissions={Permission.SKILL_READ, Permission.MEMORY_READ, Permission.SESSION_READ},
        description="Read-only access"
    ),
    "operator": Role(
        name="operator",
        permissions={
            Permission.SKILL_READ, Permission.SKILL_EVAL,
            Permission.MEMORY_READ, Permission.MEMORY_WRITE,
            Permission.TOOL_USE, Permission.SESSION_READ, Permission.SESSION_DELETE,
        },
        description="Day-to-day operator"
    ),
    "developer": Role(
        name="developer",
        permissions={
            Permission.SKILL_READ, Permission.SKILL_WRITE, Permission.SKILL_EVAL,
            Permission.MEMORY_READ, Permission.MEMORY_WRITE, Permission.MEMORY_DELETE,
            Permission.TOOL_USE, Permission.TOOL_MANAGE,
            Permission.SESSION_READ, Permission.SESSION_DELETE,
        },
        description="Developer with write access"
    ),
    "admin": Role(
        name="admin",
        permissions={Permission.ADMIN_FULL},
        description="Full administrator access"
    ),
    "auditor": Role(
        name="auditor",
        permissions={Permission.AUDIT_READ, Permission.SKILL_READ, Permission.SESSION_READ},
        description="Security auditor"
    ),
}

# Predefined users
USERS = {
    "admin": User(id="admin", name="Administrator", roles=[ROLES["admin"]]),
    "operator": User(id="operator", name="Operator", roles=[ROLES["operator"]]),
    "viewer": User(id="viewer", name="Viewer", roles=[ROLES["viewer"]]),
    "developer": User(id="developer", name="Developer", roles=[ROLES["developer"]]),
    "auditor": User(id="auditor", name="Auditor", roles=[ROLES["auditor"]]),
}


class AuthManager:
    """Manages users, roles, and permission checking."""

    def __init__(self) -> None:
        self._users: dict[str, User] = dict(USERS)
        self._sessions: dict[str, str] = {}  # token -> user_id

    def authenticate(self, username: str, password: str) -> Optional[str]:
        """Authenticate and return a session token."""
        user = self._users.get(username)
        if not user or not user.is_active:
            return None
        # In production, verify password hash here
        token = hashlib.sha256(f"{username}:{time.time()}".encode()).hexdigest()
        self._sessions[token] = user.id
        return token

    def get_user(self, token: str) -> Optional[User]:
        """Get user from session token."""
        user_id = self._sessions.get(token)
        if not user_id:
            return None
        return self._users.get(user_id)

    def check_permission(self, token: str, perm: Permission) -> bool:
        """Check if the user has a permission."""
        user = self.get_user(token)
        if not user:
            return False
        return user.has_permission(perm)

    def logout(self, token: str) -> None:
        """Invalidate a session."""
        self._sessions.pop(token, None)


# ---- SSO Integration (OIDC/SAML stub) ----

class SSOProvider:
    """SSO provider stub. In production, integrate with SAML/OIDC provider."""

    def __init__(self, provider_url: str, client_id: str, client_secret: str) -> None:
        self.provider_url = provider_url
        self.client_id = client_id
        self.client_secret = client_secret

    def get_login_url(self, redirect_uri: str) -> str:
        """Generate SSO login URL."""
        return f"{self.provider_url}/authorize?client_id={self.client_id}&redirect_uri={redirect_uri}"

    def exchange_code(self, code: str) -> dict:
        """Exchange authorization code for user info. Stub."""
        return {"sub": "user123", "name": "SSO User", "email": "user@example.com"}


__all__ = [
    "AuditLevel", "AuditEntry", "AuditLogger",
    "Permission", "Role", "User",
    "ROLES", "USERS", "AuthManager",
    "SSOProvider",
]
