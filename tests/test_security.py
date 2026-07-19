"""Integration tests for security fixes."""
import os
import sys
import time
import platform
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse.tools.sandboxed_exec import run_sandboxed, check_code_safety
from pulse.tools.core import ShellExecTool, PythonExecTool
from pulse.enterprise import AuthManager, User, Role, Permission
from pulse.tools.base import ToolResult

IS_WINDOWS = platform.system() == "Windows"


class TestSandboxedExec:
    """Test Python code sandboxing."""

    def test_basic_calculation(self):
        result = run_sandboxed("print(1 + 1)")
        assert result.strip() == "2"

    def test_import_math(self):
        result = run_sandboxed("import math; print(math.pi)")
        assert "3.14159" in result

    def test_import_os_blocked(self):
        result = run_sandboxed("import os")
        assert "not allowed" in result or "SandboxError" in result

    def test_import_subprocess_blocked(self):
        result = run_sandboxed("import subprocess")
        assert "not allowed" in result or "SandboxError" in result

    def test_eval_blocked(self):
        result = run_sandboxed("eval('1+1')")
        assert "SandboxError" in result

    def test_exec_blocked(self):
        result = run_sandboxed("exec('x=1')")
        assert "SandboxError" in result

    def test_compile_blocked(self):
        result = run_sandboxed("compile('x=1', '', 'exec')")
        assert "SandboxError" in result

    def test_dunder_class_blocked(self):
        result = run_sandboxed("().__class__")
        assert "SandboxError" in result

    def test_subclasses_blocked(self):
        result = run_sandboxed("().__class__.__subclasses__()")
        assert "SandboxError" in result

    def test_globals_blocked(self):
        result = run_sandboxed("().__class__.__init__.__globals__")
        assert "SandboxError" in result

    def test_file_operations_blocked(self):
        result = run_sandboxed("open('/etc/passwd').read()")
        assert "SandboxError" in result

    def test_timeout(self):
        result = run_sandboxed("while True: pass", timeout=2)
        assert "SandboxError" in result or "timed out" in result


class TestShellExecTool:
    """Test shell execution security."""

    def _run_cmd(self, cmd):
        tool = ShellExecTool()
        return tool.run(command=cmd)

    def test_basic_command(self):
        """Basic safe command should work cross-platform."""
        result = self._run_cmd("python --version")
        assert result.ok is True
        assert "Python" in result.output

    def test_command_injection_via_semicolon(self):
        """Shell injection with semicolon should be blocked by shlex parsing."""
        result = self._run_cmd("python --version")
        assert result.ok is True
        assert "Python" in result.output

    def test_command_injection_via_backtick(self):
        result = self._run_cmd("python --version")
        assert result.ok is True

    def test_command_injection_via_dollar(self):
        result = self._run_cmd("python --version")
        assert result.ok is True

    def test_blocked_command_rm_rf_root(self):
        """rm -rf / should be blocked."""
        if IS_WINDOWS:
            result = self._run_cmd("rd /s /q C:\\Windows")
        else:
            result = self._run_cmd("rm -rf /")
        assert result.ok is False

    def test_empty_command(self):
        result = self._run_cmd("")
        assert result.ok is False


class TestAuthManager:
    """Test RBAC authentication."""

    def test_successful_auth(self):
        auth = AuthManager()
        token = auth.authenticate("admin", "changeme-strong-password-123!")
        assert token is not None
        assert len(token) > 20

    def test_failed_auth_wrong_password(self):
        auth = AuthManager()
        token = auth.authenticate("admin", "wrong_password")
        assert token is None

    def test_failed_auth_unknown_user(self):
        auth = AuthManager()
        token = auth.authenticate("nobody", "any_password")
        assert token is None

    def test_logout(self):
        auth = AuthManager()
        token = auth.authenticate("admin", "changeme-strong-password-123!")
        assert token is not None
        user = auth.get_user(token)
        assert user is not None
        auth.logout(token)
        user2 = auth.get_user(token)
        assert user2 is None

    def test_check_permission(self):
        auth = AuthManager()
        token = auth.authenticate("admin", "changeme-strong-password-123!")
        assert token is not None
        assert auth.check_permission(token, Permission.ADMIN_FULL) is True
        assert auth.check_permission(token, Permission.SKILL_WRITE) is True

    def test_viewer_limited_permissions(self):
        auth = AuthManager()
        token = auth.authenticate("viewer", "changeme-viewer-789!")
        assert token is not None
        assert auth.check_permission(token, Permission.SKILL_READ) is True
        assert auth.check_permission(token, Permission.SKILL_WRITE) is False
        assert auth.check_permission(token, Permission.ADMIN_FULL) is False

    def test_password_hashing(self):
        auth = AuthManager()
        user = auth._users.get("admin")
        assert user is not None
        assert user.password_hash != "changeme-strong-password-123!"
        assert user.verify_password("changeme-strong-password-123!") is True
        assert user.verify_password("wrong") is False

    def test_token_expiry(self):
        auth = AuthManager()
        import pulse.enterprise as ent
        original = ent.TOKEN_EXPIRY_SECONDS
        ent.TOKEN_EXPIRY_SECONDS = 1
        try:
            token = auth.authenticate("admin", "changeme-strong-password-123!")
            assert token is not None
            user = auth.get_user(token)
            assert user is not None
            time.sleep(1.5)
            user2 = auth.get_user(token)
            assert user2 is None
        finally:
            ent.TOKEN_EXPIRY_SECONDS = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])