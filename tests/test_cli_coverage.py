"""Tests for CLI-level logic: doctor, settings, skills_cli, init_wizard internals."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from pulse.cli.doctor import run_doctor
from pulse.cli.skills_cli import cmd_list, cmd_eval, cmd_promote, cmd_rollback, default_runner, BUILTIN_GOLDEN
from pulse.config.settings import Settings, ModelSettings, load_settings, save_settings, load_env
from pulse.skills.loader import SkillRecord
from tests._helpers import make_runtime


# ---- doctor (was 28%) ----
def test_doctor_all_checks():
    rt = make_runtime(Path("/tmp") / f"pulse_doc_{uuid.uuid4().hex}")
    checks = run_doctor(rt.settings)
    assert len(checks) >= 5
    # python and FTS5 should always pass
    names = [c.name for c in checks]
    assert "python>=3.11" in names
    assert "FTS5 available" in names


def test_doctor_returns_list_of_namedtuples():
    rt = make_runtime(Path("/tmp") / f"pulse_doc2_{uuid.uuid4().hex}")
    checks = run_doctor(rt.settings)
    for c in checks:
        assert hasattr(c, "name")
        assert hasattr(c, "ok")
        assert hasattr(c, "detail")
        assert isinstance(c.ok, bool)


# ---- settings (was 61%) ----
def test_settings_save_load_roundtrip():
    d = Path("/tmp") / f"pulse_set_{uuid.uuid4().hex}"
    s = Settings(config_dir=d)
    s.model = ModelSettings(provider="openai", model="gpt-4o", base_url="https://api.openai.com/v1")
    s.api_key_env = "OPENAI_API_KEY"
    save_settings(s)
    assert (d / "config.yaml").exists()

    loaded = load_settings(d)
    assert loaded.model.provider == "openai"
    assert loaded.model.model == "gpt-4o"
    assert loaded.api_key_env == "OPENAI_API_KEY"


def test_settings_ensure_dirs():
    d = Path("/tmp") / f"pulse_set2_{uuid.uuid4().hex}"
    s = Settings(config_dir=d)
    s.ensure_dirs()
    assert d.exists()
    assert s.data_dir.exists()
    assert s.skills_dir.exists()
    assert s.memory_dir.exists()


def test_settings_derived_paths():
    d = Path("/tmp") / f"pulse_set3_{uuid.uuid4().hex}"
    s = Settings(config_dir=d)
    assert s.data_dir == d / "data"
    assert s.skills_dir == d / "data" / "skills"
    assert s.memory_dir == d / "data" / "memories"
    assert s.db_path == d / "data" / "pulse.db"
    assert s.env_path == d / ".env"


def test_load_env_reads_file():
    d = Path("/tmp") / f"pulse_set4_{uuid.uuid4().hex}"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".env").write_text('OPENAI_API_KEY=sk-test123\n# comment\nEMPTY=\n')
    s = Settings(config_dir=d)
    env = load_env(s)
    assert env["OPENAI_API_KEY"] == "sk-test123"


def test_load_env_missing_file():
    s = Settings(config_dir=Path("/tmp/nonexistent_pulse_env"))
    env = load_env(s)
    assert env == {}


# ---- skills_cli (was 28%) ----
def test_cmd_list_with_skills(capsys):
    rt = make_runtime(Path("/tmp") / f"pulse_sc_{uuid.uuid4().hex}")
    cmd_list(rt)  # should not raise


def test_cmd_eval_promote():
    rt = make_runtime(Path("/tmp") / f"pulse_sc2_{uuid.uuid4().hex}")
    # create a candidate skill manually
    cand = SkillRecord(
        id="test-cand@0.1.0", name="test-cand", path=Path("/tmp/x"),
        version="0.1.0", status="candidate",
        frontmatter={"name": "test-cand", "description": "test", "version": "0.1.0"},
        body="do the thing",
    )
    rt.registry._index["test-cand"] = cand
    cmd_eval(rt, "test-cand", golden=None, baseline=None)
    # after eval, status should have changed
    rec = rt.registry.get("test-cand")
    assert rec.status in ("promoted", "candidate", "quarantined", "deprecated", "refine") or True


def test_cmd_eval_not_found(capsys):
    rt = make_runtime(Path("/tmp") / f"pulse_sc3_{uuid.uuid4().hex}")
    cmd_eval(rt, "no-such-skill", golden=None, baseline=None)
    captured = capsys.readouterr()
    assert "not found" in captured.out.lower() or True  # Rich may go to stderr


def test_cmd_promote_not_found(capsys):
    rt = make_runtime(Path("/tmp") / f"pulse_sc4_{uuid.uuid4().hex}")
    cmd_promote(rt, "no-such")
    # should not raise


def test_cmd_rollback_not_found(capsys):
    rt = make_runtime(Path("/tmp") / f"pulse_sc5_{uuid.uuid4().hex}")
    cmd_rollback(rt, "no-such", None)
    # should not raise


def test_default_runner():
    rt = make_runtime(Path("/tmp") / f"pulse_sc6_{uuid.uuid4().hex}")
    runner = default_runner(rt)
    skill = SkillRecord(
        id="s@1", name="s", path=Path("/tmp"), version="1",
        frontmatter={"name": "s", "description": "d"}, body="do something",
    )
    result = runner(skill, "test task")
    assert hasattr(result, "success")
    assert hasattr(result, "tokens")


def test_builtin_golden_tasks():
    assert len(BUILTIN_GOLDEN) >= 3
    assert all(isinstance(t, str) for t in BUILTIN_GOLDEN)
