"""Tests for walkthrough/ai/tools/narrative_critic.py (US-018)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from walkthrough.ai.tools.narrative_critic import (
    LLMUnsupportedResponse,
    critique_narratives,
)
from walkthrough.models.project import Gap
from walkthrough.models.video import UIElement
from walkthrough.models.workflow import (
    DecisionTree,
    Narrative,
    SourceRef,
    WorkflowScreen,
)


def _screen_with_narrative(
    screen_id: str = "s1",
    *,
    what: str = "User clicks Submit to finalize the form",
    why: str = "Submission records the entry in the database",
    when_condition: str | None = "After all required fields are filled",
    source_type: str = "video",
    reference: str = "train.mp4:00:10",
    excerpt: str = "Click Submit to complete the form",
) -> WorkflowScreen:
    return WorkflowScreen(
        screen_id=screen_id,
        title=f"Screen {screen_id}",
        ui_elements=[UIElement(element_type="button", label="Submit")],
        narrative=Narrative(
            what=what,
            why=why,
            when_condition=when_condition,
        ),
        evidence_tier="observed",
        source_refs=[
            SourceRef(
                source_type=source_type,  # type: ignore[arg-type]
                reference=reference,
                excerpt=excerpt,
            ),
        ],
    )


def _tree_with(*screens: WorkflowScreen) -> DecisionTree:
    screens_map = {s.screen_id: s for s in screens}
    return DecisionTree(
        root_screen_id=screens[0].screen_id,
        screens=screens_map,
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
        tree = _tree_with(_screen_with_narrative("s1"))
        client = _make_client([])

        result = await critique_narratives([tree], client=client)

        assert result == []
        client.messages.create.assert_not_awaited()


class TestFlagOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "true")
        monkeypatch.setenv("NARRATIVE_CRITIC_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def test_emits_gap_for_unsupported_claim(self) -> None:
        response_payload = {
            "unsupported": [
                {
                    "screen_id": "s1",
                    "claim": "Submission records the entry in the database",
                    "reason": (
                        "No excerpt mentions a database; only UI action "
                        "described"
                    ),
                },
            ]
        }
        client = _make_client([json.dumps(response_payload)])

        tree = _tree_with(_screen_with_narrative("s1"))
        result = await critique_narratives([tree], client=client)

        assert len(result) == 1
        gap = result[0]
        assert isinstance(gap, Gap)
        assert gap.severity == "medium"
        assert gap.description.startswith(
            "Narrative claim unsupported on s1: "
        )
        assert "Submission records" in gap.description
        assert gap.gap_id.startswith("gap_narr_")
        assert len(gap.evidence) == 1
        assert gap.evidence[0].source_type == "video"
        assert gap.evidence[0].reference == "s1"
        assert gap.evidence[0].excerpt is not None
        assert "No excerpt mentions a database" in gap.evidence[0].excerpt
        client.messages.create.assert_awaited_once()

    async def test_skips_screens_without_narrative(self) -> None:
        no_narr_screen = WorkflowScreen(
            screen_id="s_empty",
            title="No narrative here",
            ui_elements=[UIElement(element_type="button", label="Go")],
            narrative=None,
            evidence_tier="observed",
            source_refs=[
                SourceRef(
                    source_type="video",
                    reference="v.mp4:00:00",
                    excerpt="Go button",
                ),
            ],
        )
        client = _make_client([])

        tree = _tree_with(no_narr_screen)
        result = await critique_narratives([tree], client=client)

        assert result == []
        client.messages.create.assert_not_awaited()

    async def test_multi_screen_emits_per_screen_gaps(self) -> None:
        payload_s1 = {
            "unsupported": [
                {
                    "screen_id": "s1",
                    "claim": "Claim on s1",
                    "reason": "No matching excerpt",
                },
            ]
        }
        payload_s2 = {
            "unsupported": [
                {
                    "screen_id": "s2",
                    "claim": "Claim on s2",
                    "reason": "Missing support",
                },
            ]
        }
        client = _make_client(
            [json.dumps(payload_s1), json.dumps(payload_s2)]
        )

        tree = _tree_with(
            _screen_with_narrative("s1"),
            _screen_with_narrative("s2"),
        )
        result = await critique_narratives([tree], client=client)

        assert {g.gap_id for g in result} == {
            g.gap_id for g in result
        }  # unique
        assert len(result) == 2
        screen_ids = {g.evidence[0].reference for g in result}
        assert screen_ids == {"s1", "s2"}
        assert client.messages.create.await_count == 2

    async def test_empty_unsupported_list_yields_no_gaps(self) -> None:
        client = _make_client([json.dumps({"unsupported": []})])

        tree = _tree_with(_screen_with_narrative("s1"))
        result = await critique_narratives([tree], client=client)

        assert result == []

    async def test_malformed_response_is_swallowed_per_screen(self) -> None:
        # First screen: retries exhaust, second screen: valid empty list.
        bad = ["not json"] * 3  # max_retries=2 => 3 attempts exhaust
        good = [json.dumps({"unsupported": []})]
        client = _make_client(bad + good)

        tree = _tree_with(
            _screen_with_narrative("s1"),
            _screen_with_narrative("s2"),
        )
        result = await critique_narratives([tree], client=client)

        assert result == []
        # 3 attempts on s1 + 1 on s2
        assert client.messages.create.await_count == 4

    async def test_composed_system_prompt_and_payload_shape(self) -> None:
        client = _make_client([json.dumps({"unsupported": []})])

        tree = _tree_with(_screen_with_narrative("s1"))
        await critique_narratives([tree], client=client)

        call_kwargs = client.messages.create.await_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"

        system = call_kwargs["system"]
        assert isinstance(system, list)
        system_text = system[0]["text"]
        # FIDELITY_STANDARD marker
        assert "__unreadable__" in system_text
        # EVIDENCE_CITATION_RULES marker
        assert "SourceRef" in system_text
        # Task section present with the exact unsupported output contract
        assert "## Task" in system_text
        assert '"unsupported"' in system_text
        assert "narrative claims" in system_text.lower()
        assert system[0]["cache_control"] == {"type": "ephemeral"}

        user_content = call_kwargs["messages"][0]["content"]
        payload = json.loads(user_content)
        assert payload["screen_id"] == "s1"
        assert payload["narrative"]["what"].startswith("User clicks Submit")
        assert payload["narrative"]["why"].startswith("Submission records")
        assert payload["narrative"]["when_condition"] is not None
        assert len(payload["excerpts"]) == 1
        assert payload["excerpts"][0]["source_type"] == "video"

    async def test_dedups_identical_claim_on_same_screen(self) -> None:
        response_payload = {
            "unsupported": [
                {
                    "screen_id": "s1",
                    "claim": "Duplicate claim",
                    "reason": "reason A",
                },
                {
                    "screen_id": "s1",
                    "claim": "Duplicate claim",
                    "reason": "reason B",
                },
            ]
        }
        client = _make_client([json.dumps(response_payload)])

        tree = _tree_with(_screen_with_narrative("s1"))
        result = await critique_narratives([tree], client=client)

        assert len(result) == 1
        assert result[0].evidence[0].excerpt == "reason A"


def test_llm_unsupported_response_roundtrip() -> None:
    payload = {
        "unsupported": [
            {
                "screen_id": "s1",
                "claim": "claim text",
                "reason": "reason text",
            }
        ]
    }
    parsed = LLMUnsupportedResponse.model_validate(payload)
    assert len(parsed.unsupported) == 1
    assert parsed.unsupported[0].screen_id == "s1"
    assert parsed.unsupported[0].claim == "claim text"
