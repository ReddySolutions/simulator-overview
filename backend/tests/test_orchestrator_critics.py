"""Tests for PhaseOrchestrator LLM-critic wiring (US-017, US-019)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from walkthrough.ai.orchestrator import PhaseOrchestrator
from walkthrough.models.project import Gap, Project
from walkthrough.models.workflow import SourceRef


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_COLLECTION", "test_projects")


def _project(project_id: str = "proj_crit") -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id=project_id,
        name="Critic Test",
        status="analyzing",
        videos=[],
        pdfs=[],
        decision_trees=[],
        gaps=[],
        questions=[],
        walkthrough_output=None,
        created_at=now,
        updated_at=now,
    )


def _gap(gap_id: str, description: str | None = None) -> Gap:
    return Gap(
        gap_id=gap_id,
        severity="medium",
        description=description or gap_id,
        evidence=[
            SourceRef(source_type="video", reference="v.mp4:00:00", excerpt="x"),
            SourceRef(source_type="pdf", reference="p.pdf:S1", excerpt="y"),
        ],
    )


class TestFlagOff:
    async def test_gaps_unchanged_and_critic_not_called(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "false")

        from walkthrough.ai.tools import detect_contradictions as det_mod
        from walkthrough.ai.tools import (
            detect_contradictions_critic as critic_mod,
        )

        deterministic = [_gap("gap_det1"), _gap("gap_det2")]

        async def _det_stub(videos, pdfs, trees):
            return list(deterministic)

        async def _critic_explode(*args, **kwargs):
            raise AssertionError(
                "critique_contradictions must not run when flag is off"
            )

        monkeypatch.setattr(det_mod, "detect_contradictions", _det_stub)
        monkeypatch.setattr(
            critic_mod, "critique_contradictions", _critic_explode
        )

        orch = PhaseOrchestrator()
        project = _project("proj_off")

        await orch._run_contradictions(project)

        assert [g.gap_id for g in project.gaps] == ["gap_det1", "gap_det2"]
        assert project.status == "clarifying"


class TestFlagOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def test_gaps_include_critic_additions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from walkthrough.ai.tools import detect_contradictions as det_mod
        from walkthrough.ai.tools import (
            detect_contradictions_critic as critic_mod,
        )

        deterministic = [_gap("gap_det1")]
        critic_new = [_gap("gap_llm1"), _gap("gap_llm2")]

        async def _det_stub(videos, pdfs, trees):
            return list(deterministic)

        seen_existing: list[list[str]] = []

        async def _critic_stub(
            videos, pdfs, trees, existing_gaps, *, client=None,
        ):
            seen_existing.append([g.gap_id for g in existing_gaps])
            return list(critic_new)

        monkeypatch.setattr(det_mod, "detect_contradictions", _det_stub)
        monkeypatch.setattr(
            critic_mod, "critique_contradictions", _critic_stub
        )

        orch = PhaseOrchestrator()
        project = _project("proj_on")

        await orch._run_contradictions(project)

        assert [g.gap_id for g in project.gaps] == [
            "gap_det1",
            "gap_llm1",
            "gap_llm2",
        ]
        # Critic was called exactly once with deterministic gaps as existing
        assert seen_existing == [["gap_det1"]]
        assert project.status == "clarifying"

    async def test_deduplicates_overlap_between_deterministic_and_critic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the critic re-emits an already-known gap_id, orchestrator dedup
        keeps the first (deterministic) copy and drops the duplicate."""
        from walkthrough.ai.tools import detect_contradictions as det_mod
        from walkthrough.ai.tools import (
            detect_contradictions_critic as critic_mod,
        )

        deterministic = [_gap("gap_shared"), _gap("gap_det")]
        critic_raw = [
            _gap("gap_shared", description="critic-duplicate"),
            _gap("gap_llm"),
        ]

        async def _det_stub(*args, **kwargs):
            return list(deterministic)

        async def _critic_stub(*args, **kwargs):
            return list(critic_raw)

        monkeypatch.setattr(det_mod, "detect_contradictions", _det_stub)
        monkeypatch.setattr(
            critic_mod, "critique_contradictions", _critic_stub
        )

        orch = PhaseOrchestrator()
        project = _project("proj_dedup")

        await orch._run_contradictions(project)

        # gap_shared keeps deterministic description (first wins)
        assert [g.gap_id for g in project.gaps] == [
            "gap_shared",
            "gap_det",
            "gap_llm",
        ]
        shared = next(g for g in project.gaps if g.gap_id == "gap_shared")
        assert shared.description == "gap_shared"

    async def test_empty_critic_additions_leave_deterministic_intact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from walkthrough.ai.tools import detect_contradictions as det_mod
        from walkthrough.ai.tools import (
            detect_contradictions_critic as critic_mod,
        )

        deterministic = [_gap("gap_only_det")]

        async def _det_stub(*args, **kwargs):
            return list(deterministic)

        async def _critic_stub(*args, **kwargs):
            return []

        monkeypatch.setattr(det_mod, "detect_contradictions", _det_stub)
        monkeypatch.setattr(
            critic_mod, "critique_contradictions", _critic_stub
        )

        orch = PhaseOrchestrator()
        project = _project("proj_empty_critic")

        await orch._run_contradictions(project)

        assert [g.gap_id for g in project.gaps] == ["gap_only_det"]


