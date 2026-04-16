"""Tests for walkthrough/ai/qa/decision_tree_structure.py (US-005)."""

from __future__ import annotations

from datetime import datetime, timezone

from walkthrough.ai.qa.decision_tree_structure import validate
from walkthrough.models.project import Project
from walkthrough.models.workflow import (
    BranchPoint,
    DecisionTree,
    SourceRef,
    WorkflowScreen,
)


def _screen(screen_id: str) -> WorkflowScreen:
    return WorkflowScreen(
        screen_id=screen_id,
        title=f"Screen {screen_id}",
        ui_elements=[],
        evidence_tier="observed",
        source_refs=[SourceRef(source_type="video", reference="v.mp4:0:10")],
    )


def _project(trees: list[DecisionTree]) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id="proj_qa_tree",
        name="QA Tree Test",
        status="analyzing",
        videos=[],
        pdfs=[],
        decision_trees=trees,
        gaps=[],
        questions=[],
        created_at=now,
        updated_at=now,
    )


class TestSelfLoop:
    async def test_detects_self_loop(self):
        tree = DecisionTree(
            root_screen_id="s1",
            screens={"s1": _screen("s1")},
            branches=[
                BranchPoint(
                    screen_id="s1",
                    condition="user decides",
                    paths={"retry": "s1"},
                )
            ],
        )
        result = await validate(_project([tree]))

        assert result.validator == "decision_tree_structure"
        assert result.ok is False
        self_loops = [f for f in result.findings if f.code == "self_loop"]
        assert len(self_loops) == 1
        assert self_loops[0].severity == "critical"
        assert self_loops[0].screen_id == "s1"
        assert "retry" in self_loops[0].message

    async def test_reproduces_known_self_loop_at_screen_d3af07fa2d51(self):
        """The bug the user just hit: one branch path loops back to its own screen."""
        bad_id = "screen_d3af07fa2d51"
        other_id = "screen_other"
        tree = DecisionTree(
            root_screen_id=bad_id,
            screens={bad_id: _screen(bad_id), other_id: _screen(other_id)},
            branches=[
                BranchPoint(
                    screen_id=bad_id,
                    condition="user decides path",
                    paths={"continue": other_id, "stay": bad_id},
                )
            ],
        )
        result = await validate(_project([tree]))

        assert result.ok is False
        self_loops = [f for f in result.findings if f.code == "self_loop"]
        assert len(self_loops) == 1
        assert self_loops[0].screen_id == bad_id
        assert self_loops[0].severity == "critical"


class TestDanglingBranchTarget:
    async def test_dangling_target_is_critical(self):
        tree = DecisionTree(
            root_screen_id="s1",
            screens={"s1": _screen("s1")},
            branches=[
                BranchPoint(
                    screen_id="s1",
                    condition="c",
                    paths={"next": "missing_screen"},
                )
            ],
        )
        result = await validate(_project([tree]))

        dangling = [f for f in result.findings if f.code == "dangling_branch_target"]
        assert len(dangling) == 1
        assert dangling[0].severity == "critical"
        assert dangling[0].screen_id == "s1"
        assert "missing_screen" in dangling[0].message
        assert result.ok is False


class TestOrphanScreen:
    async def test_orphan_screen_is_medium(self):
        tree = DecisionTree(
            root_screen_id="s1",
            screens={
                "s1": _screen("s1"),
                "s2": _screen("s2"),
                "s_orphan": _screen("s_orphan"),
            },
            branches=[
                BranchPoint(
                    screen_id="s1",
                    condition="c",
                    paths={"next": "s2"},
                )
            ],
        )
        result = await validate(_project([tree]))

        orphans = [f for f in result.findings if f.code == "orphan_screen"]
        orphan_ids = {f.screen_id for f in orphans}
        assert "s_orphan" in orphan_ids
        assert "s1" not in orphan_ids  # root exempt
        assert "s2" not in orphan_ids  # it's a branch target
        for finding in orphans:
            assert finding.severity == "medium"

    async def test_no_critical_findings_ok_true(self):
        tree = DecisionTree(
            root_screen_id="s1",
            screens={
                "s1": _screen("s1"),
                "s2": _screen("s2"),
                "s_orphan": _screen("s_orphan"),
            },
            branches=[
                BranchPoint(
                    screen_id="s1",
                    condition="c",
                    paths={"next": "s2"},
                )
            ],
        )
        result = await validate(_project([tree]))

        # Only medium-severity findings — ok stays True
        assert result.ok is True
        assert all(f.severity != "critical" for f in result.findings)


class TestUnreachableScreen:
    async def test_unreachable_screen_is_medium(self):
        # s3 is a branch target (so not orphan) but the source branch s2
        # is itself never reached from root -> s3 is unreachable via BFS.
        tree = DecisionTree(
            root_screen_id="s1",
            screens={
                "s1": _screen("s1"),
                "s2": _screen("s2"),
                "s3": _screen("s3"),
            },
            branches=[
                BranchPoint(
                    screen_id="s2",
                    condition="c",
                    paths={"next": "s3"},
                )
            ],
        )
        result = await validate(_project([tree]))

        unreachable = [f for f in result.findings if f.code == "unreachable_screen"]
        unreachable_ids = {f.screen_id for f in unreachable}
        assert "s2" in unreachable_ids
        assert "s3" in unreachable_ids
        assert "s1" not in unreachable_ids
        for finding in unreachable:
            assert finding.severity == "medium"


class TestClean:
    async def test_clean_tree_produces_no_findings(self):
        tree = DecisionTree(
            root_screen_id="s1",
            screens={"s1": _screen("s1"), "s2": _screen("s2")},
            branches=[
                BranchPoint(
                    screen_id="s1",
                    condition="c",
                    paths={"next": "s2"},
                )
            ],
        )
        result = await validate(_project([tree]))

        assert result.ok is True
        assert result.findings == []
        assert result.validator == "decision_tree_structure"


class TestMultipleTrees:
    async def test_aggregates_findings_across_trees(self):
        tree_clean = DecisionTree(
            root_screen_id="a1",
            screens={"a1": _screen("a1"), "a2": _screen("a2")},
            branches=[
                BranchPoint(screen_id="a1", condition="c", paths={"n": "a2"})
            ],
        )
        tree_loop = DecisionTree(
            root_screen_id="b1",
            screens={"b1": _screen("b1")},
            branches=[
                BranchPoint(screen_id="b1", condition="c", paths={"x": "b1"})
            ],
        )
        result = await validate(_project([tree_clean, tree_loop]))

        assert result.ok is False
        codes = [f.code for f in result.findings]
        assert codes.count("self_loop") == 1
