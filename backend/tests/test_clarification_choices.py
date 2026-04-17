"""Tests for Clarification choice generation.

Regression tests for the multi-choice clarification UI — preset choices are
emitted for multi-source contradictions and omitted for single-source gaps.
"""

from __future__ import annotations

from typing import Literal

from walkthrough.ai.tools.clarification import generate_questions
from walkthrough.models.project import Gap
from walkthrough.models.workflow import SourceRef


def _ref(
    source_type: Literal["video", "audio", "pdf"],
    excerpt: str,
    reference: str = "x.mp4:00:10",
) -> SourceRef:
    return SourceRef(source_type=source_type, reference=reference, excerpt=excerpt)


class TestChoiceGeneration:
    async def test_contradiction_across_video_and_pdf_produces_two_choices(self):
        gap = Gap(
            gap_id="gap-1",
            severity="critical",
            description="Button label differs between video and PDF",
            evidence=[
                _ref("video", "Save & Continue"),
                _ref("pdf", "Submit", reference="SOP.pdf:Section 3.2"),
            ],
        )

        [q] = await generate_questions([gap])

        labels = [c.label for c in q.choices]
        assert labels == ["Save & Continue", "Submit"]
        # Each choice carries a source-attribution hint
        descs = [c.description for c in q.choices]
        assert descs == ["Matches video source", "Matches pdf source"]

    async def test_three_way_contradiction_produces_three_choices(self):
        gap = Gap(
            gap_id="gap-2",
            severity="critical",
            description="Three-way disagreement",
            evidence=[
                _ref("video", "Dropdown"),
                _ref("audio", "Radio group"),
                _ref("pdf", "Checkbox list", reference="SOP.pdf:Section 1"),
            ],
        )

        [q] = await generate_questions([gap])

        assert {c.label for c in q.choices} == {
            "Dropdown",
            "Radio group",
            "Checkbox list",
        }

    async def test_single_source_gap_produces_no_choices(self):
        # Only video evidence — no canonical side to pick between.
        gap = Gap(
            gap_id="gap-3",
            severity="medium",
            description="Unclear label in video",
            evidence=[_ref("video", "Save")],
        )

        [q] = await generate_questions([gap])

        assert q.choices == []

    async def test_duplicate_excerpts_dedup(self):
        # Video and audio both say "Submit" — collapse to one choice.
        gap = Gap(
            gap_id="gap-4",
            severity="medium",
            description="Audio confirms video label",
            evidence=[
                _ref("video", "Submit"),
                _ref("audio", "Submit"),
            ],
        )

        [q] = await generate_questions([gap])

        assert len(q.choices) == 1
        assert q.choices[0].label == "Submit"

    async def test_missing_excerpt_falls_back_to_reference(self):
        gap = Gap(
            gap_id="gap-5",
            severity="critical",
            description="Evidence lacks excerpt text",
            evidence=[
                SourceRef(source_type="video", reference="cxone.mp4:00:14", excerpt=None),
                SourceRef(
                    source_type="pdf", reference="SOP.pdf:Section 4.1", excerpt=None,
                ),
            ],
        )

        [q] = await generate_questions([gap])

        assert [c.label for c in q.choices] == [
            "cxone.mp4:00:14",
            "SOP.pdf:Section 4.1",
        ]

    async def test_resolved_gaps_are_skipped(self):
        gap = Gap(
            gap_id="gap-6",
            severity="critical",
            description="Already resolved",
            evidence=[_ref("video", "A"), _ref("pdf", "B", "SOP.pdf:s1")],
            resolved=True,
        )
        assert await generate_questions([gap]) == []


class TestSeverityRebalance:
    """The upstream classifier dumps almost everything into 'medium'; the
    post-generation rebalancer uses impact score to re-distribute."""

    async def test_flat_medium_bucket_gets_spread_across_tiers(self):
        from walkthrough.models.workflow import (
            DecisionTree,
            WorkflowScreen,
        )

        # Build 30 medium gaps; one keyframe reference is shared by many
        # screens (high impact), another by almost none (low impact).
        high_refs = [
            SourceRef(source_type="video", reference=f"v.mp4:00:{i:02d}", excerpt="high")
            for i in range(1, 6)  # gaps 1-5 get the high-impact refs
        ]
        low_refs = [
            SourceRef(source_type="video", reference=f"v.mp4:99:{i:02d}", excerpt="low")
            for i in range(1, 6)  # gaps 26-30 get the low-impact refs
        ]
        mid_refs = [
            SourceRef(source_type="video", reference=f"v.mp4:05:{i:02d}", excerpt="mid")
            for i in range(1, 21)
        ]

        gaps: list[Gap] = []
        for i, ref in enumerate(high_refs + mid_refs + low_refs):
            gaps.append(
                Gap(
                    gap_id=f"g{i}",
                    severity="medium",
                    description=f"gap {i}",
                    evidence=[
                        ref,
                        SourceRef(
                            source_type="pdf", reference="SOP.pdf:s1", excerpt="x",
                        ),
                    ],
                )
            )

        # Decision tree with many screens referencing the high-impact refs,
        # a few referencing the mid-impact refs, and none referencing the low-impact ones.
        screens: dict[str, WorkflowScreen] = {}
        for i, ref in enumerate(high_refs):
            for copy in range(10):  # 10 screens cite each high-impact ref
                sid = f"hi_{i}_{copy}"
                screens[sid] = WorkflowScreen(
                    screen_id=sid, title="t", ui_elements=[],
                    evidence_tier="observed", source_refs=[ref],
                )
        for i, ref in enumerate(mid_refs):
            sid = f"mid_{i}"
            screens[sid] = WorkflowScreen(
                screen_id=sid, title="t", ui_elements=[],
                evidence_tier="observed", source_refs=[ref],
            )
        tree = DecisionTree(root_screen_id="hi_0_0", screens=screens, branches=[])

        questions = await generate_questions(gaps, [tree])

        severities = [q.severity for q in questions]
        assert "critical" in severities, "expected at least one critical after rebalance"
        assert "low" in severities, "expected at least one low after rebalance"
        # Most should still be medium — rebalance only moves ~14% each direction
        assert severities.count("medium") > severities.count("critical")
        assert severities.count("medium") > severities.count("low")

    async def test_small_projects_skip_rebalance(self):
        from walkthrough.models.workflow import DecisionTree

        gaps = [
            Gap(
                gap_id=f"g{i}",
                severity="medium",
                description=f"g{i}",
                evidence=[_ref("video", "x"), _ref("pdf", "y", "SOP.pdf:1")],
            )
            for i in range(5)
        ]
        tree = DecisionTree(root_screen_id="r", screens={}, branches=[])

        questions = await generate_questions(gaps, [tree])

        # Below 10 mediums → no rebalance
        assert all(q.severity == "medium" for q in questions)
