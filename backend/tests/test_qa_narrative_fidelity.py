"""Tests for walkthrough/ai/qa/narrative_fidelity_critic.py (US-008)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from walkthrough.ai.qa.narrative_fidelity_critic import validate
from walkthrough.models.project import Project
from walkthrough.models.workflow import (
    DecisionTree,
    Narrative,
    SourceRef,
    WorkflowScreen,
)


def _video_ref(excerpt: str = "User clicks Submit") -> SourceRef:
    return SourceRef(
        source_type="video",
        reference="train.mp4:00:10",
        excerpt=excerpt,
    )


def _screen(
    screen_id: str,
    *,
    narrative: Narrative | None = None,
    source_refs: list[SourceRef] | None = None,
) -> WorkflowScreen:
    return WorkflowScreen(
        screen_id=screen_id,
        title=f"Screen {screen_id}",
        ui_elements=[],
        narrative=narrative,
        evidence_tier="observed",
        source_refs=source_refs if source_refs is not None else [_video_ref()],
    )


def _tree(*screens: WorkflowScreen) -> DecisionTree:
    return DecisionTree(
        root_screen_id=screens[0].screen_id,
        screens={s.screen_id: s for s in screens},
        branches=[],
    )


def _project(*trees: DecisionTree) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        project_id="proj_nfc",
        name="Narrative Fidelity Critic Test",
        status="analyzing",
        videos=[],
        pdfs=[],
        decision_trees=list(trees),
        gaps=[],
        questions=[],
        created_at=now,
        updated_at=now,
    )


def _fake_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _make_client(response_texts: list[str]) -> MagicMock:
    """Build a MagicMock AsyncAnthropic client that returns mocked responses."""
    client = MagicMock()
    responses = [_fake_response(t) for t in response_texts]
    client.messages.create = AsyncMock(side_effect=responses)
    return client


class TestFlagOff:
    async def test_returns_empty_result_without_http_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "false")
        project = _project(
            _tree(
                _screen(
                    "s1",
                    narrative=Narrative(
                        what="User submits form",
                        why="To complete intake",
                    ),
                )
            )
        )
        client = _make_client([])

        result = await validate(project, client=client)

        assert result.validator == "narrative_fidelity"
        assert result.ok is True
        assert result.findings == []
        client.messages.create.assert_not_awaited()


class TestFlagOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QA_ENABLE_LLM_CRITIC", "true")
        monkeypatch.setenv(
            "NARRATIVE_FIDELITY_MODEL", "claude-haiku-4-5-20251001"
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def test_emits_finding_from_unsupported_claim(self) -> None:
        project = _project(
            _tree(
                _screen(
                    "s1",
                    narrative=Narrative(
                        what="User clicks Submit",
                        why="To send the form",
                    ),
                )
            )
        )
        response_text = json.dumps(
            {
                "unsupported_claims": [
                    {
                        "claim": "Form auto-saves every 10 seconds",
                        "reason": "No excerpt mentions auto-save behavior",
                    }
                ]
            }
        )
        client = _make_client([response_text])

        result = await validate(project, client=client)

        assert result.ok is True  # findings are medium, not critical
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.severity == "medium"
        assert finding.code == "narrative_unsupported_claim"
        assert finding.screen_id == "s1"
        assert "Form auto-saves" in finding.message
        assert "auto-save behavior" in finding.message
        client.messages.create.assert_awaited_once()

    async def test_skips_screens_without_narrative(self) -> None:
        project = _project(
            _tree(
                _screen("s1", narrative=None),
                _screen(
                    "s2",
                    narrative=Narrative(what="Step 2", why="Reason"),
                ),
            )
        )
        response_text = json.dumps({"unsupported_claims": []})
        client = _make_client([response_text])

        result = await validate(project, client=client)

        assert result.ok is True
        assert result.findings == []
        # Only s2 has a narrative, so exactly one call
        assert client.messages.create.await_count == 1

    async def test_empty_unsupported_claims_yields_no_findings(self) -> None:
        project = _project(
            _tree(
                _screen(
                    "s1",
                    narrative=Narrative(what="Step 1", why="Reason"),
                )
            )
        )
        response_text = json.dumps({"unsupported_claims": []})
        client = _make_client([response_text])

        result = await validate(project, client=client)

        assert result.ok is True
        assert result.findings == []

    async def test_malformed_json_response_is_ignored(self) -> None:
        project = _project(
            _tree(
                _screen(
                    "s1",
                    narrative=Narrative(what="Step 1", why="Reason"),
                )
            )
        )
        client = _make_client(["not json at all"])

        result = await validate(project, client=client)

        assert result.ok is True
        assert result.findings == []

    async def test_multiple_screens_multiple_findings(self) -> None:
        project = _project(
            _tree(
                _screen(
                    "s1",
                    narrative=Narrative(what="Step 1", why="Reason 1"),
                ),
                _screen(
                    "s2",
                    narrative=Narrative(what="Step 2", why="Reason 2"),
                ),
            )
        )
        client = _make_client(
            [
                json.dumps(
                    {
                        "unsupported_claims": [
                            {"claim": "Claim A", "reason": "No evidence A"}
                        ]
                    }
                ),
                json.dumps(
                    {
                        "unsupported_claims": [
                            {"claim": "Claim B", "reason": "No evidence B"}
                        ]
                    }
                ),
            ]
        )

        result = await validate(project, client=client)

        assert len(result.findings) == 2
        screen_ids = {f.screen_id for f in result.findings}
        assert screen_ids == {"s1", "s2"}
        assert client.messages.create.await_count == 2

    async def test_uses_configured_model_and_parameters(self) -> None:
        project = _project(
            _tree(
                _screen(
                    "s1",
                    narrative=Narrative(
                        what="Step 1",
                        why="Reason",
                        when_condition="After login",
                    ),
                    source_refs=[
                        _video_ref("User clicks the Submit button at 0:10"),
                    ],
                )
            )
        )
        response_text = json.dumps({"unsupported_claims": []})
        client = _make_client([response_text])

        await validate(project, client=client)

        call_kwargs = client.messages.create.await_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["temperature"] == 0.0
        assert "narrative" in call_kwargs["system"].lower()
        user_content = call_kwargs["messages"][0]["content"]
        payload = json.loads(user_content)
        assert payload["narrative"]["what"] == "Step 1"
        assert payload["narrative"]["when_condition"] == "After login"
        assert payload["excerpts"][0]["excerpt"].startswith("User clicks")
