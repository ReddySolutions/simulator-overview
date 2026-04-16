"""Shared Anthropic client factory and structured-JSON helper.

`get_client()` builds an ``anthropic.AsyncAnthropic`` using the API key from
``Settings``. It raises only when actually called so module import stays safe
in environments without a key (e.g., tests or workers that never hit the LLM).

``run_structured_json`` wraps ``messages.create`` with:

* the system prompt sent as a single ``{"type": "text", ...}`` block carrying
  ``cache_control={"type": "ephemeral"}`` so upstream prompt caching keeps the
  system block warm across calls;
* a schema-validated response body: the model's text content is fed through
  ``schema.model_validate_json`` and on failure the helper retries up to
  ``max_retries`` times with a reminder user message appended to the
  conversation (the model gets to see its own bad output);
* a ``ValueError`` when retries are exhausted so callers treat JSON / schema
  failure as a hard error.

``max_retries=2`` therefore allows up to 3 total ``messages.create`` calls:
the initial attempt plus two retries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from walkthrough.config import Settings

if TYPE_CHECKING:
    from anthropic.types import MessageParam

ModelT = TypeVar("ModelT", bound=BaseModel)

REMINDER_MESSAGE = (
    "Return ONLY valid JSON per the schema; no markdown fencing"
)


def get_client() -> anthropic.AsyncAnthropic:
    """Build an ``AsyncAnthropic`` using the configured API key.

    Raises:
        ValueError: if ``ANTHROPIC_API_KEY`` is unset. The check only runs
            when this function is called so module import remains safe.
    """
    settings = Settings()
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set; cannot build Anthropic client"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


def _extract_text(response: Any) -> str:
    """Concatenate text blocks from an Anthropic message response."""
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


async def run_structured_json(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    system: str,
    user: str,
    schema: type[ModelT],
    max_tokens: int = 4096,
    max_retries: int = 2,
) -> ModelT:
    """Call ``messages.create`` and parse the response as ``schema``.

    Retries up to ``max_retries`` times when the response text cannot be
    validated against the schema, appending the prior bad reply + a reminder
    user message to the conversation so the model sees its own output.

    Raises:
        ValueError: when every attempt fails validation.
    """
    system_blocks = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[MessageParam] = [{"role": "user", "content": user}]

    last_error: ValidationError | None = None
    total_attempts = max_retries + 1
    for _ in range(total_attempts):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,  # type: ignore[arg-type]
            messages=messages,
        )
        text = _extract_text(response)
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": REMINDER_MESSAGE})

    raise ValueError(
        f"run_structured_json: exhausted {total_attempts} attempts for schema "
        f"{schema.__name__}: {last_error}"
    )
