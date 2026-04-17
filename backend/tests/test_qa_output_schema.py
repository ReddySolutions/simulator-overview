"""Tests for walkthrough/ai/qa/output_schema.py (US-006)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from walkthrough.ai.qa.output_schema import validate
from walkthrough.models.project import Project
from walkthrough.storage.phase_artifacts import write_phase_artifact


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_COLLECTION", "test_projects")


def _project(project_id: str = "proj_output_schema") -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id=project_id,
        name="QA Output Schema Test",
        status="complete",
        videos=[],
        pdfs=[],
        decision_trees=[],
        gaps=[],
        questions=[],
        created_at=now,
        updated_at=now,
    )


def _valid_screen(screen_id: str) -> dict[str, Any]:
    return {
        "screen_id": screen_id,
        "title": f"Screen {screen_id}",
        "ui_elements": [
            {"element_type": "button", "label": "Submit"},
        ],
        "evidence_tier": "observed",
        "source_refs": [{"source_type": "video", "reference": "v.mp4:0:10"}],
    }


def _valid_artifact() -> dict[str, Any]:
    s1 = _valid_screen("s1")
    return {
        "metadata": {"project_id": "proj_output_schema"},
        "decision_trees": [],
        "screens": {"s1": s1},
        "warnings": [],
        "open_questions": [],
        "stats": {
            "total_screens": 1,
            "total_branches": 0,
            "total_paths": 1,
            "open_questions": 0,
        },
    }


class TestArtifactMissing:
    async def test_returns_critical_when_artifact_absent(self):
        result = await validate(_project("missing_project"))

        assert result.validator == "output_schema"
        assert result.ok is False
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.code == "generation_artifact_missing"
        assert finding.severity == "critical"


class TestCleanArtifact:
    async def test_valid_artifact_produces_no_findings(self):
        project = _project()
        await write_phase_artifact(
            project.project_id, "generation", _valid_artifact()
        )

        result = await validate(project)
        assert result.ok is True
        assert result.findings == []
        assert result.validator == "output_schema"


class TestMissingScreenField:
    async def test_missing_title_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        del artifact["screens"]["s1"]["title"]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        codes = [f.code for f in result.findings]
        assert "missing_screen_field" in codes
        missing = [f for f in result.findings if f.code == "missing_screen_field"]
        assert all(f.severity == "critical" for f in missing)
        assert any("title" in f.message for f in missing)
        assert result.ok is False

    async def test_missing_source_refs_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        del artifact["screens"]["s1"]["source_refs"]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        missing = [f for f in result.findings if f.code == "missing_screen_field"]
        assert any("source_refs" in f.message for f in missing)
        assert result.ok is False


class TestLegacyElementsKey:
    async def test_legacy_elements_key_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        # Simulate regression: screen emits 'elements' instead of 'ui_elements'
        screen = artifact["screens"]["s1"]
        screen["elements"] = screen.pop("ui_elements")
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        legacy = [f for f in result.findings if f.code == "legacy_elements_key"]
        assert len(legacy) == 1
        assert legacy[0].severity == "critical"
        assert legacy[0].screen_id == "s1"
        assert result.ok is False


class TestBadUIElement:
    async def test_ui_element_missing_label_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["screens"]["s1"]["ui_elements"] = [
            {"element_type": "button"},  # missing label
        ]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        bad = [f for f in result.findings if f.code == "bad_ui_element"]
        assert len(bad) == 1
        assert bad[0].severity == "critical"
        assert bad[0].screen_id == "s1"
        assert "label" in bad[0].message
        assert result.ok is False

    async def test_ui_element_missing_element_type_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["screens"]["s1"]["ui_elements"] = [
            {"label": "Submit"},  # missing element_type
        ]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        bad = [f for f in result.findings if f.code == "bad_ui_element"]
        assert len(bad) == 1
        assert "element_type" in bad[0].message
        assert result.ok is False


class TestWarningReferencesMissingScreen:
    async def test_warning_screen_id_not_in_screens_is_medium(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["warnings"] = [
            {
                "gap_id": "g1",
                "description": "Conflict",
                "evidence": [],
                "screen_id": "ghost_screen",
            }
        ]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        missing_refs = [
            f
            for f in result.findings
            if f.code == "warning_references_missing_screen"
        ]
        assert len(missing_refs) == 1
        assert missing_refs[0].severity == "medium"
        assert missing_refs[0].screen_id == "ghost_screen"
        # Only medium findings -> ok stays True
        assert result.ok is True

    async def test_empty_screen_id_is_not_flagged(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["warnings"] = [
            {
                "gap_id": "g1",
                "description": "Unanchored",
                "evidence": [],
                "screen_id": "",
            }
        ]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        assert [
            f
            for f in result.findings
            if f.code == "warning_references_missing_screen"
        ] == []


class TestStatsFieldMismatch:
    async def test_missing_total_branches_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        del artifact["stats"]["total_branches"]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        mismatches = [f for f in result.findings if f.code == "stats_field_mismatch"]
        assert any("total_branches" in f.message for f in mismatches)
        assert all(f.severity == "critical" for f in mismatches)
        assert result.ok is False

    async def test_missing_open_questions_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        del artifact["stats"]["open_questions"]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        mismatches = [f for f in result.findings if f.code == "stats_field_mismatch"]
        assert any("open_questions" in f.message for f in mismatches)
        assert result.ok is False

    async def test_legacy_total_branch_points_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["stats"]["total_branch_points"] = 5  # legacy regression
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        mismatches = [f for f in result.findings if f.code == "stats_field_mismatch"]
        assert any("total_branch_points" in f.message for f in mismatches)
        assert result.ok is False

    async def test_legacy_open_questions_count_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["stats"]["open_questions_count"] = 3  # legacy regression
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        mismatches = [f for f in result.findings if f.code == "stats_field_mismatch"]
        assert any("open_questions_count" in f.message for f in mismatches)
        assert result.ok is False

    async def test_legacy_warnings_count_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        artifact["stats"]["warnings_count"] = 0  # legacy regression
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        mismatches = [f for f in result.findings if f.code == "stats_field_mismatch"]
        assert any("warnings_count" in f.message for f in mismatches)
        assert result.ok is False

    async def test_stats_missing_entirely_is_critical(self):
        project = _project()
        artifact = _valid_artifact()
        del artifact["stats"]
        await write_phase_artifact(project.project_id, "generation", artifact)

        result = await validate(project)
        mismatches = [f for f in result.findings if f.code == "stats_field_mismatch"]
        assert len(mismatches) >= 1
        assert result.ok is False
