"""Tests for the meta-question cascade behavior.

When the user answers a Big Picture meta-question, every clarification
question tied to its affected_gap_ids should be marked answered so the
open-question count in the UI drops. The cascade prefixes answers with
'[Big Picture]' for traceability.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from walkthrough.ai.tools.clarification import _question_id
from walkthrough.main import app
from walkthrough.models.project import (
    ClarificationQuestion,
    Gap,
    MetaQuestion,
    Project,
)
from walkthrough.models.workflow import SourceRef
from walkthrough.storage.local_firestore import LocalFirestoreClient


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))


def _ref() -> SourceRef:
    return SourceRef(source_type="video", reference="v.mp4:00:01", excerpt="x")


async def _seed_project() -> Project:
    gaps = [
        Gap(gap_id=f"g{i}", severity="medium", description=f"g{i}", evidence=[_ref()])
        for i in range(5)
    ]
    questions = [
        ClarificationQuestion(
            question_id=_question_id(g.gap_id),
            text=f"Q for {g.gap_id}",
            severity=g.severity,
            evidence=[_ref()],
        )
        for g in gaps
    ]
    meta = MetaQuestion(
        meta_question_id="mq1",
        text="Prefer video labels?",
        rationale="Many label mismatches share this pattern",
        affected_gap_ids=["g0", "g1", "g2"],
    )
    now = datetime.now(timezone.utc)
    project = Project(
        project_id="proj_cascade",
        name="test",
        status="clarifying",
        videos=[],
        pdfs=[],
        decision_trees=[],
        gaps=gaps,
        questions=questions,
        meta_questions=[meta],
        created_at=now,
        updated_at=now,
    )
    fs = LocalFirestoreClient()
    await fs.save_project(project)
    return project


async def test_cascade_marks_covered_questions_answered():
    project = await _seed_project()

    with TestClient(app) as client:
        resp = client.post(
            f"/api/projects/{project.project_id}/meta-questions/mq1/answer",
            json={"answer": "Always video", "cascade": True},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta_question"]["answer"] == "Always video"
    assert set(body["resolved_question_ids"]) == {
        _question_id(gid) for gid in ("g0", "g1", "g2")
    }

    # Persisted state: affected questions got the '[Big Picture]' prefix
    fs = LocalFirestoreClient()
    reloaded = await fs.load_project(project.project_id)
    assert reloaded is not None
    answers = {q.question_id: q.answer for q in reloaded.questions}
    for gid in ("g0", "g1", "g2"):
        assert answers[_question_id(gid)] == "[Big Picture] Always video"
    # Uncovered questions stay unanswered
    for gid in ("g3", "g4"):
        assert answers[_question_id(gid)] is None

    # Underlying gaps are marked resolved
    by_id = {g.gap_id: g for g in reloaded.gaps}
    for gid in ("g0", "g1", "g2"):
        assert by_id[gid].resolved
        assert by_id[gid].resolution == "[Big Picture] Always video"


async def test_cascade_false_leaves_questions_alone():
    project = await _seed_project()

    with TestClient(app) as client:
        resp = client.post(
            f"/api/projects/{project.project_id}/meta-questions/mq1/answer",
            json={"answer": "Always video", "cascade": False},
        )

    assert resp.status_code == 200
    assert resp.json()["resolved_question_ids"] == []

    fs = LocalFirestoreClient()
    reloaded = await fs.load_project(project.project_id)
    assert reloaded is not None
    assert all(q.answer is None for q in reloaded.questions)
    assert all(not g.resolved for g in reloaded.gaps)
    # Meta still persisted
    assert reloaded.meta_questions[0].answer == "Always video"


async def test_cascade_skips_already_answered_questions():
    project = await _seed_project()
    # Pre-answer g0 with a manual answer — cascade must not overwrite it
    fs = LocalFirestoreClient()
    project.questions[0].answer = "manual answer"
    await fs.save_project(project)

    with TestClient(app) as client:
        resp = client.post(
            f"/api/projects/{project.project_id}/meta-questions/mq1/answer",
            json={"answer": "Always video"},
        )

    assert resp.status_code == 200
    reloaded = await fs.load_project(project.project_id)
    assert reloaded is not None
    # g0 keeps its manual answer; g1/g2 got the cascade
    by_id = {q.question_id: q.answer for q in reloaded.questions}
    assert by_id[_question_id("g0")] == "manual answer"
    assert by_id[_question_id("g1")] == "[Big Picture] Always video"
    assert by_id[_question_id("g2")] == "[Big Picture] Always video"
    assert _question_id("g0") not in resp.json()["resolved_question_ids"]
