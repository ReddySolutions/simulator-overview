"""Tests for walkthrough/ai/llm/client.py (US-015)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from walkthrough.ai.llm.client import (
    REMINDER_MESSAGE,
    get_client,
    run_structured_json,
)


class DummyPayload(BaseModel):
    kind: str
    count: int


def _fake_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _make_client(texts: list[str]) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[_fake_response(t) for t in texts]
    )
    return client


class TestGetClient:
    def test_module_import_does_not_fail_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Import happens at test-collection time; this test just confirms the
        # module loads even when the key is empty.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        import importlib

        import walkthrough.ai.llm.client as client_mod

        importlib.reload(client_mod)
        assert hasattr(client_mod, "get_client")

    def test_raises_when_key_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_client()

    def test_returns_async_anthropic_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import anthropic

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        client = get_client()
        assert isinstance(client, anthropic.AsyncAnthropic)


class TestRunStructuredJson:
    async def test_happy_path_returns_parsed_model(self) -> None:
        client = _make_client(['{"kind": "a", "count": 1}'])

        result = await run_structured_json(
            client,
            model="claude-sonnet-4-6",
            system="You are a helper.",
            user="Go.",
            schema=DummyPayload,
        )

        assert isinstance(result, DummyPayload)
        assert result.kind == "a"
        assert result.count == 1
        client.messages.create.assert_awaited_once()

    async def test_happy_path_sends_system_with_ephemeral_cache_control(
        self,
    ) -> None:
        client = _make_client(['{"kind": "a", "count": 1}'])

        await run_structured_json(
            client,
            model="claude-sonnet-4-6",
            system="SYSTEM-PROMPT-A",
            user="Go.",
            schema=DummyPayload,
        )

        call_kwargs = client.messages.create.await_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == 4096
        system = call_kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["type"] == "text"
        assert system[0]["text"] == "SYSTEM-PROMPT-A"
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert call_kwargs["messages"] == [{"role": "user", "content": "Go."}]

    async def test_invalid_then_valid_succeeds_on_retry(self) -> None:
        client = _make_client(
            [
                "not json at all",
                '{"kind": "b", "count": 2}',
            ]
        )

        result = await run_structured_json(
            client,
            model="claude-sonnet-4-6",
            system="SYS",
            user="Go.",
            schema=DummyPayload,
            max_retries=2,
        )

        assert result.kind == "b"
        assert result.count == 2
        assert client.messages.create.await_count == 2

        # Second call must include the prior assistant bad-reply + reminder
        second_call = client.messages.create.await_args_list[1].kwargs
        messages = second_call["messages"]
        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "Go."}
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "not json at all"
        assert messages[2] == {"role": "user", "content": REMINDER_MESSAGE}

    async def test_exhausted_retries_raises_value_error(self) -> None:
        client = _make_client(
            [
                "bad 1",
                "bad 2",
                "bad 3",
            ]
        )

        with pytest.raises(ValueError, match="exhausted"):
            await run_structured_json(
                client,
                model="claude-sonnet-4-6",
                system="SYS",
                user="Go.",
                schema=DummyPayload,
                max_retries=2,
            )

        assert client.messages.create.await_count == 3

    async def test_schema_mismatch_counts_as_invalid(self) -> None:
        # Valid JSON but wrong shape -> pydantic ValidationError -> retry path
        client = _make_client(
            [
                '{"kind": "a"}',  # missing `count`
                '{"kind": "a", "count": 7}',
            ]
        )

        result = await run_structured_json(
            client,
            model="claude-sonnet-4-6",
            system="SYS",
            user="Go.",
            schema=DummyPayload,
        )

        assert result.count == 7
        assert client.messages.create.await_count == 2
