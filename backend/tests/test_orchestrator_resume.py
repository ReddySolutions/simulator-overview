"""Tests for _infer_resume_phase artifact-presence resume logic (US-003)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from walkthrough.ai.orchestrator import _infer_resume_phase
from walkthrough.models.project import Gap, Project
from walkthrough.models.video import VideoAnalysis
from walkthrough.models.workflow import SourceRef
from walkthrough.storage.phase_artifacts import write_phase_artifact


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIRESTORE_COLLECTION", "test_projects")


def _video(video_id: str = "v1") -> VideoAnalysis:
    return VideoAnalysis(
        video_id=video_id,
        filename=f"{video_id}.mp4",
        keyframes=[],
        transitions=[],
        audio_segments=[],
        temporal_flow=[],
    )


def _project(
    *,
    project_id: str = "proj_resume",
    status: str = "analyzing",
    videos: list[VideoAnalysis] | None = None,
    gaps: list[Gap] | None = None,
    questions: list | None = None,
) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id=project_id,
        name="Resume Test Project",
        status=status,  # type: ignore[arg-type]
        videos=videos if videos is not None else [_video()],
        pdfs=[],
        decision_trees=[],
        gaps=gaps or [],
        questions=questions or [],
        created_at=now,
        updated_at=now,
    )


class TestAnalyzingResume:
    async def test_artifacts_through_narrative_returns_contradictions(self):
        project = _project(project_id="p_narr", status="analyzing")
        await write_phase_artifact("p_narr", "path_merge", {})
        await write_phase_artifact("p_narr", "narrative", {})

        assert _infer_resume_phase(project) == "contradictions"

    async def test_no_artifacts_empty_project_returns_ingestion(self):
        project = _project(
            project_id="p_empty", status="analyzing", videos=[],
        )
        assert _infer_resume_phase(project) == "ingestion"

    async def test_no_artifacts_with_videos_returns_ingestion(self):
        # Fallback: zero artifacts means resume at ingestion even if videos
        # exist, since downstream phases haven't started.
        project = _project(project_id="p_none", status="analyzing")
        assert _infer_resume_phase(project) == "ingestion"


class TestClarifyingResume:
    async def test_unresolved_critical_returns_clarification(self):
        ref = SourceRef(source_type="video", reference="v.mp4:0:10")
        unresolved = Gap(
            gap_id="g1",
            severity="critical",
            description="critical unresolved",
            evidence=[ref],
            resolved=False,
        )
        project = _project(
            project_id="p_clar",
            status="clarifying",
            gaps=[unresolved],
        )
        # Artifacts through contradictions exist, but clarification logic
        # hinges on status + gaps, not artifacts.
        await write_phase_artifact("p_clar", "path_merge", {})
        await write_phase_artifact("p_clar", "narrative", {})
        await write_phase_artifact("p_clar", "contradictions", {})

        assert _infer_resume_phase(project) == "clarification"


class TestCompleteResume:
    def test_complete_status_returns_done(self):
        project = _project(status="complete")
        assert _infer_resume_phase(project) == "done"