class TestNarrativeCriticFlagOff:
    async def test_gaps_unchanged_and_critic_not_called(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "false")

        from walkthrough.ai.tools import narrative as narr_mod
        from walkthrough.ai.tools import narrative_critic as narr_critic_mod

        async def _synth_stub(videos, pdfs, trees):
            return list(trees)

        async def _critic_explode(*args, **kwargs):
            raise AssertionError(
                "critique_narratives must not run when flag is off"
            )

        monkeypatch.setattr(narr_mod, "synthesize_narrative", _synth_stub)
        monkeypatch.setattr(
            narr_critic_mod, "critique_narratives", _critic_explode
        )

        orch = PhaseOrchestrator()
        project = _project("proj_narr_off")

        await orch._run_narrative(project)

        assert project.gaps == []


class TestNarrativeCriticFlagOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def test_critic_gaps_appended_to_project_gaps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from walkthrough.ai.tools import narrative as narr_mod
        from walkthrough.ai.tools import narrative_critic as narr_critic_mod

        critic_new = [_gap("gap_narr1"), _gap("gap_narr2")]

        async def _synth_stub(videos, pdfs, trees):
            return list(trees)

        seen_trees: list[int] = []

        async def _critic_stub(decision_trees, *, client=None):
            seen_trees.append(len(decision_trees))
            return list(critic_new)

        monkeypatch.setattr(narr_mod, "synthesize_narrative", _synth_stub)
        monkeypatch.setattr(
            narr_critic_mod, "critique_narratives", _critic_stub
        )

        orch = PhaseOrchestrator()
        project = _project("proj_narr_on")

        await orch._run_narrative(project)

        assert [g.gap_id for g in project.gaps] == ["gap_narr1", "gap_narr2"]
        assert seen_trees == [0]

    async def test_appends_without_overwriting_prior_gaps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prior gaps on project.gaps must survive; new critic gaps are
        appended. Contradictions phase (not this one) handles any dedup."""
        from walkthrough.ai.tools import narrative as narr_mod
        from walkthrough.ai.tools import narrative_critic as narr_critic_mod

        async def _synth_stub(videos, pdfs, trees):
            return list(trees)

        async def _critic_stub(decision_trees, *, client=None):
            return [_gap("gap_narr_new")]

        monkeypatch.setattr(narr_mod, "synthesize_narrative", _synth_stub)
        monkeypatch.setattr(
            narr_critic_mod, "critique_narratives", _critic_stub
        )

        orch = PhaseOrchestrator()
        project = _project("proj_narr_prior")
        project.gaps = [_gap("gap_prior1"), _gap("gap_prior2")]

        await orch._run_narrative(project)

        assert [g.gap_id for g in project.gaps] == [
            "gap_prior1",
            "gap_prior2",
            "gap_narr_new",
        ]
