"""Tests for walkthrough/ai/llm/review_pass.py (US-020)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from walkthrough.ai.llm.review_pass import surgical_review


class V1Schema(BaseModel):
    title: str
    items: list[str]
    nested: dict[str, Any]


def _fake_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _make_client(texts: list[str]) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[_fake_response(t) for t in texts]
    )
    return client


def _v1() -> dict[str, Any]:
    return {
        "title": "Submit form",
        "items": ["a", "b", "c"],
        "nested": {"key": "old", "keep": "unchanged"},
    }


class TestFlagOff:
    async def test_returns_v1_unchanged_without_http_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENABLE_SELF_CRITIQUE", "false")
        client = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=AssertionError("flag-off must not call the LLM")
        )
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=["evidence 1"],
            schema=V1Schema,
        )

        assert v2 == v1
        assert v2 is v1  # flag-off returns the same object (no copy)
        client.messages.create.assert_not_called()


class TestFlagOn:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_SELF_CRITIQUE", "true")

    async def test_edits_applied_returns_modified_v2(self) -> None:
        edits_response = json.dumps(
            {
                "edits": [
                    {
                        "path": "title",
                        "operation": "replace",
                        "new_value": "Send form",
                    },
                ]
            }
        )
        client = _make_client([edits_response])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=["The PDF says 'Send form'"],
            schema=V1Schema,
        )

        assert v2 != v1
        assert v2["title"] == "Send form"
        # Original v1 untouched (we operated on a deep copy)
        assert v1["title"] == "Submit form"
        # Other fields preserved
        assert v2["items"] == ["a", "b", "c"]
        assert v2["nested"] == {"key": "old", "keep": "unchanged"}

    async def test_idempotence_v3_equals_v2_when_no_more_edits(self) -> None:
        first = json.dumps(
            {
                "edits": [
                    {
                        "path": "title",
                        "operation": "replace",
                        "new_value": "Send form",
                    },
                ]
            }
        )
        empty = json.dumps({"edits": []})
        client = _make_client([first, empty])

        v1 = _v1()
        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=["The PDF says 'Send form'"],
            schema=V1Schema,
        )
        v3 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v2,
            source_excerpts=["The PDF says 'Send form'"],
            schema=V1Schema,
        )

        assert v3 == v2
        assert client.messages.create.await_count == 2

    async def test_empty_edits_returns_equal_copy_of_v1(self) -> None:
        client = _make_client([json.dumps({"edits": []})])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert v2 == v1

    async def test_remove_operation_on_dict_key(self) -> None:
        edits = json.dumps(
            {
                "edits": [
                    {
                        "path": "nested.key",
                        "operation": "remove",
                        "new_value": None,
                    },
                ]
            }
        )
        client = _make_client([edits])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert "key" not in v2["nested"]
        assert v2["nested"] == {"keep": "unchanged"}
        # v1 untouched
        assert v1["nested"] == {"key": "old", "keep": "unchanged"}

    async def test_add_operation_inserts_into_list(self) -> None:
        edits = json.dumps(
            {
                "edits": [
                    {
                        "path": "items.1",
                        "operation": "add",
                        "new_value": "new-b",
                    },
                ]
            }
        )
        client = _make_client([edits])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert v2["items"] == ["a", "new-b", "b", "c"]
        assert v1["items"] == ["a", "b", "c"]

    async def test_replace_list_index(self) -> None:
        edits = json.dumps(
            {
                "edits": [
                    {
                        "path": "items.0",
                        "operation": "replace",
                        "new_value": "A",
                    },
                ]
            }
        )
        client = _make_client([edits])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert v2["items"] == ["A", "b", "c"]

    async def test_exhausted_retries_degrades_to_v1(self) -> None:
        client = _make_client(["not json", "still not json", "bad"])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert v2 is v1
        assert client.messages.create.await_count == 3

    async def test_v2_failing_schema_validation_degrades_to_v1(self) -> None:
        # Replace the required `title` with a non-string -> schema validation
        # on v2 fails; surgical_review returns v1 unchanged.
        edits = json.dumps(
            {
                "edits": [
                    {
                        "path": "title",
                        "operation": "replace",
                        "new_value": 123,
                    },
                ]
            }
        )
        client = _make_client([edits])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert v2 is v1

    async def test_bad_path_degrades_to_v1(self) -> None:
        edits = json.dumps(
            {
                "edits": [
                    {
                        "path": "does.not.exist",
                        "operation": "replace",
                        "new_value": "x",
                    },
                ]
            }
        )
        client = _make_client([edits])
        v1 = _v1()

        v2 = await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=[],
            schema=V1Schema,
        )

        assert v2 is v1

    async def test_system_prompt_and_user_payload_shape(self) -> None:
        edits = json.dumps({"edits": []})
        client = _make_client([edits])
        v1 = _v1()
        excerpts = ["evidence one", "evidence two"]

        await surgical_review(
            client,
            model="claude-sonnet-4-6",
            v1_output=v1,
            source_excerpts=excerpts,
            schema=V1Schema,
        )

        kwargs = client.messages.create.await_args.kwargs
        assert kwargs["model"] == "claude-sonnet-4-6"
        system = kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        sys_text = system[0]["text"]
        assert "__unreadable__" in sys_text
        assert "SourceRef" in sys_text
        assert "## Task" in sys_text
        assert '"edits"' in sys_text
        assert "replace" in sys_text
        assert "remove" in sys_text
        assert "add" in sys_text

        user_payload = json.loads(kwargs["messages"][0]["content"])
        assert user_payload["v1_output"] == v1
        assert user_payload["source_excerpts"] == excerpts
