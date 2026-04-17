"""Tests for walkthrough/ai/tools/generate.py."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from walkthrough.ai.tools.generate import (
    _build_decision_tree_output,
    _build_open_questions,
    _build_screen_wireframe,
    _build_warnings,
    _count_paths,
    _find_affected_screens,
    generate_walkthrough,
)
from walkthrough.models.project import Gap, Project
from walkthrough.models.video import UIElement
from walkthrough.models.workflow import (
    BranchPoint,
    DecisionTree,
    Narrative,
    SourceRef,
    WorkflowScreen,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _element(label: str, state: str | None = None) -> UIElement:
    return UIElement(element_type="button", label=label, state=state)


def _ref(reference: str, excerpt: str | None = None) -> SourceRef:
    return SourceRef(source_type="video", reference=reference, excerpt=excerpt)


def _screen(
    screen_id: str = "s1",
    title: str = "Login",
    elements: list[UIElement] | None = None,
    narrative: Narrative | None = None,
    evidence_tier: Literal["observed", "mentioned"] = "observed",
    source_refs: list[SourceRef] | None = None,
) -> WorkflowScreen:
    return WorkflowScreen(
        screen_id=screen_id,
        title=title,
        ui_elements=[_element("Submit")] if elements is None else elements,
        narrative=narrative,
        evidence_tier=evidence_tier,
        source_refs=source_refs or [_ref("vid.mp4:00:10")],
    )


def _gap(
    gap_id: str = "g1",
    severity: Literal["critical", "medium", "low"] = "critical",
    description: str = "Missing field",
    evidence: list[SourceRef] | None = None,
    resolved: bool = False,
) -> Gap:
    return Gap(
        gap_id=gap_id,
        severity=severity,
        description=description,
        evidence=evidence or [_ref("vid.mp4:00:10")],
        resolved=resolved,
    )


def _project(
    decision_trees: list[DecisionTree] | None = None,
    gaps: list[Gap] | None = None,
) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id="proj1",
        name="Test Project",
        status="generating",
        videos=[],
        pdfs=[],
        decision_trees=decision_trees or [],
        gaps=gaps or [],
        questions=[],
        created_at=now,
        updated_at=now,
    )


def _tree(
    root: str = "s1",
    screens: dict[str, WorkflowScreen] | None = None,
    branches: list[BranchPoint] | None = None,
) -> DecisionTree:
    if screens is None:
        screens = {"s1": _screen("s1")}
    return DecisionTree(
        root_screen_id=root,
        screens=screens,
        branches=branches or [],
    )


# ---------------------------------------------------------------------------
# _build_screen_wireframe
# ---------------------------------------------------------------------------


class TestBuildScreenWireframe:
    def test_uses_ui_elements_key(self):
        result = _build_screen_wireframe(_screen())
        assert "ui_elements" in result
        assert "elements" not in result

    def test_element_fields(self):
        screen = _screen(elements=[_element("OK", state="enabled")])
        result = _build_screen_wireframe(screen)
        assert result["ui_elements"][0] == {
            "element_type": "button",
            "label": "OK",
            "state": "enabled",
        }

    def test_element_state_none_omitted(self):
        screen = _screen(elements=[_element("OK", state=None)])
        result = _build_screen_wireframe(screen)
        assert "state" not in result["ui_elements"][0]

    def test_no_narrative_omitted(self):
        result = _build_screen_wireframe(_screen(narrative=None))
        assert "narrative" not in result

    def test_narrative_included(self):
        narrative = Narrative(what="Shows login form", why="User must authenticate")
        result = _build_screen_wireframe(_screen(narrative=narrative))
        assert result["narrative"]["what"] == "Shows login form"
        assert result["narrative"]["why"] == "User must authenticate"
        assert "when_condition" not in result["narrative"]

    def test_narrative_when_condition(self):
        narrative = Narrative(
            what="Shows form", why="Auth required", when_condition="After timeout"
        )
        result = _build_screen_wireframe(_screen(narrative=narrative))
        assert result["narrative"]["when_condition"] == "After timeout"

    def test_source_refs_with_excerpt(self):
        screen = _screen(source_refs=[_ref("vid.mp4:00:05", excerpt="User clicks")])
        result = _build_screen_wireframe(screen)
        assert result["source_refs"][0]["excerpt"] == "User clicks"

    def test_source_ref_without_excerpt_omitted(self):
        screen = _screen(source_refs=[_ref("vid.mp4:00:05", excerpt=None)])
        result = _build_screen_wireframe(screen)
        assert "excerpt" not in result["source_refs"][0]

    def test_evidence_tier_preserved(self):
        result = _build_screen_wireframe(_screen(evidence_tier="mentioned"))
        assert result["evidence_tier"] == "mentioned"

    def test_empty_ui_elements(self):
        screen = _screen(elements=[])
        result = _build_screen_wireframe(screen)
        assert result["ui_elements"] == []


# ---------------------------------------------------------------------------
# _build_decision_tree_output
# ---------------------------------------------------------------------------


class TestBuildDecisionTreeOutput:
    def test_structure_keys(self):
        result = _build_decision_tree_output(_tree())
        assert set(result.keys()) == {"root_screen_id", "screens", "branches"}

    def test_root_screen_id(self):
        result = _build_decision_tree_output(_tree(root="s2"))
        assert result["root_screen_id"] == "s2"

    def test_screens_use_ui_elements(self):
        result = _build_decision_tree_output(_tree())
        for screen_data in result["screens"].values():
            assert "ui_elements" in screen_data
            assert "elements" not in screen_data

    def test_branches_serialized(self):
        branch = BranchPoint(
            screen_id="s1",
            condition="user choice",
            paths={"yes": "s2", "no": "s3"},
        )
        result = _build_decision_tree_output(_tree(branches=[branch]))
        assert result["branches"][0] == {
            "screen_id": "s1",
            "condition": "user choice",
            "paths": {"yes": "s2", "no": "s3"},
        }

    def test_empty_branches(self):
        result = _build_decision_tree_output(_tree(branches=[]))
        assert result["branches"] == []


# ---------------------------------------------------------------------------
# _find_affected_screens
# ---------------------------------------------------------------------------


class TestFindAffectedScreens:
    def test_match_by_source_ref(self):
        screen = _screen("s1", source_refs=[_ref("vid.mp4:00:10")])
        gap = _gap(evidence=[_ref("vid.mp4:00:10")])
        trees = [_tree(screens={"s1": screen})]
        result = _find_affected_screens(gap, trees)
        assert "s1" in result

    def test_no_match_returns_empty(self):
        screen = _screen("s1", source_refs=[_ref("vid.mp4:00:10")])
        gap = _gap(evidence=[_ref("other.mp4:00:00")])
        trees = [_tree(screens={"s1": screen})]
        result = _find_affected_screens(gap, trees)
        assert result == []

    def test_fallback_label_match(self):
        screen = _screen(
            "s1",
            source_refs=[_ref("vid.mp4:00:10")],
            elements=[_element("Submit Button")],
        )
        gap = Gap(
            gap_id="g1",
            severity="critical",
            description="Issue with submit button flow",
            evidence=[_ref("other.mp4:00:00")],
        )
        trees = [_tree(screens={"s1": screen})]
        result = _find_affected_screens(gap, trees)
        assert "s1" in result

    def test_multiple_screens_matched(self):
        s1 = _screen("s1", source_refs=[_ref("vid.mp4:00:10")])
        s2 = _screen("s2", source_refs=[_ref("vid.mp4:00:10")])
        gap = _gap(evidence=[_ref("vid.mp4:00:10")])
        trees = [_tree(screens={"s1": s1, "s2": s2})]
        result = _find_affected_screens(gap, trees)
        assert "s1" in result
        assert "s2" in result


# ---------------------------------------------------------------------------
# _build_warnings
# ---------------------------------------------------------------------------


class TestBuildWarnings:
    def test_critical_unresolved_produces_warning(self):
        screen = _screen("s1", source_refs=[_ref("vid.mp4:00:10")])
        gap = _gap("g1", severity="critical", evidence=[_ref("vid.mp4:00:10")])
        trees = [_tree(screens={"s1": screen})]
        result = _build_warnings([gap], trees)
        assert len(result) == 1
        assert result[0]["gap_id"] == "g1"
        assert result[0]["screen_id"] == "s1"

    def test_each_affected_screen_gets_own_entry(self):
        s1 = _screen("s1", source_refs=[_ref("vid.mp4:00:10")])
        s2 = _screen("s2", source_refs=[_ref("vid.mp4:00:10")])
        gap = _gap(evidence=[_ref("vid.mp4:00:10")])
        trees = [_tree(screens={"s1": s1, "s2": s2})]
        result = _build_warnings([gap], trees)
        screen_ids = {w["screen_id"] for w in result}
        assert screen_ids == {"s1", "s2"}

    def test_no_affected_screens_yields_empty_screen_id(self):
        gap = _gap("g1", severity="critical", evidence=[_ref("nowhere.mp4")])
        trees = [_tree(screens={"s1": _screen("s1", source_refs=[_ref("vid.mp4")])})]
        result = _build_warnings([gap], trees)
        assert len(result) == 1
        assert result[0]["screen_id"] == ""

    def test_resolved_critical_excluded(self):
        gap = _gap(severity="critical", resolved=True)
        trees = [_tree()]
        result = _build_warnings([gap], trees)
        assert result == []

    def test_medium_gap_excluded(self):
        gap = _gap(severity="medium")
        trees = [_tree()]
        result = _build_warnings([gap], trees)
        assert result == []

    def test_low_gap_excluded(self):
        gap = _gap(severity="low")
        trees = [_tree()]
        result = _build_warnings([gap], trees)
        assert result == []

    def test_warning_has_required_fields(self):
        screen = _screen("s1", source_refs=[_ref("vid.mp4:00:10")])
        gap = _gap(evidence=[_ref("vid.mp4:00:10")])
        trees = [_tree(screens={"s1": screen})]
        w = _build_warnings([gap], trees)[0]
        assert {"gap_id", "screen_id", "description", "evidence"} <= w.keys()


# ---------------------------------------------------------------------------
# _build_open_questions
# ---------------------------------------------------------------------------


class TestBuildOpenQuestions:
    def test_medium_gap_included(self):
        gap = _gap("g1", severity="medium")
        result = _build_open_questions([gap])
        assert len(result) == 1
        assert result[0]["gap_id"] == "g1"

    def test_low_gap_included(self):
        gap = _gap("g1", severity="low")
        result = _build_open_questions([gap])
        assert len(result) == 1

    def test_critical_gap_excluded(self):
        gap = _gap(severity="critical")
        result = _build_open_questions([gap])
        assert result == []

    def test_resolved_gap_excluded(self):
        gap = _gap(severity="medium", resolved=True)
        result = _build_open_questions([gap])
        assert result == []

    def test_question_has_required_fields(self):
        gap = _gap("g1", severity="medium", description="Unclear step")
        result = _build_open_questions([gap])
        q = result[0]
        assert q["gap_id"] == "g1"
        assert q["severity"] == "medium"
        assert q["description"] == "Unclear step"
        assert "evidence" in q


# ---------------------------------------------------------------------------
# _count_paths
# ---------------------------------------------------------------------------


class TestCountPaths:
    def test_no_branches_returns_one(self):
        assert _count_paths([]) == 1

    def test_single_branch_two_paths(self):
        bp = BranchPoint(screen_id="s1", condition="c", paths={"a": "s2", "b": "s3"})
        assert _count_paths([bp]) == 2

    def test_multiple_branches_summed(self):
        b1 = BranchPoint(screen_id="s1", condition="c1", paths={"a": "s2", "b": "s3"})
        b2 = BranchPoint(screen_id="s2", condition="c2", paths={"x": "s4"})
        assert _count_paths([b1, b2]) == 3


# ---------------------------------------------------------------------------
# generate_walkthrough (integration)
# ---------------------------------------------------------------------------


class TestGenerateWalkthrough:
    def _simple_project(self) -> Project:
        screen = _screen(
            "s1",
            elements=[_element("OK", state="enabled")],
            source_refs=[_ref("vid.mp4:00:05", excerpt="User sees OK")],
        )
        tree = _tree(root="s1", screens={"s1": screen})
        return _project(decision_trees=[tree])

    async def test_output_top_level_keys(self):
        result = await generate_walkthrough(self._simple_project())
        assert set(result.keys()) == {
            "metadata", "decision_trees", "screens", "warnings", "open_questions", "stats"
        }

    async def test_screens_use_ui_elements_key(self):
        result = await generate_walkthrough(self._simple_project())
        for screen_data in result["screens"].values():
            assert "ui_elements" in screen_data, "screen must use 'ui_elements', not 'elements'"
            assert "elements" not in screen_data

    async def test_decision_tree_screens_use_ui_elements_key(self):
        result = await generate_walkthrough(self._simple_project())
        for tree in result["decision_trees"]:
            for screen_data in tree["screens"].values():
                assert "ui_elements" in screen_data
                assert "elements" not in screen_data

    async def test_stats_field_names(self):
        result = await generate_walkthrough(self._simple_project())
        stats = result["stats"]
        assert "total_branches" in stats, "stats must use 'total_branches'"
        assert "total_branch_points" not in stats
        assert "open_questions" in stats, "stats must use 'open_questions'"
        assert "open_questions_count" not in stats
        assert "total_screens" in stats
        assert "total_paths" in stats

    async def test_stats_values(self):
        branch = BranchPoint(
            screen_id="s1", condition="c", paths={"a": "s2", "b": "s3"}
        )
        screens = {
            "s1": _screen("s1"),
            "s2": _screen("s2"),
            "s3": _screen("s3"),
        }
        tree = _tree(root="s1", screens=screens, branches=[branch])
        medium_gap = _gap("g1", severity="medium")
        project = _project(decision_trees=[tree], gaps=[medium_gap])
        result = await generate_walkthrough(project)
        stats = result["stats"]
        assert stats["total_screens"] == 3
        assert stats["total_branches"] == 1
        assert stats["total_paths"] == 2
        assert stats["open_questions"] == 1

    async def test_no_gaps_produces_empty_warnings_and_questions(self):
        result = await generate_walkthrough(self._simple_project())
        assert result["warnings"] == []
        assert result["open_questions"] == []

    async def test_critical_unresolved_gap_goes_to_warnings(self):
        screen = _screen("s1", source_refs=[_ref("vid.mp4:00:05")])
        tree = _tree(screens={"s1": screen})
        gap = _gap("g1", severity="critical", evidence=[_ref("vid.mp4:00:05")])
        project = _project(decision_trees=[tree], gaps=[gap])
        result = await generate_walkthrough(project)
        assert len(result["warnings"]) == 1
        assert result["open_questions"] == []

    async def test_medium_gap_goes_to_open_questions(self):
        tree = _tree()
        gap = _gap("g1", severity="medium")
        project = _project(decision_trees=[tree], gaps=[gap])
        result = await generate_walkthrough(project)
        assert result["warnings"] == []
        assert len(result["open_questions"]) == 1

    async def test_metadata_contains_project_info(self):
        result = await generate_walkthrough(self._simple_project())
        meta = result["metadata"]
        assert meta["project_id"] == "proj1"
        assert meta["name"] == "Test Project"
        assert "generated_at" in meta

    async def test_screens_flat_index_populated(self):
        result = await generate_walkthrough(self._simple_project())
        assert "s1" in result["screens"]

    async def test_warning_screen_id_field_present(self):
        screen = _screen("s1", source_refs=[_ref("vid.mp4:00:05")])
        tree = _tree(screens={"s1": screen})
        gap = _gap(severity="critical", evidence=[_ref("vid.mp4:00:05")])
        project = _project(decision_trees=[tree], gaps=[gap])
        result = await generate_walkthrough(project)
        for w in result["warnings"]:
            assert "screen_id" in w
            assert "affected_screens" not in w
