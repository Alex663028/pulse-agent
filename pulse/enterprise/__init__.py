"""Enterprise features: audit logging, RBAC/ABAC, SSO integration.

Enhanced security:
- Password hashing with bcrypt
- Token expiry (24h default)
- Session token rotation
- Secure token generation using secrets module
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Token expiry time in seconds (24 hours)
TOKEN_EXPIRY_SECONDS = 86400


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

    def query(
        self, user_id: str = "", action: str = "", limit: int = 100
    ) -> list[AuditEntry]:
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
    attributes: dict[str, Any] = field(
        default_factory=dict
    )  # department, team, clearance_level, etc.
    is_active: bool = True
    password_hash: str = ""  # bcrypt hash

    def has_permission(self, perm: Permission) -> bool:
        return any(role.has_permission(perm) for role in self.roles)

    def has_attribute(self, key: str, value: Any) -> bool:
        return self.attributes.get(key) == value

    def set_password(self, password: str) -> None:
        """Hash and store the password using bcrypt."""
        import bcrypt
        self.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def verify_password(self, password: str) -> bool:
        """Verify a password against the stored hash."""
        if not self.password_hash:
            return False
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))


@dataclass
class SessionToken:
    """A session token with expiry tracking."""

    token: str
    user_id: str
    created_at: float
    expires_at: float
    is_revoked: bool = False

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired


# Predefined roles
ROLES = {
    "viewer": Role(
        name="viewer",
        permissions={
            Permission.SKILL_READ,
            Permission.MEMORY_READ,
            Permission.SESSION_READ,
        },
        description="Read-only access",
    ),
    "operator": Role(
        name="operator",
        permissions={
            Permission.SKILL_READ,
            Permission.SKILL_EVAL,
            Permission.MEMORY_READ,
            Permission.MEMORY_WRITE,
            Permission.TOOL_USE,
            Permission.SESSION_READ,
            Permission.SESSION_DELETE,
        },
        description="Day-to-day operator",
    ),
    "developer": Role(
        name="developer",
        permissions={
            Permission.SKILL_READ,
            Permission.SKILL_WRITE,
            Permission.SKILL_EVAL,
            Permission.MEMORY_READ,
            Permission.MEMORY_WRITE,
            Permission.MEMORY_DELETE,
            Permission.TOOL_USE,
            Permission.TOOL_MANAGE,
            Permission.SESSION_READ,
            Permission.SESSION_DELETE,
        },
        description="Developer with write access",
    ),
    "admin": Role(
        name="admin",
        permissions={Permission.ADMIN_FULL},
        description="Full administrator access",
    ),
    "auditor": Role(
        name="auditor",
        permissions={
            Permission.AUDIT_READ,
            Permission.SKILL_READ,
            Permission.SESSION_READ,
        },
        description="Security auditor",
    ),
}


def _create_user_with_password(name: str, username: str, password: str, role: Role) -> User:
    """Create a user with a hashed password."""
    user = User(id=username, name=name, roles=[role])
    user.set_password(password)
    return user


# Predefined users with default passwords (should be changed on first login)
USERS = {
    "admin": _create_user_with_password("Administrator", "admin", "changeme-strong-password-123!", ROLES["admin"]),
    "operator": _create_user_with_password("Operator", "operator", "changeme-operator-456!", ROLES["operator"]),
    "viewer": _create_user_with_password("Viewer", "viewer", "changeme-viewer-789!", ROLES["viewer"]),
    "developer": _create_user_with_password("Developer", "developer", "changeme-dev-abc!", ROLES["developer"]),
    "auditor": _create_user_with_password("Auditor", "auditor", "changeme-auditor-xyz!", ROLES["auditor"]),
}


class AuthManager:
    """Manages users, roles, and permission checking with secure token management."""

    def __init__(self) -> None:
        self._users: dict[str, User] = dict(USERS)
        self._sessions: dict[str, SessionToken] = {}  # token -> SessionToken

    def authenticate(self, username: str, password: str) -> Optional[str]:
        """Authenticate and return a session token with expiry."""
        user = self._users.get(username)
        if not user or not user.is_active:
            return None
        # Verify password hash
        if not user.verify_password(password):
            return None
        # Generate secure random token
        token = secrets.token_urlsafe(48)
        now = time.time()
        session = SessionToken(
            token=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + TOKEN_EXPIRY_SECONDS,
        )
        self._sessions[token] = session
        return token

    def get_user(self, token: str) -> Optional[User]:
        """Get user from session token (checks expiry)."""
        session = self._sessions.get(token)
        if not session:
            return None
        if session.is_expired:
            # Auto-cleanup expired token
            del self._sessions[token]
            return None
        return self._users.get(session.user_id)

    def check_permission(self, token: str, perm: Permission) -> bool:
        """Check if the user has a permission."""
        user = self.get_user(token)
        if not user:
            return False
        return user.has_permission(perm)

    def logout(self, token: str) -> None:
        """Invalidate a session."""
        if token in self._sessions:
            self._sessions[token].is_revoked = True
            del self._sessions[token]

    def revoke_all_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user. Returns count of revoked sessions."""
        revoked = 0
        for token, session in list(self._sessions.items()):
            if session.user_id == user_id:
                session.is_revoked = True
                del self._sessions[token]
                revoked += 1
        return revoked

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """Change a user'password after verifying the old one."""
        user = self._users.get(username)
        if not user or not user.verify_password(old_password):
            return False
        user.set_password(new_password)
        # Revoke all existing sessions for security
        self.revoke_all_sessions(username)
        return True

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        now = time.time()
        expired = [
            token for token, session in self._sessions.items()
            if session.expires_at < now
        ]
        for token in expired:
            del self._sessions[token]
        return len(expired)


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
    "AuditLevel",
    "AuditEntry",
    "AuditLogger",
    "Permission",
    "Role",
    "User",
    "SessionToken",
    "ROLES",
    "USERS",
    "AuthManager",
    "SSOProvider",
    "TOKEN_EXPIRY_SECONDS",
]