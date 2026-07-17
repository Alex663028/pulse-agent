"""Tests for the self-evolution framework."""
from __future__ import annotations

from pulse.evolution import EvolutionAnalyzer, EvolutionEngine, EvolutionProposal, EvolutionSignal


class TestEvolutionSignal:
    def test_to_dict(self):
        s = EvolutionSignal(kind="tool_gap", source="tool:calc", description="test")
        d = s.to_dict()
        assert d["kind"] == "tool_gap"
        assert d["source"] == "tool:calc"
        assert "timestamp" in d


class TestEvolutionAnalyzer:
    def test_empty_storage_returns_no_signals(self, tmp_path):
        from pulse.config.settings import Settings
        from pulse.storage.engine import Storage
        from pulse.skills.registry import SkillRegistry

        settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
        storage = Storage(settings.db_path)
        registry = SkillRegistry(settings, storage)
        analyzer = EvolutionAnalyzer(storage, registry)
        signals = analyzer.analyze()
        assert signals == []

    def test_detects_repeated_failures(self, tmp_path):
        from pulse.config.settings import Settings
        from pulse.storage.engine import Storage
        from pulse.skills.registry import SkillRegistry

        settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
        storage = Storage(settings.db_path)
        registry = SkillRegistry(settings, storage)

        # Log multiple failures with calc tool
        for i in range(5):
            storage.log_trajectory(
                tid=f"t{i}", session_id=f"s{i}", outcome=False,
                used_skills=[], data={"trajectory": [{"action": "tool:calc", "outcome": False, "detail": "error"}]}
            )

        analyzer = EvolutionAnalyzer(storage, registry)
        signals = analyzer.analyze()
        assert any(s.kind == "repeated_failure" and s.source == "tool:calc" for s in signals)

    def test_detects_skill_gap(self, tmp_path):
        from pulse.config.settings import Settings
        from pulse.storage.engine import Storage
        from pulse.skills.registry import SkillRegistry

        settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
        storage = Storage(settings.db_path)
        registry = SkillRegistry(settings, storage)

        # Log multiple successful trajectories with same task prefix
        for i in range(7):
            storage.log_trajectory(
                tid=f"t{i}", session_id=f"s{i}", outcome=True,
                used_skills=[], data={"task": "quarterly report summary and analysis"}
            )

        analyzer = EvolutionAnalyzer(storage, registry)
        signals = analyzer.analyze()
        assert any(s.kind == "skill_gap" for s in signals)


class TestEvolutionEngine:
    def test_generate_proposals_from_signals(self, tmp_path):
        from pulse.config.settings import Settings
        from pulse.storage.engine import Storage
        from pulse.skills.registry import SkillRegistry

        settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
        storage = Storage(settings.db_path)
        registry = SkillRegistry(settings, storage)

        # Log failures to trigger proposal
        for i in range(5):
            storage.log_trajectory(
                tid=f"t{i}", session_id=f"s{i}", outcome=False,
                used_skills=[], data={"trajectory": [{"action": "tool:web_search", "outcome": False, "detail": "timeout"}]}
            )

        analyzer = EvolutionAnalyzer(storage, registry)
        engine = EvolutionEngine(analyzer, settings.skills_dir)
        proposals = engine.generate_proposals()

        assert len(proposals) > 0
        assert any(p.action in ("fix_bug", "improve_skill") for p in proposals)

    def test_apply_add_skill_proposal(self, tmp_path):
        from unittest.mock import MagicMock
        analyzer = EvolutionAnalyzer(MagicMock(), MagicMock())
        engine = EvolutionEngine(analyzer, tmp_path / "skills")

        proposal = EvolutionProposal(
            title="Create skill for report tasks",
            description="Repeated task pattern",
            action="add_skill",
            target="auto-report-summary",
        )

        result = engine.apply_proposal(proposal)
        assert result["status"] == "applied"
