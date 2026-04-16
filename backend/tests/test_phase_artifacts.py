"""Tests for walkthrough/storage/phase_artifacts.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from walkthrough.storage import phase_artifacts
from walkthrough.storage.phase_artifacts import (
    PHASE_ORDER,
    completed_phases,
    phase_artifact_exists,
    read_phase_artifact,
    write_phase_artifact,
)


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point Settings().LOCAL_DATA_DIR at tmp_path for every test in this module."""
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_COLLECTION", "test_projects")


class TestWriteReadRoundtrip:
    async def test_roundtrip(self, tmp_path: Path):
        payload = {"decision_trees": [{"root_screen_id": "s1"}]}
        path = await write_phase_artifact("proj1", "path_merge", payload)

        assert path.exists()
        expected = (
            tmp_path
            / "projects"
            / "test_projects"
            / "proj1"
            / "phases"
            / "path_merge.json"
        )
        assert path == expected

        data = await read_phase_artifact("proj1", "path_merge")
        assert data == payload

    async def test_creates_parent_dirs(self, tmp_path: Path):
        await write_phase_artifact("projX", "narrative", {"ok": True})
        assert (tmp_path / "projects" / "test_projects" / "projX" / "phases").is_dir()


class TestReadMissing:
    async def test_returns_none(self):
        assert await read_phase_artifact("no-such-project", "ingestion") is None


class TestExistsMissing:
    def test_false_when_missing(self):
        assert phase_artifact_exists("ghost", "ingestion") is False

    async def test_true_after_write(self):
        await write_phase_artifact("p", "ingestion", {})
        assert phase_artifact_exists("p", "ingestion") is True


class TestCompletedPhasesOrder:
    async def test_returns_in_phase_order(self):
        # Write artifacts out of order; expect PHASE_ORDER sequence back.
        await write_phase_artifact("p", "generation", {})
        await write_phase_artifact("p", "path_merge", {})
        await write_phase_artifact("p", "narrative", {})

        result = completed_phases("p")
        assert result == ["path_merge", "narrative", "generation"]

    def test_empty_when_no_artifacts(self):
        assert completed_phases("empty") == []

    async def test_all_phases(self):
        for phase in PHASE_ORDER:
            await write_phase_artifact("full", phase, {})
        assert completed_phases("full") == list(PHASE_ORDER)


class TestPhaseOrderConstant:
    def test_matches_orchestrator_order(self):
        # Guard against drift from orchestrator's PHASE_ORDER.
        from walkthrough.ai.orchestrator import PHASE_ORDER as ORCHESTRATOR_ORDER

        assert phase_artifacts.PHASE_ORDER == ORCHESTRATOR_ORDER
