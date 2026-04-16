"""Tests for walkthrough/ai/qa/video_coverage.py (US-007)."""

from __future__ import annotations

from datetime import datetime, timezone

from walkthrough.ai.qa.video_coverage import validate
from walkthrough.models.project import Project
from walkthrough.models.workflow import (
    BranchPoint,
    DecisionTree,
    SourceRef,
    WorkflowScreen,
)


def _video_ref() -> SourceRef:
    return SourceRef(source_type="video", reference="train.mp4:00:10")


def _pdf_ref() -> SourceRef:
    return SourceRef(source_type="pdf", reference="SOP.pdf:Section 3.2")


def _audio_ref() -> SourceRef:
    return SourceRef(source_type="audio", reference="train.mp4:00:10:audio")


def _screen(
    screen_id: str,
    *,
    evidence_tier: str = "observed",
    source_refs: list[SourceRef] | None = None,
) -> WorkflowScreen:
    if source_refs is None:
        source_refs = [_video_ref()]
    return WorkflowScreen(
        screen_id=screen_id,
        title=f"Screen {screen_id}",
        ui_elements=[],
        evidence_tier=evidence_tier,  # type: ignore[arg-type]
        source_refs=source_refs,
    )


def _project(trees: list[DecisionTree]) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id="proj_qa_video",
        name="QA Video Coverage Test",
        status="analyzing",
        videos=[],
        pdfs=[],
        decision_trees=trees,
        gaps=[],
        questions=[],
        created_at=now,
        updated_at=now,
    )


def _tree(*screens: WorkflowScreen, root: str | None = None) -> DecisionTree:
    screen_map = {s.screen_id: s for s in screens}
    root_id = root if root is not None else screens[0].screen_id
    return DecisionTree(
        root_screen_id=root_id,
        screens=screen_map,
        branches=[],
    )


class TestObservedWithoutVideoRef:
    async def test_observed_screen_with_only_pdf_ref_is_critical(self):
        tree = _tree(
            _screen(
                "s1",
                evidence_tier="observed",
                source_refs=[_pdf_ref()],
            )
        )
        result = await validate(_project([tree]))

        assert result.validator == "video_coverage"
        assert result.ok is False
        flagged = [f for f in result.findings if f.code == "observed_without_video_ref"]
        assert len(flagged) == 1
        assert flagged[0].severity == "critical"
        assert flagged[0].screen_id == "s1"

    async def test_observed_screen_with_only_audio_ref_is_critical(self):
        tree = _tree(
            _screen(
                "s_audio",
                evidence_tier="observed",
                source_refs=[_audio_ref()],
            )
        )
        result = await validate(_project([tree]))

        flagged = [f for f in result.findings if f.code == "observed_without_video_ref"]
        assert len(flagged) == 1
        assert flagged[0].screen_id == "s_audio"
        assert result.ok is False

    async def test_observed_screen_with_video_plus_pdf_refs_is_clean(self):
        tree = _tree(
            _screen(
                "s_ok",
                evidence_tier="observed",
                source_refs=[_pdf_ref(), _video_ref()],
            )
        )
        result = await validate(_project([tree]))

        assert result.ok is True
        assert result.findings == []

    async def test_mentioned_screen_without_video_ref_is_not_flagged(self):
        # 'mentioned' evidence_tier is not subject to the video-ref rule
        tree = _tree(
            _screen(
                "s_mentioned",
                evidence_tier="mentioned",
                source_refs=[_pdf_ref()],
            )
        )
        result = await validate(_project([tree]))

        assert result.ok is True
        assert result.findings == []


class TestScreenWithoutAnyRef:
    async def test_empty_source_refs_is_critical(self):
        tree = _tree(
            _screen("s_empty", evidence_tier="observed", source_refs=[])
        )
        result = await validate(_project([tree]))

        flagged = [f for f in result.findings if f.code == "screen_without_any_ref"]
        assert len(flagged) == 1
        assert flagged[0].severity == "critical"
        assert flagged[0].screen_id == "s_empty"
        assert result.ok is False

    async def test_empty_source_refs_does_not_double_flag(self):
        # A screen with zero refs cannot also be flagged for missing-video-ref;
        # the validator should short-circuit so each screen yields one finding.
        tree = _tree(
            _screen("s_empty", evidence_tier="observed", source_refs=[])
        )
        result = await validate(_project([tree]))

        assert len(result.findings) == 1
        assert result.findings[0].code == "screen_without_any_ref"

    async def test_mentioned_screen_with_empty_refs_is_critical(self):
        tree = _tree(
            _screen("s_empty_mentioned", evidence_tier="mentioned", source_refs=[])
        )
        result = await validate(_project([tree]))

        flagged = [f for f in result.findings if f.code == "screen_without_any_ref"]
        assert len(flagged) == 1
        assert flagged[0].screen_id == "s_empty_mentioned"
        assert result.ok is False


class TestClean:
    async def test_clean_project_yields_no_findings(self):
        tree = DecisionTree(
            root_screen_id="s1",
            screens={
                "s1": _screen("s1", source_refs=[_video_ref()]),
                "s2": _screen("s2", evidence_tier="mentioned", source_refs=[_pdf_ref()]),
            },
            branches=[
                BranchPoint(screen_id="s1", condition="c", paths={"next": "s2"})
            ],
        )
        result = await validate(_project([tree]))

        assert result.validator == "video_coverage"
        assert result.ok is True
        assert result.findings == []

    async def test_empty_project_yields_no_findings(self):
        result = await validate(_project([]))

        assert result.ok is True
        assert result.findings == []


class TestMultipleTrees:
    async def test_aggregates_across_trees(self):
        good_tree = _tree(_screen("g1", source_refs=[_video_ref()]))
        bad_tree_no_video = _tree(
            _screen("b1", evidence_tier="observed", source_refs=[_pdf_ref()])
        )
        bad_tree_no_refs = _tree(
            _screen("b2", evidence_tier="observed", source_refs=[])
        )
        result = await validate(
            _project([good_tree, bad_tree_no_video, bad_tree_no_refs])
        )

        codes = [f.code for f in result.findings]
        assert codes.count("observed_without_video_ref") == 1
        assert codes.count("screen_without_any_ref") == 1
        assert result.ok is False

        screens_flagged = {f.screen_id for f in result.findings}
        assert "b1" in screens_flagged
        assert "b2" in screens_flagged
        assert "g1" not in screens_flagged
