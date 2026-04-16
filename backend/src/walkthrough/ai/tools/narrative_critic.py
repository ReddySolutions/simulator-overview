"""Narrative LLM critic (additive, flag-gated).

Reviews the synthesized narrative on each ``WorkflowScreen`` against its
cited ``SourceRef`` excerpts and emits a ``Gap`` for every claim the LLM
flags as unsupported. Runs per-screen so a single bad call cannot poison
the whole tree; bad responses from ``run_structured_json`` (exhausted
retries -> ``ValueError``) are swallowed and that screen contributes zero
gaps.

Gated by ``Settings().QA_ENABLE_LLM_CRITIC`` -- when False this is a
no-op that makes zero HTTP calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import anthropic
from pydantic import BaseModel

from walkthrough.ai.llm.client import run_structured_json
from walkthrough.ai.llm.review_pass import surgical_review
from walkthrough.ai.prompts.compose import compose_system_prompt
from walkthrough.ai.prompts.fidelity import (
    EVIDENCE_CITATION_RULES,
    FIDELITY_STANDARD,
)
from walkthrough.config import Settings
from walkthrough.models.project import Gap
from walkthrough.models.workflow import DecisionTree, SourceRef, WorkflowScreen

logger = logging.getLogger(__name__)

TASK_PROMPT = (
    "Identify narrative claims not supported by the listed source excerpts. "
    'Output JSON: {"unsupported": [{"screen_id": str, "claim": str, '
    '"reason": str}]}'
)


class _UnsupportedClaim(BaseModel):
    screen_id: str
    claim: str
    reason: str


class LLMUnsupportedResponse(BaseModel):
    unsupported: list[_UnsupportedClaim]


def _gap_id(screen_id: str, claim: str) -> str:
    digest = hashlib.sha256(f"{screen_id}|{claim}".encode()).hexdigest()[:10]
    return f"gap_narr_{digest}"


def _build_payload(screen_id: str, screen: WorkflowScreen) -> dict[str, Any]:
    narrative = screen.narrative
    assert narrative is not None  # caller filters screens without narrative
    return {
        "screen_id": screen_id,
        "narrative": {
            "what": narrative.what,
            "why": narrative.why,
            "when_condition": narrative.when_condition,
        },
        "excerpts": [
            {
                "source_type": ref.source_type,
                "reference": ref.reference,
                "excerpt": ref.excerpt,
            }
            for ref in screen.source_refs
        ],
    }


async def critique_narratives(
    decision_trees: list[DecisionTree],
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> list[Gap]:
    """Return gaps the LLM critic found for unsupported narrative claims.

    Returns an empty list when ``Settings().QA_ENABLE_LLM_CRITIC`` is
    False (no HTTP calls). One LLM call is issued per screen carrying a
    narrative; a bad response on any single screen yields zero gaps for
    that screen but does not halt the remaining screens.
    """
    settings = Settings()
    if not settings.QA_ENABLE_LLM_CRITIC:
        return []

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    system = compose_system_prompt(
        FIDELITY_STANDARD,
        EVIDENCE_CITATION_RULES,
        task=TASK_PROMPT,
    )

    gaps: list[Gap] = []
    seen_ids: set[str] = set()

    for tree in decision_trees:
        for screen_id, screen in tree.screens.items():
            if screen.narrative is None:
                continue

            payload = _build_payload(screen_id, screen)
            try:
                response = await run_structured_json(
                    client,
                    model=settings.NARRATIVE_CRITIC_MODEL,
                    system=system,
                    user=json.dumps(payload),
                    schema=LLMUnsupportedResponse,
                )
            except ValueError:
                logger.warning(
                    "narrative_critic: LLM call failed schema validation "
                    "for screen %s; skipping",
                    screen_id,
                )
                continue

            if settings.ENABLE_SELF_CRITIQUE:
                source_excerpts = [
                    ref.excerpt
                    for ref in screen.source_refs
                    if ref.excerpt
                ]
                v1_dict = response.model_dump(mode="json")
                v2_dict = await surgical_review(
                    client,
                    model=settings.SELF_CRITIQUE_MODEL,
                    v1_output=v1_dict,
                    source_excerpts=source_excerpts,
                    schema=LLMUnsupportedResponse,
                )
                response = LLMUnsupportedResponse.model_validate(v2_dict)

            for item in response.unsupported:
                claim = item.claim.strip()
                reason = item.reason.strip()
                if not claim:
                    continue
                gap_id = _gap_id(screen_id, claim)
                if gap_id in seen_ids:
                    continue
                seen_ids.add(gap_id)
                gaps.append(
                    Gap(
                        gap_id=gap_id,
                        severity="medium",
                        description=(
                            f"Narrative claim unsupported on {screen_id}: "
                            f"{claim}"
                        ),
                        evidence=[
                            SourceRef(
                                source_type="video",
                                reference=screen_id,
                                excerpt=reason,
                            ),
                        ],
                    )
                )

    return gaps
