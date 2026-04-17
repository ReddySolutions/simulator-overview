"""Tests for the best-guess tool.

Validates proposal parsing, LLM-failure graceful-None, missing-api-key
behavior, and that prior-answer context is formatted correctly.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from walkthrough.ai.tools import best_guess
from walkthrough.ai.tools.best_guess import (
    BestGuess,
    _format_prior,
    propose_best_guess,
)
from walkthrough.config import Settings
from walkthrough.models.project import Choice, ClarificationQuestion
from walkthrough.models.workflow import SourceRef


def _mock_settings(monkeypatch: pytest.MonkeyPatch, api_key: str = "key") -> None:
    monkeypatch.setattr(
        best_guess,
        "Settings",
        lambda: Settings(
            GEMINI_API_KEY=api_key,
            GEMINI_MODEL="gemini-test",
            LOCAL_DEV=True,
        ),
    )


def _q(
    question_id: str = "q1",
    text: str = "Should the button say Save or Submit?",
    choices: list[Choice] | None = None,
    answer: str | None = None,
) -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id=question_id,
        text=text,
        severity="medium",
        evidence=[
            SourceRef(source_type="video", reference="v.mp4:00:10", excerpt="Save & Continue"),
            SourceRef(source_type="pdf", reference="sop.pdf:p3", excerpt="Submit"),
        ],
        choices=choices or [],
        answer=answer,
    )


class TestBestGuess:
    async def test_missing_api_key_returns_none(self, monkeypatch):
        _mock_settings(monkeypatch, api_key="")
        result = await propose_best_guess(_q(), [])
        assert result is None

    async def test_llm_failure_returns_none(self, monkeypatch):
        _mock_settings(monkeypatch)

        async def boom(*_args, **_kwargs):
            raise RuntimeError("no network")

        with patch.object(best_guess, "_call_gemini", side_effect=boom):
            result = await propose_best_guess(_q(), [])

        assert result is None

    async def test_valid_response_returns_proposal(self, monkeypatch):
        _mock_settings(monkeypatch)

        async def fake_llm(*_args, **_kwargs):
            return json.dumps({
                "answer": "Save & Continue",
                "rationale": "Matches the video observation, which takes priority by convention.",
            })

        with patch.object(best_guess, "_call_gemini", side_effect=fake_llm):
            result = await propose_best_guess(_q(), [])

        assert isinstance(result, BestGuess)
        assert result.answer == "Save & Continue"
        assert "video observation" in result.rationale

    async def test_fenced_json_parsed(self, monkeypatch):
        _mock_settings(monkeypatch)

        async def fake_llm(*_args, **_kwargs):
            return '```json\n{"answer": "X", "rationale": "r"}\n```'

        with patch.object(best_guess, "_call_gemini", side_effect=fake_llm):
            result = await propose_best_guess(_q(), [])

        assert result is not None
        assert result.answer == "X"

    async def test_empty_answer_rejected(self, monkeypatch):
        _mock_settings(monkeypatch)

        async def fake_llm(*_args, **_kwargs):
            return json.dumps({"answer": "", "rationale": "nope"})

        with patch.object(best_guess, "_call_gemini", side_effect=fake_llm):
            result = await propose_best_guess(_q(), [])

        assert result is None

    async def test_non_json_rejected(self, monkeypatch):
        _mock_settings(monkeypatch)

        async def fake_llm(*_args, **_kwargs):
            return "I cannot answer this question."

        with patch.object(best_guess, "_call_gemini", side_effect=fake_llm):
            result = await propose_best_guess(_q(), [])

        assert result is None

    def test_prior_skips_unanswered_and_caps(self):
        prior = [
            _q(question_id=f"q{i}", text=f"Q{i}", answer=f"A{i}")
            for i in range(15)
        ]
        prior.append(_q(question_id="qN", text="unanswered", answer=None))
        prior.append(
            _q(question_id="qU", text="unanswerable", answer="Marked unanswerable by user"),
        )

        formatted = _format_prior(prior)

        # Cap at 10 recent, skip None answers and 'unanswerable' marker
        assert formatted.count("-> A:") == 10
        assert "unanswerable" not in formatted
        assert "A: A14" in formatted  # newest kept
