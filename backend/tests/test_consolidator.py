"""Tests for the consolidator tool.

The consolidator ships meta-questions by calling Gemini. Tests stub the
LLM call so the logic around minimum-gap threshold, response parsing,
invalid-id filtering, and graceful failure is covered without any
network calls.
"""

from __future__ import annotations

import json
from typing import Literal
from unittest.mock import patch

import pytest

from walkthrough.ai.tools import consolidator
from walkthrough.ai.tools.consolidator import (
    MAX_META_QUESTIONS,
    MIN_GAPS_TO_CONSOLIDATE,
    consolidate_gaps,
)
from walkthrough.config import Settings
from walkthrough.models.project import Gap
from walkthrough.models.workflow import SourceRef


def _gap(gap_id: str, severity: Literal["critical", "medium", "low"] = "medium") -> Gap:
    return Gap(
        gap_id=gap_id,
        severity=severity,
        description=f"desc for {gap_id}",
        evidence=[SourceRef(source_type="video", reference="v.mp4:00:01", excerpt="x")],
    )


def _mock_settings(monkeypatch: pytest.MonkeyPatch, api_key: str = "key") -> None:
    """Patch Settings() to return a stub with the given API key."""
    monkeypatch.setattr(
        consolidator,
        "Settings",
        lambda: Settings(
            GEMINI_API_KEY=api_key,
            GEMINI_MODEL="gemini-test",
            LOCAL_DEV=True,
        ),
    )


class TestConsolidator:
    async def test_below_threshold_returns_empty(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE - 1)]

        result = await consolidate_gaps(gaps)

        assert result == []

    async def test_missing_api_key_returns_empty(self, monkeypatch):
        _mock_settings(monkeypatch, api_key="")
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 5)]

        result = await consolidate_gaps(gaps)

        assert result == []

    async def test_llm_failure_returns_empty(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 5)]

        async def boom(*_args, **_kwargs):
            raise RuntimeError("gemini unavailable")

        with patch.object(consolidator, "_call_gemini", side_effect=boom):
            result = await consolidate_gaps(gaps)

        assert result == []

    async def test_valid_response_emits_meta_questions(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 2)]
        payload = {
            "meta_questions": [
                {
                    "text": "Can you record the refund flow?",
                    "rationale": "We see refund branches but never observed them.",
                    "affected_gap_ids": ["g0", "g1", "g2", "g3", "g4"],
                },
                {
                    "text": "Should we always prefer the video label?",
                    "rationale": "Most mismatches are label-only.",
                    "affected_gap_ids": ["g5", "g6", "g7"],
                },
            ]
        }

        async def fake_llm(*_args, **_kwargs):
            return json.dumps(payload)

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            result = await consolidate_gaps(gaps)

        assert len(result) == 2
        assert result[0].text == "Can you record the refund flow?"
        assert result[0].affected_gap_ids == ["g0", "g1", "g2", "g3", "g4"]
        assert result[1].affected_gap_ids == ["g5", "g6", "g7"]
        # Deterministic id based on text hash
        assert result[0].meta_question_id.startswith("mq_")

    async def test_unknown_gap_ids_are_dropped(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 2)]
        payload = {
            "meta_questions": [
                {
                    "text": "Valid question",
                    "rationale": "r",
                    "affected_gap_ids": ["g0", "ghost_id", "g1"],
                },
                {
                    "text": "Would-be empty after filter",
                    "rationale": "r",
                    "affected_gap_ids": ["ghost_1", "ghost_2"],
                },
            ]
        }

        async def fake_llm(*_args, **_kwargs):
            return json.dumps(payload)

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            result = await consolidate_gaps(gaps)

        # First meta-question keeps only real ids; second is dropped entirely
        assert len(result) == 1
        assert result[0].affected_gap_ids == ["g0", "g1"]

    async def test_markdown_fenced_json_is_parsed(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 2)]
        payload = {
            "meta_questions": [
                {
                    "text": "Question",
                    "rationale": "r",
                    "affected_gap_ids": ["g0"],
                }
            ]
        }

        async def fake_llm(*_args, **_kwargs):
            return "```json\n" + json.dumps(payload) + "\n```"

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            result = await consolidate_gaps(gaps)

        assert len(result) == 1

    async def test_more_than_max_are_truncated(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 5)]
        payload = {
            "meta_questions": [
                {
                    "text": f"Question {i}",
                    "rationale": "r",
                    "affected_gap_ids": [f"g{i}"],
                }
                for i in range(MAX_META_QUESTIONS + 3)
            ]
        }

        async def fake_llm(*_args, **_kwargs):
            return json.dumps(payload)

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            result = await consolidate_gaps(gaps)

        assert len(result) == MAX_META_QUESTIONS

    async def test_choices_are_parsed_when_present(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 2)]
        payload = {
            "meta_questions": [
                {
                    "text": "Prefer video or PDF labels?",
                    "rationale": "Label mismatches are most common.",
                    "affected_gap_ids": ["g0", "g1", "g2"],
                    "choices": [
                        {"label": "Always video", "description": "Trust the observation"},
                        {"label": "Always PDF"},
                        {"label": "Case by case"},
                    ],
                }
            ]
        }

        async def fake_llm(*_args, **_kwargs):
            return json.dumps(payload)

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            [mq] = await consolidate_gaps(gaps)

        assert [c.label for c in mq.choices] == [
            "Always video",
            "Always PDF",
            "Case by case",
        ]
        assert mq.choices[0].description == "Trust the observation"
        assert mq.choices[1].description is None

    async def test_malformed_choices_are_skipped(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 2)]
        payload = {
            "meta_questions": [
                {
                    "text": "Question",
                    "rationale": "r",
                    "affected_gap_ids": ["g0"],
                    "choices": [
                        {"label": "Valid"},
                        "not a dict",
                        {"label": ""},  # empty label dropped
                        {"description": "no label"},
                    ],
                }
            ]
        }

        async def fake_llm(*_args, **_kwargs):
            return json.dumps(payload)

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            [mq] = await consolidate_gaps(gaps)

        assert len(mq.choices) == 1
        assert mq.choices[0].label == "Valid"

    async def test_non_json_response_returns_empty(self, monkeypatch):
        _mock_settings(monkeypatch)
        gaps = [_gap(f"g{i}") for i in range(MIN_GAPS_TO_CONSOLIDATE + 2)]

        async def fake_llm(*_args, **_kwargs):
            return "sorry, I can't help"

        with patch.object(consolidator, "_call_gemini", side_effect=fake_llm):
            result = await consolidate_gaps(gaps)

        assert result == []
