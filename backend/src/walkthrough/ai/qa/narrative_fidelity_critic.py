"""Narrative-fidelity critic (LLM validator, flag-gated).

Checks whether each screen's narrative claims are actually supported by its
cited source excerpts. All LLM traffic sits behind
``Settings().QA_ENABLE_LLM_CRITIC`` — when the flag is off the validator
skips the network and returns an empty, ok result.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from pydantic import BaseModel

from walkthrough.ai.llm.review_pass import surgical_review
from walkthrough.config import Settings
from walkthrough.models.project import Project
from walkthrough.models.qa import ValidatorFinding, ValidatorResult

logger = logging.getLogger(__name__)


class _FidelityClaim(BaseModel):
    claim: str = ""
    reason: str = ""


class _FidelityV1(BaseModel):
    unsupported_claims: list[_FidelityClaim]

SYSTEM_PROMPT = (
    "You check if narrative text is supported by source excerpts. "
    "A claim is unsupported if no excerpt contains evidence for it. "
    "Paraphrase alone is NOT evidence — require overlap of specific nouns "
    "or UI labels. Output JSON: "
    '{"unsupported_claims": [{"claim": str, "reason": str}]}'
)

MAX_TOKENS = 1024
TEMPERATURE = 0.0


def _build_payload(screen: Any) -> dict[str, Any]:
    narrative = screen.narrative
    return {
        "narrative": {
            "what": narrative.what,
            "why": narrative.why,
            "when_condition": narrative.when_condition,
        },
        "excerpts": [
            {"reference": ref.reference, "excerpt": ref.excerpt}
            for ref in screen.source_refs
        ],
    }


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text  # type: ignore[attr-defined]
    return ""


def _parse_unsupported_claims(text: str) -> list[dict[str, str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("narrative_fidelity_critic: non-JSON response ignored")
        return []
    claims = data.get("unsupported_claims", [])
    if not isinstance(claims, list):
        return []
    return [c for c in claims if isinstance(c, dict)]


async def validate(
    project: Project,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> ValidatorResult:
    """Validate narrative fidelity against cited excerpts.

    When ``Settings().QA_ENABLE_LLM_CRITIC`` is False this returns an empty,
    ok result without any HTTP calls.
    """
    settings = Settings()
    if not settings.QA_ENABLE_LLM_CRITIC:
        return ValidatorResult(
            validator="narrative_fidelity",
            ok=True,
            findings=[],
        )

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    findings: list[ValidatorFinding] = []
    model = settings.NARRATIVE_FIDELITY_MODEL

    for tree in project.decision_trees:
        for screen_id, screen in tree.screens.items():
            if screen.narrative is None:
                continue

            payload = _build_payload(screen)
            response = await client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": json.dumps(payload)},
                ],
            )

            text = _extract_text(response)
            claims_raw = _parse_unsupported_claims(text)

            if settings.ENABLE_SELF_CRITIQUE:
                v1_dict: dict[str, Any] = {"unsupported_claims": claims_raw}
                source_excerpts = [
                    ref.excerpt for ref in screen.source_refs if ref.excerpt
                ]
                v2_dict = await surgical_review(
                    client,
                    model=settings.SELF_CRITIQUE_MODEL,
                    v1_output=v1_dict,
                    source_excerpts=source_excerpts,
                    schema=_FidelityV1,
                )
                reviewed_claims = v2_dict.get("unsupported_claims", [])
                if not isinstance(reviewed_claims, list):
                    reviewed_claims = []
                claims_raw = [c for c in reviewed_claims if isinstance(c, dict)]

            for claim in claims_raw:
                claim_text = str(claim.get("claim", "")).strip()
                reason_text = str(claim.get("reason", "")).strip()
                if not claim_text and not reason_text:
                    continue
                findings.append(
                    ValidatorFinding(
                        severity="medium",
                        code="narrative_unsupported_claim",
                        screen_id=screen_id,
                        message=f"{claim_text} — {reason_text}",
                    )
                )

    ok = not any(f.severity == "critical" for f in findings)
    return ValidatorResult(
        validator="narrative_fidelity",
        ok=ok,
        findings=findings,
    )
