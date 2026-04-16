"""Tests for walkthrough/ai/tools/detect_contradictions_critic.py (US-016)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from walkthrough.ai.tools.detect_contradictions_critic import (
    LLMGapsResponse,
    critique_contradictions,
)
from walkthrough.models.pdf import PDFExtraction, PDFSection
from walkthrough.models.project import Gap
from walkthrough.models.video import (
    AudioSegment,
    Keyframe,
    UIElement,
    VideoAnalysis,
)
from walkthrough.models.workflow import DecisionTree, SourceRef, WorkflowScreen


def _video_with_submit() -> VideoAnalysis:
    return VideoAnalysis(
        video_id="vid1",
        filename="train.mp4",
        keyframes=[
            Keyframe(
                video_id="vid1",
                timestamp_sec=10.0,
                ui_elements=[
                    UIElement(element_type="button", label="Submit"),
                ],
                screenshot_description="A form page with a Submit button",
            ),
        ],
        transitions=[],
        audio_segments=[
            AudioSegment(
                start_sec=10.0,
                end_sec=12.0,
                text="Now click the Submit button to continue",
            ),
        ],
        temporal_flow=["00:10 Submit"],
    )


def _pdf_with_send() -> PDFExtraction:
    return PDFExtraction(
        pdf_id="pdf1",
        filename="SOP.pdf",
        sections=[
            PDFSection(
                heading="Section 2 - Completing the Form",
                text="After filling in all fields, press the Send button.",
                page_number=4,
                confidence=0.95,
            ),
        ],
        tables=[],
        images=[],
    )


def _decision_tree() -> DecisionTree:
    screen = WorkflowScreen(
        screen_id="s1",
        title="Form page",
        ui_elements=[UIElement(element_type="button", label="Submit")],
        evidence_tier="observed",
        source_refs=[
            SourceRef(
                source_type="video",
                reference="train.mp4:00:10",
                excerpt="Submit button visible",
            ),
        ],
    )
    return DecisionTree(
        root_screen_id="s1",
        screens={"s1": screen},
        branches=[],
    )


def _fake_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _make_client(texts: list[str]) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[_fake_response(t) for t in texts]
    )
    return client


class TestFlagOff:
    async def test_returns_empty_without_http_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "false")
        client = _make_client([])

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        assert result == []
        client.messages.create.assert_not_awaited()


class TestFlagOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "true")
        monkeypatch.setenv("CONTRADICTION_CRITIC_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def test_emits_new_gap_for_submit_vs_send(self) -> None:
        new_gap = {
            "gap_id": "gap_submit_vs_send",
            "severity": "medium",
            "description": (
                "Label mismatch: video shows 'Submit' button but PDF section "
                "2 documents 'Send' button on the same form"
            ),
            "evidence": [
                {
                    "source_type": "video",
                    "reference": "train.mp4:00:10",
                    "excerpt": "Submit button",
                },
                {
                    "source_type": "pdf",
                    "reference": "SOP.pdf:Section 2",
                    "excerpt": "press the Send button",
                },
            ],
        }
        response_text = json.dumps({"gaps": [new_gap]})
        client = _make_client([response_text])

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        assert len(result) == 1
        gap = result[0]
        assert isinstance(gap, Gap)
        assert gap.gap_id == "gap_submit_vs_send"
        assert gap.severity == "medium"
        assert "Submit" in gap.description and "Send" in gap.description
        assert len(gap.evidence) >= 2
        source_types = {ev.source_type for ev in gap.evidence}
        assert {"video", "pdf"}.issubset(source_types)
        client.messages.create.assert_awaited_once()

    async def test_filters_duplicates_against_existing_gaps(self) -> None:
        existing = Gap(
            gap_id="gap_known",
            severity="medium",
            description="Already detected by deterministic",
            evidence=[
                SourceRef(
                    source_type="video",
                    reference="train.mp4:00:00",
                    excerpt="known",
                ),
                SourceRef(
                    source_type="pdf",
                    reference="SOP.pdf:Section 1",
                    excerpt="known",
                ),
            ],
        )
        critic_payload = {
            "gaps": [
                {
                    "gap_id": "gap_known",  # duplicate of existing
                    "severity": "medium",
                    "description": "Already detected by deterministic",
                    "evidence": [
                        {
                            "source_type": "video",
                            "reference": "train.mp4:00:00",
                            "excerpt": "known",
                        },
                        {
                            "source_type": "pdf",
                            "reference": "SOP.pdf:Section 1",
                            "excerpt": "known",
                        },
                    ],
                },
                {
                    "gap_id": "gap_new",
                    "severity": "critical",
                    "description": "Novel contradiction",
                    "evidence": [
                        {
                            "source_type": "video",
                            "reference": "train.mp4:00:05",
                            "excerpt": "A",
                        },
                        {
                            "source_type": "pdf",
                            "reference": "SOP.pdf:Section 3",
                            "excerpt": "B",
                        },
                    ],
                },
            ]
        }
        client = _make_client([json.dumps(critic_payload)])

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [existing],
            client=client,
        )

        assert len(result) == 1
        assert result[0].gap_id == "gap_new"

    async def test_composed_system_prompt_and_user_payload_shape(self) -> None:
        response_text = json.dumps({"gaps": []})
        client = _make_client([response_text])

        await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        call_kwargs = client.messages.create.await_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"

        # system comes through run_structured_json as a list of text blocks
        system = call_kwargs["system"]
        assert isinstance(system, list)
        system_text = system[0]["text"]
        # Composed from the four fidelity blocks + task
        assert "__unreadable__" in system_text  # FIDELITY_STANDARD marker
        assert "M1" in system_text  # INVARIANTS marker
        assert "authority hierarchy" in system_text.lower()
        assert "SourceRef" in system_text  # EVIDENCE_CITATION_RULES marker
        assert "## Task" in system_text
        assert "deterministic detector" in system_text
        assert system[0]["cache_control"] == {"type": "ephemeral"}

        user_content = call_kwargs["messages"][0]["content"]
        payload = json.loads(user_content)
        assert "videos" in payload
        assert "pdfs" in payload
        assert "existing_gaps" in payload
        assert payload["videos"][0]["filename"] == "train.mp4"
        assert payload["pdfs"][0]["filename"] == "SOP.pdf"

    async def test_malformed_llm_response_yields_empty_list(self) -> None:
        # run_structured_json exhausts retries and raises ValueError;
        # the critic should swallow and return [].
        client = _make_client(["not json"] * 10)

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        assert result == []

    async def test_empty_gaps_response_yields_empty_list(self) -> None:
        client = _make_client([json.dumps({"gaps": []})])

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        assert result == []

    async def test_self_critique_off_does_not_call_surgical_review(self) -> None:
        """QA flag on, self-critique off -> one HTTP call only."""
        new_gap = {
            "gap_id": "gap_x",
            "severity": "medium",
            "description": "some finding",
            "evidence": [
                {
                    "source_type": "video",
                    "reference": "train.mp4:00:10",
                    "excerpt": "Submit",
                },
                {
                    "source_type": "pdf",
                    "reference": "SOP.pdf:S2",
                    "excerpt": "Send",
                },
            ],
        }
        client = _make_client([json.dumps({"gaps": [new_gap]})])

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        assert len(result) == 1
        assert result[0].gap_id == "gap_x"
        assert client.messages.create.await_count == 1


class TestSelfCritiqueOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "true")
        monkeypatch.setenv("ENABLE_SELF_CRITIQUE", "true")
        monkeypatch.setenv("CONTRADICTION_CRITIC_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("SELF_CRITIQUE_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def test_surgical_review_v2_differs_from_v1(self) -> None:
        """Flag on: reviewer edits v1 description; v2 gap carries edited text."""
        v1_gap = {
            "gap_id": "gap_x",
            "severity": "medium",
            "description": "Original description",
            "evidence": [
                {
                    "source_type": "video",
                    "reference": "train.mp4:00:10",
                    "excerpt": "Submit",
                },
                {
                    "source_type": "pdf",
                    "reference": "SOP.pdf:S2",
                    "excerpt": "Send",
                },
            ],
        }
        v1_text = json.dumps({"gaps": [v1_gap]})
        edits_text = json.dumps(
            {
                "edits": [
                    {
                        "path": "gaps.0.description",
                        "operation": "replace",
                        "new_value": "Reviewed description",
                    }
                ]
            }
        )
        client = _make_client([v1_text, edits_text])

        result = await critique_contradictions(
            [_video_with_submit()],
            [_pdf_with_send()],
            [_decision_tree()],
            [],
            client=client,
        )

        assert len(result) == 1
        assert result[0].description == "Reviewed description"
        # v1 + surgical_review = 2 calls
        assert client.messages.create.await_count == 2


def test_llm_gaps_response_roundtrip() -> None:
    payload = {
        "gaps": [
            {
                "gap_id": "g1",
                "severity": "critical",
                "description": "desc",
                "evidence": [
                    {
                        "source_type": "video",
                        "reference": "v.mp4:00:00",
                        "excerpt": "x",
                    },
                    {
                        "source_type": "pdf",
                        "reference": "p.pdf:S1",
                        "excerpt": "y",
                    },
                ],
            }
        ]
    }
    parsed = LLMGapsResponse.model_validate(payload)
    assert len(parsed.gaps) == 1
    assert parsed.gaps[0].severity == "critical"
