"""Tests for enterprise features: audit logging, RBAC/ABAC, SSO."""
from __future__ import annotations


from pulse.enterprise import (
    AuditEntry, AuditLogger, AuthManager, Permission, USERS, SSOProvider,
)


class TestAuditLogger:
    def test_log_and_query(self, tmp_path):
        al = AuditLogger(tmp_path / "audit")
        entry = AuditEntry(
            timestamp=1000.0, user_id="admin", action="skill:promote",
            resource="my-skill", result="success",
        )
        al.log(entry)
        results = al.query()
        assert len(results) == 1
        assert results[0].user_id == "admin"

    def test_filter_by_user(self, tmp_path):
        al = AuditLogger(tmp_path / "audit")
        al.log(AuditEntry(timestamp=1.0, user_id="admin", action="a", resource="r", result="success"))
        al.log(AuditEntry(timestamp=2.0, user_id="viewer", action="a", resource="r", result="success"))
        assert len(al.query(user_id="admin")) == 1


class TestRBAC:
    def test_admin_has_all_permissions(self):
        admin = USERS["admin"]
        assert admin.has_permission(Permission.SKILL_READ)
        assert admin.has_permission(Permission.ADMIN_FULL)

    def test_viewer_limited_permissions(self):
        viewer = USERS["viewer"]
        assert viewer.has_permission(Permission.SKILL_READ)
        assert not viewer.has_permission(Permission.SKILL_WRITE)

    def test_operator_can_use_tools(self):
        op = USERS["operator"]
        assert op.has_permission(Permission.TOOL_USE)

    def test_auditor_can_read_audit(self):
        auditor = USERS["auditor"]
        assert auditor.has_permission(Permission.AUDIT_READ)
        assert not auditor.has_permission(Permission.SKILL_WRITE)


class TestAuthManager:
    def test_authenticate(self):
        am = AuthManager()
        token = am.authenticate("admin", "pass")
        assert token is not None
        user = am.get_user(token)
        assert user is not None
        assert user.id == "admin"

    def test_check_permission(self):
        am = AuthManager()
        token = am.authenticate("viewer", "pass")
        assert am.check_permission(token, Permission.SKILL_READ)
        assert not am.check_permission(token, Permission.SKILL_WRITE)

    def test_logout(self):
        am = AuthManager()
        token = am.authenticate("admin", "pass")
        am.logout(token)
        assert am.get_user(token) is None


class TestSSOProvider:
    def test_login_url(self):
        sso = SSOProvider("https://sso.example.com", "client123", "secret")
        url = sso.get_login_url("https://app.example.com/callback")
        assert "client123" in url
        assert "authorize" in url
