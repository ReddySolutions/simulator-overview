"""Surgical self-critique: v1 -> v2 review helper.

``surgical_review`` takes a v1 JSON dict produced by some earlier LLM call,
sends it plus the original source excerpts to a reviewer model, and applies
the reviewer's edit list to a deep copy. The result is validated against the
caller-supplied ``schema`` and returned as a dict (the v2).

The reviewer emits ``{"edits": [{"path": str, "operation": "replace"|"remove"|
"add", "new_value": any}]}``. An empty ``edits`` list means v1 was already
correct, which is the intended idempotence path: ``surgical_review(v2, ...)``
-> ``v3 == v2`` when the reviewer returns no further edits.

Gated by ``Settings().ENABLE_SELF_CRITIQUE`` -- when False, returns
``v1_output`` unchanged with zero HTTP calls.

Degradation policy (matches the other LLM critics on this branch): if the
reviewer call fails schema validation (exhausted retries) or the edited v2
fails ``schema`` validation, log a warning and return ``v1_output`` unchanged.
A broken self-critique is strictly worse than no self-critique; callers see
the v1 they already had.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ValidationError

from walkthrough.ai.llm.client import run_structured_json
from walkthrough.ai.prompts.compose import compose_system_prompt
from walkthrough.ai.prompts.fidelity import (
    EVIDENCE_CITATION_RULES,
    FIDELITY_STANDARD,
)
from walkthrough.config import Settings

logger = logging.getLogger(__name__)

TASK_PROMPT = (
    "Review the v1 output for unsupported claims, missing citations, and "
    "hallucinated labels against the provided source excerpts. Emit a "
    "minimal set of surgical edits. Paths use dotted notation; numeric "
    "segments index lists. Return ONLY edits that are strictly required "
    "by the evidence -- an empty edits list means v1 is already correct. "
    'Output JSON: {"edits": [{"path": str, "operation": '
    '"replace"|"remove"|"add", "new_value": any}]}'
)


class _EditOp(BaseModel):
    path: str
    operation: Literal["replace", "remove", "add"]
    new_value: Any = None


class _EditsResponse(BaseModel):
    edits: list[_EditOp]


def _split_path(path: str) -> list[str]:
    if not path:
        raise ValueError("edit path must be non-empty")
    return path.split(".")


def _descend(container: Any, segment: str) -> Any:
    if isinstance(container, list):
        idx = int(segment)
        return container[idx]
    if isinstance(container, dict):
        return container[segment]
    raise TypeError(
        f"cannot descend into {type(container).__name__} at segment {segment!r}"
    )


def _apply_edit(target: dict[str, Any], edit: _EditOp) -> None:
    segments = _split_path(edit.path)
    parent: Any = target
    for seg in segments[:-1]:
        parent = _descend(parent, seg)
    leaf = segments[-1]

    if isinstance(parent, list):
        idx = int(leaf)
        if edit.operation == "remove":
            del parent[idx]
        elif edit.operation == "add":
            parent.insert(idx, edit.new_value)
        else:  # replace
            parent[idx] = edit.new_value
        return

    if isinstance(parent, dict):
        if edit.operation == "remove":
            parent.pop(leaf, None)
        else:  # add or replace
            parent[leaf] = edit.new_value
        return

    raise TypeError(
        f"cannot apply edit at {edit.path!r}: parent is "
        f"{type(parent).__name__}"
    )


def _apply_edits(v1: dict[str, Any], edits: list[_EditOp]) -> dict[str, Any]:
    v2 = copy.deepcopy(v1)
    for edit in edits:
        _apply_edit(v2, edit)
    return v2


async def surgical_review(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    v1_output: dict[str, Any],
    source_excerpts: list[str],
    schema: type[BaseModel],
) -> dict[str, Any]:
    """Run a surgical review pass over ``v1_output`` and return v2.

    When ``Settings().ENABLE_SELF_CRITIQUE`` is False, returns ``v1_output``
    unchanged (no HTTP call). Otherwise asks the reviewer model for an
    edit list, applies edits to a deep copy, and validates the result
    against ``schema``. On any failure (exhausted retries, apply error,
    schema validation error) logs and returns ``v1_output`` unchanged.
    """
    settings = Settings()
    if not settings.ENABLE_SELF_CRITIQUE:
        return v1_output

    system = compose_system_prompt(
        FIDELITY_STANDARD,
        EVIDENCE_CITATION_RULES,
        task=TASK_PROMPT,
    )
    payload = {
        "v1_output": v1_output,
        "source_excerpts": source_excerpts,
    }

    try:
        response = await run_structured_json(
            client,
            model=model,
            system=system,
            user=json.dumps(payload),
            schema=_EditsResponse,
        )
    except ValueError:
        logger.warning(
            "surgical_review: reviewer returned unparseable edits; "
            "returning v1 unchanged"
        )
        return v1_output

    if not response.edits:
        return copy.deepcopy(v1_output)

    try:
        v2 = _apply_edits(v1_output, response.edits)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning(
            "surgical_review: failed to apply edits (%s); returning v1 "
            "unchanged",
            exc,
        )
        return v1_output

    try:
        schema.model_validate(v2)
    except ValidationError as exc:
        logger.warning(
            "surgical_review: v2 failed schema validation (%s); returning "
            "v1 unchanged",
            exc,
        )
        return v1_output

    return v2
