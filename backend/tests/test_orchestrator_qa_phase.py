"""Tests for PhaseOrchestrator._run_qa (US-010)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from walkthrough.ai.orchestrator import (
    PHASE_ORDER,
    PhaseOrchestrator,
    ProgressEvent,
)
from walkthrough.models.project import Project


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_COLLECTION", "test_projects")
    # Keep LLM critic off so the runner stays hermetic
    monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "false")


def _project(
    project_id: str = "proj_qa_phase",
    *,
    walkthrough_output: dict | None = None,
) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id=project_id,
        name="QA Phase Test",
        status="complete",
        videos=[],
        pdfs=[],
        decision_trees=[],
        gaps=[],
        questions=[],
        walkthrough_output=walkthrough_output,
        created_at=now,
        updated_at=now,
    )


class TestPhaseOrder:
    def test_qa_appended_after_generation(self):
        assert PHASE_ORDER[-1] == "qa"
        assert PHASE_ORDER.index("generation") < PHASE_ORDER.index("qa")


class TestRunQAEndToEnd:
    async def test_writes_qa_artifact_and_attaches_report(
        self, tmp_path: Path
    ) -> None:
        # Pre-populate walkthrough_output as if generation just ran
        orch = PhaseOrchestrator()
        project = _project(walkthrough_output={"metadata": {}})

        events: list[ProgressEvent] = []
        async for event in orch._run_qa(project):
            events.append(event)

        # Two events: 0% start and 100% finish
        assert events[0].phase == "qa"
        assert events[0].percentage == 0
        assert events[-1].phase == "qa"
        assert events[-1].percentage == 100
        assert "critical findings" in events[-1].message

        # qa.json artifact written
        artifact_path = (
            tmp_path
            / "projects"
            / "test_projects"
            / "proj_qa_phase"
            / "phases"
            / "qa.json"
        )
        assert artifact_path.exists()
        artifact = json.loads(artifact_path.read_text())
        assert artifact["project_id"] == "proj_qa_phase"
        assert "results" in artifact
        assert isinstance(artifact["results"], list)
        assert isinstance(artifact["has_critical"], bool)
        # generated_at is an ISO-formatted string
        assert isinstance(artifact["generated_at"], str)
        datetime.fromisoformat(artifact["generated_at"])

        # qa_report attached to walkthrough_output
        assert project.walkthrough_output is not None
        assert "qa_report" in project.walkthrough_output
        report_payload = project.walkthrough_output["qa_report"]
        assert report_payload["project_id"] == "proj_qa_phase"
        # The dict is the model_dump(mode="json") of the QAReport
        assert report_payload["has_critical"] == artifact["has_critical"]


class TestWalkthroughOutputNone:
    async def test_initializes_walkthrough_output_when_none(self) -> None:
        orch = PhaseOrchestrator()
        project = _project("proj_none_output", walkthrough_output=None)

        async for _ in orch._run_qa(project):
            pass

        assert project.walkthrough_output is not None
        assert "qa_report" in project.walkthrough_output


class TestQABlockOnCritical:
    async def test_status_flips_to_qa_blocked_when_critical_and_flag_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The default registry runs output_schema, which on a project with
        # no generation artifact emits a `generation_artifact_missing`
        # critical finding -> has_critical True.
        monkeypatch.setenv("QA_BLOCK_ON_CRITICAL", "true")

        orch = PhaseOrchestrator()
        project = _project("proj_block")
        # Status starts as 'complete' (post-generation)
        assert project.status == "complete"

        async for _ in orch._run_qa(project):
            pass

        assert project.status == "qa_blocked"

    async def test_status_unchanged_when_flag_off_even_with_critical(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Flag remains off (set in autouse via default); critical findings
        # still occur but status must not flip.
        monkeypatch.delenv("QA_BLOCK_ON_CRITICAL", raising=False)

        orch = PhaseOrchestrator()
        project = _project("proj_no_block")
        assert project.status == "complete"

        async for _ in orch._run_qa(project):
            pass

        assert project.status == "complete"
        # qa_report still attached
        assert project.walkthrough_output is not None
        assert "qa_report" in project.walkthrough_output

    async def test_status_unchanged_when_flag_on_but_no_critical(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Patch VALIDATORS so the registry produces no critical findings
        from walkthrough.ai.qa import runner as qa_runner
        from walkthrough.models.qa import ValidatorResult

        async def _ok(project: Project) -> ValidatorResult:
            return ValidatorResult(validator="stub", ok=True, findings=[])

        monkeypatch.setattr(qa_runner, "VALIDATORS", [("stub", _ok)])
        monkeypatch.setenv("QA_BLOCK_ON_CRITICAL", "true")

        orch = PhaseOrchestrator()
        project = _project("proj_clean")

        async for _ in orch._run_qa(project):
            pass

        assert project.status == "complete"


class TestRunGenerationPhaseRunsQA:
    """After clarification, the frontend calls run_generation_phase — not
    run_pipeline. QA must run on this path too, otherwise it never runs
    for any project that pauses for user input (i.e. almost all of them).
    """

    async def test_run_generation_phase_emits_qa_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from walkthrough.ai.orchestrator import PhaseOrchestrator
        from walkthrough.ai.qa import runner as qa_runner
        from walkthrough.models.qa import ValidatorResult

        # Stub the Firestore load/save and generate_walkthrough so we can
        # exercise the run_generation_phase → _run_qa path without real work.
        orch = PhaseOrchestrator()
        project = _project("proj_gen_qa")

        async def _fake_load(_id: str) -> Project:
            return project

        async def _fake_save(_p: Project) -> None:
            return None

        async def _fake_generate(_p: Project) -> dict:
            return {"metadata": {}, "screens": {}, "warnings": [], "stats": {
                "total_screens": 0, "total_branches": 0,
                "total_paths": 0, "open_questions": 0,
            }}

        async def _ok(p: Project) -> ValidatorResult:
            return ValidatorResult(validator="stub", ok=True, findings=[])

        monkeypatch.setattr(orch._firestore, "load_project", _fake_load)
        monkeypatch.setattr(orch._firestore, "save_project", _fake_save)
        monkeypatch.setattr(
            "walkthrough.ai.tools.generate.generate_walkthrough",
            _fake_generate,
        )
        monkeypatch.setattr(qa_runner, "VALIDATORS", [("stub", _ok)])

        phases_seen: list[str] = []
        async for event in orch.run_generation_phase("proj_gen_qa"):
            phases_seen.append(event.phase)

        assert "generation" in phases_seen
        assert "qa" in phases_seen, (
            "QA phase must run on run_generation_phase path, not only run_pipeline"
        )


class TestRunnerDefensiveCoercion:
    """run_qa must coerce malformed validator return values instead of crashing."""

    async def test_non_validator_result_becomes_structured_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from walkthrough.ai.qa import runner as qa_runner
        from walkthrough.ai.qa.runner import run_qa

        async def _bad(p: Project):  # returns a dict, not ValidatorResult
            return {"this": "is wrong"}

        monkeypatch.setattr(qa_runner, "VALIDATORS", [("misbehaving", _bad)])

        project = _project("proj_bad_validator")
        report = await run_qa(project)

        assert len(report.results) == 1
        result = report.results[0]
        assert result.validator == "misbehaving"
        assert result.ok is False
        assert any(f.code == "validator_error" for f in result.findings)
        assert any("dict" in f.message for f in result.findings)


class TestProgressMessage:
    async def test_critical_count_in_final_event_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from walkthrough.ai.qa import runner as qa_runner
        from walkthrough.models.qa import ValidatorFinding, ValidatorResult

        async def _two_critical(project: Project) -> ValidatorResult:
            return ValidatorResult(
                validator="stub",
                ok=False,
                findings=[
                    ValidatorFinding(
                        severity="critical", code="x", message="a"
                    ),
                    ValidatorFinding(
                        severity="critical", code="y", message="b"
                    ),
                ],
            )

        monkeypatch.setattr(
            qa_runner, "VALIDATORS", [("stub", _two_critical)]
        )

        orch = PhaseOrchestrator()
        project = _project("proj_count")

        events: list[ProgressEvent] = []
        async for event in orch._run_qa(project):
            events.append(event)

        assert events[-1].message == "QA complete — 2 critical findings"
