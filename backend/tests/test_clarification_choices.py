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
