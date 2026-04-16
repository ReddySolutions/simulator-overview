"""Tests for walkthrough/ai/qa/runner.py (US-009)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from walkthrough.ai.qa import runner as qa_runner
from walkthrough.ai.qa.runner import VALIDATORS, run_qa
from walkthrough.models.project import Project
from walkthrough.models.qa import ValidatorFinding, ValidatorResult


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_COLLECTION", "test_projects")
    # Keep LLM critic off so the runner's fan-out stays hermetic by default
    monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "false")


def _project(project_id: str = "proj_runner") -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id=project_id,
        name="QA Runner Test",
        status="complete",
        videos=[],
        pdfs=[],
        decision_trees=[],
        gaps=[],
        questions=[],
        created_at=now,
        updated_at=now,
    )


def _stub_validator(
    name: str,
    *,
    ok: bool = True,
    findings: list[ValidatorFinding] | None = None,
):
    async def _fn(project: Project) -> ValidatorResult:  # pragma: no cover - trivial
        return ValidatorResult(
            validator=name,
            ok=ok,
            findings=findings or [],
        )

    return _fn


def _raising_validator(message: str):
    async def _fn(project: Project) -> ValidatorResult:  # pragma: no cover - raises
        raise RuntimeError(message)

    return _fn


def _patch_validators(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[tuple[str, object]],
) -> None:
    monkeypatch.setattr(qa_runner, "VALIDATORS", entries)


class TestAllValidatorsOk:
    async def test_has_critical_false_when_all_clean(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_validators(
            monkeypatch,
            [
                ("decision_tree_structure", _stub_validator("decision_tree_structure")),
                ("output_schema", _stub_validator("output_schema")),
                ("video_coverage", _stub_validator("video_coverage")),
                ("narrative_fidelity", _stub_validator("narrative_fidelity")),
            ],
        )

        project = _project()
        report = await run_qa(project)

        assert report.project_id == "proj_runner"
        assert report.has_critical is False
        assert [r.validator for r in report.results] == [
            "decision_tree_structure",
            "output_schema",
            "video_coverage",
            "narrative_fidelity",
        ]
        assert all(r.ok for r in report.results)
        assert all(r.findings == [] for r in report.results)

    async def test_non_critical_findings_do_not_flip_has_critical(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        medium_finding = ValidatorFinding(
            severity="medium",
            code="orphan_screen",
            message="medium issue",
        )
        _patch_validators(
            monkeypatch,
            [
                (
                    "decision_tree_structure",
                    _stub_validator(
                        "decision_tree_structure",
                        ok=True,
                        findings=[medium_finding],
                    ),
                ),
                ("output_schema", _stub_validator("output_schema")),
                ("video_coverage", _stub_validator("video_coverage")),
                ("narrative_fidelity", _stub_validator("narrative_fidelity")),
            ],
        )

        report = await run_qa(_project())

        assert report.has_critical is False
        assert report.results[0].findings == [medium_finding]


class TestValidatorRaises:
    async def test_exception_becomes_structured_error_finding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_validators(
            monkeypatch,
            [
                (
                    "decision_tree_structure",
                    _raising_validator("boom"),
                ),
                ("output_schema", _stub_validator("output_schema")),
                ("video_coverage", _stub_validator("video_coverage")),
                ("narrative_fidelity", _stub_validator("narrative_fidelity")),
            ],
        )

        report = await run_qa(_project())

        assert report.has_critical is True
        errored = report.results[0]
        assert errored.validator == "decision_tree_structure"
        assert errored.ok is False
        assert len(errored.findings) == 1
        finding = errored.findings[0]
        assert finding.severity == "critical"
        assert finding.code == "validator_error"
        assert finding.message == "boom"
        # Other validators still return their normal results
        assert all(r.ok for r in report.results[1:])

    async def test_multiple_raises_each_coerced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_validators(
            monkeypatch,
            [
                ("decision_tree_structure", _raising_validator("a")),
                ("output_schema", _raising_validator("b")),
                ("video_coverage", _stub_validator("video_coverage")),
                ("narrative_fidelity", _stub_validator("narrative_fidelity")),
            ],
        )

        report = await run_qa(_project())

        assert report.has_critical is True
        assert report.results[0].findings[0].message == "a"
        assert report.results[1].findings[0].message == "b"
        for r in report.results[:2]:
            assert r.ok is False
            assert r.findings[0].code == "validator_error"


class TestArtifactWritten:
    async def test_writes_qa_json_artifact(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_validators(
            monkeypatch,
            [
                ("decision_tree_structure", _stub_validator("decision_tree_structure")),
                ("output_schema", _stub_validator("output_schema")),
                ("video_coverage", _stub_validator("video_coverage")),
                ("narrative_fidelity", _stub_validator("narrative_fidelity")),
            ],
        )

        report = await run_qa(_project("proj_artifact"))

        artifact_path = (
            tmp_path
            / "projects"
            / "test_projects"
            / "proj_artifact"
            / "phases"
            / "qa.json"
        )
        assert artifact_path.exists()

        serialized = json.loads(artifact_path.read_text())
        assert serialized["project_id"] == "proj_artifact"
        assert serialized["has_critical"] is False
        assert [r["validator"] for r in serialized["results"]] == [
            "decision_tree_structure",
            "output_schema",
            "video_coverage",
            "narrative_fidelity",
        ]
        # generated_at must be ISO-formatted by model_dump(mode="json")
        assert isinstance(serialized["generated_at"], str)
        # Round-trip datetime parse sanity check
        datetime.fromisoformat(serialized["generated_at"])

        # Returned report matches what was serialized
        assert report.project_id == serialized["project_id"]
        assert report.has_critical is serialized["has_critical"]


class TestRealValidatorsSmoke:
    """Sanity check that the default VALIDATORS registry runs end-to-end
    on an empty project without any patches (flag off -> no LLM traffic)."""

    async def test_empty_project_default_registry(self) -> None:
        assert [name for name, _ in VALIDATORS] == [
            "decision_tree_structure",
            "output_schema",
            "video_coverage",
            "narrative_fidelity",
        ]

        report = await run_qa(_project("proj_smoke"))

        # output_schema will fail (no generation artifact) -> has_critical True
        assert report.has_critical is True
        output_schema_result = next(
            r for r in report.results if r.validator == "output_schema"
        )
        assert output_schema_result.ok is False
        assert any(
            f.code == "generation_artifact_missing"
            for f in output_schema_result.findings
        )

        # narrative_fidelity short-circuits with flag off
        nf = next(
            r for r in report.results if r.validator == "narrative_fidelity"
        )
        assert nf.ok is True
        assert nf.findings == []
