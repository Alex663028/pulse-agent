"""Tests for CLI main commands and Runtime bootstrap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

# ──────────────────────────────────────────────────────────────────────
# Runtime tests
# ──────────────────────────────────────────────────────────────────────


class TestRuntime:
    """Test bootstrap and Runtime dataclass."""

    def test_bootstrap_returns_runtime_with_all_fields(self, tmp_path):
        """bootstrap() returns a Runtime with all required fields."""
        from pulse.cli.runtime import bootstrap

        rt = bootstrap(config_dir=str(tmp_path))
        assert rt.settings is not None
        assert rt.storage is not None
        assert rt.memory is not None
        assert rt.registry is not None
        assert rt.tools is not None
        assert rt.router is not None
        assert rt.obs is not None
        assert rt.orchestrator is not None

    def test_bootstrap_sets_config_dir(self, tmp_path):
        """bootstrap() uses the config_dir parameter."""
        from pulse.cli.runtime import bootstrap

        rt = bootstrap(config_dir=str(tmp_path))
        assert str(rt.settings.config_dir) == str(tmp_path)

    def test_bootstrap_without_mcp(self, tmp_path):
        """bootstrap(load_mcp=False) does not create MCPManager."""
        from pulse.cli.runtime import bootstrap

        rt = bootstrap(config_dir=str(tmp_path), load_mcp=False)
        assert rt.mcp is None

    def test_bootstrap_with_mcp_no_servers_configured(self, tmp_path):
        """bootstrap(load_mcp=True) with no mcp_servers doesn't error."""
        from pulse.cli.runtime import bootstrap

        rt = bootstrap(config_dir=str(tmp_path), load_mcp=True)
        # Either mcp stays None or manager is created
        # No exception means success
        assert rt is not None


# ──────────────────────────────────────────────────────────────────────
# CLI main tests
# ──────────────────────────────────────────────────────────────────────


class TestCliDoctor:
    """Test the doctor CLI command."""

    def test_doctor_command_runs_without_error(self, tmp_path):
        """doctor command completes successfully."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            with patch("pulse.cli.main.run_doctor") as mock_doc:
                mock_doc.return_value = []
                result = runner.invoke(app, ["doctor"])
                assert result.exit_code == 0


class TestCliMemory:
    """Test memory CLI commands."""

    def test_memory_recall_no_matches(self, tmp_path):
        """memory recall with no matches shows a message."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_rt.memory.recall.return_value = []
            mock_boot.return_value = mock_rt
            result = runner.invoke(app, ["memory", "recall", "test query"])
            assert result.exit_code == 0

    def test_memory_add_note(self, tmp_path):
        """memory add succeeds."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            result = runner.invoke(app, ["memory", "add", "remember this"])
            assert result.exit_code == 0

    def test_memory_profile_invalid_action(self, tmp_path):
        """memory profile with invalid action shows error."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            result = runner.invoke(app, ["memory", "profile", "invalid_action"])
            assert result.exit_code == 0  # prints error but doesn't crash

    def test_memory_invalid_action(self, tmp_path):
        """memory with invalid action shows error."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            result = runner.invoke(app, ["memory", "invalid"])
            assert result.exit_code == 0


class TestCliCron:
    """Test cron CLI commands."""

    def test_cron_list_empty(self, tmp_path):
        """cron list with no jobs."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_rt.settings.config_dir = tmp_path
            mock_boot.return_value = mock_rt
            # Create empty cron file
            cron_file = tmp_path / "cron_jobs.json"
            cron_file.write_text("{}")
            result = runner.invoke(app, ["cron", "list"])
            assert result.exit_code == 0

    def test_cron_add_and_remove(self, tmp_path):
        """cron add then remove."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_rt.settings.config_dir = tmp_path
            mock_boot.return_value = mock_rt
            cron_file = tmp_path / "cron_jobs.json"
            cron_file.write_text("{}")

            result = runner.invoke(
                app, ["cron", "add", "--name", "test-job", "test task", "60"]
            )
            assert result.exit_code == 0
            result = runner.invoke(app, ["cron", "remove", "test-job"])
            assert result.exit_code == 0

    def test_cron_remove_not_found(self, tmp_path):
        """cron remove with non-existent job."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_rt.settings.config_dir = tmp_path
            mock_boot.return_value = mock_rt
            cron_file = tmp_path / "cron_jobs.json"
            cron_file.write_text("{}")
            result = runner.invoke(app, ["cron", "remove", "nonexistent"])
            assert result.exit_code == 0

    def test_cron_pause_resume(self, tmp_path):
        """cron pause and resume."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_rt.settings.config_dir = tmp_path
            mock_boot.return_value = mock_rt
            cron_file = tmp_path / "cron_jobs.json"
            cron_file.write_text("{}")

            runner.invoke(app, ["cron", "add", "--name", "test-job", "test task", "60"])
            result = runner.invoke(app, ["cron", "pause", "test-job"])
            assert result.exit_code == 0
            result = runner.invoke(app, ["cron", "resume", "test-job"])
            assert result.exit_code == 0


class TestCliSkills:
    """Test skills CLI commands."""

    def test_skills_list(self, tmp_path):
        """skills list runs."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            result = runner.invoke(app, ["skills", "list"])
            assert result.exit_code == 0


class TestCliRl:
    """Test RL CLI commands."""

    def test_rl_export_default(self, tmp_path):
        """rl export with default args."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            with patch("pulse.rl.export.export_jsonl", return_value=10):
                result = runner.invoke(app, ["rl", "export"])
                assert result.exit_code == 0

    def test_rl_export_sharegpt(self, tmp_path):
        """rl export with sharegpt format."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_boot.return_value = mock_rt
            with patch("pulse.rl.export.export_sharegpt", return_value=5):
                result = runner.invoke(app, ["rl", "export", "--format", "sharegpt"])
                assert result.exit_code == 0


class TestCliPlugin:
    """Test plugin CLI commands."""

    def test_plugin_list_empty(self, tmp_path):
        """plugin list with no plugins."""
        from pulse.cli.main import app

        runner = CliRunner()
        with patch("pulse.cli.main.bootstrap") as mock_boot:
            mock_rt = MagicMock()
            mock_rt.settings.config_dir = tmp_path
            mock_boot.return_value = mock_rt
            result = runner.invoke(app, ["plugin", "list"])
            assert result.exit_code == 0


class TestCliMcp:
    """Test MCP CLI commands."""

    def test_mcp_list(self, tmp_path):
        """mcp list runs."""
        from pulse.cli.main import app

        runner = CliRunner()
        with (
            patch("pulse.cli.mcp_cli.cmd_list") as mock_cmd,
            patch("pulse.config.settings.load_settings") as mock_ls,
        ):
            mock_ls.return_value = MagicMock()
            result = runner.invoke(app, ["mcp", "list"])
            assert result.exit_code == 0
            mock_cmd.assert_called_once()

    def test_mcp_add_and_remove(self, tmp_path):
        """mcp add then remove."""
        from pulse.cli.main import app

        runner = CliRunner()
        with (
            patch("pulse.cli.mcp_cli.cmd_add") as mock_add,
            patch("pulse.cli.mcp_cli.cmd_remove") as mock_remove,
            patch("pulse.config.settings.load_settings") as mock_ls,
        ):
            mock_ls.return_value = MagicMock()
            result = runner.invoke(
                app, ["mcp", "add", "test-server", "npx -y some-server"]
            )
            assert result.exit_code == 0
            mock_add.assert_called_once()
            result = runner.invoke(app, ["mcp", "remove", "test-server"])
            assert result.exit_code == 0
            mock_remove.assert_called_once()
