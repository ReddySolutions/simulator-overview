"""Contradiction-detector LLM critic (additive, flag-gated).

Reads the raw source materials plus the deterministic detector's existing
gaps and asks an LLM for *additional* contradictions the heuristics may
have missed. Output is filtered against ``existing_gaps`` via
``_deduplicate_gaps`` (imported from the deterministic module) so the
orchestrator only receives genuinely new findings.

Gated by ``Settings().QA_ENABLE_LLM_CRITIC`` — when False this is a no-op
that makes zero HTTP calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from pydantic import BaseModel

from walkthrough.ai.llm.client import run_structured_json
from walkthrough.ai.llm.review_pass import surgical_review
from walkthrough.ai.prompts.compose import compose_system_prompt
from walkthrough.ai.prompts.fidelity import (
    AUTHORITY_HIERARCHY,
    EVIDENCE_CITATION_RULES,
    FIDELITY_STANDARD,
    INVARIANTS,
)
from walkthrough.ai.tools.detect_contradictions import _deduplicate_gaps
from walkthrough.config import Settings
from walkthrough.models.pdf import PDFExtraction
from walkthrough.models.project import Gap
from walkthrough.models.video import VideoAnalysis
from walkthrough.models.workflow import DecisionTree

logger = logging.getLogger(__name__)

TASK_PROMPT = (
    "Compare UI labels across videos, PDF sections, and audio excerpts. "
    "Identify contradictions the deterministic detector may have missed. "
    "Do NOT duplicate items already present in `existing_gaps`. "
    'Output JSON: {"gaps": [{"gap_id": str, "severity": '
    '"critical|medium|low", "description": str, "evidence": '
    "[SourceRef-like dicts from >=2 sources]}]}"
)


class LLMGapsResponse(BaseModel):
    gaps: list[Gap]


def _format_timestamp(seconds: float) -> str:
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


def _source_excerpts(
    videos: list[VideoAnalysis], pdfs: list[PDFExtraction]
) -> list[str]:
    """Flatten audio segments + PDF section text into a list of prose excerpts."""
    excerpts: list[str] = []
    for va in videos:
        for seg in va.audio_segments:
            excerpts.append(seg.text[:200])
    for pdf in pdfs:
        for s in pdf.sections:
            excerpts.append(s.text[:200])
    return excerpts


def _build_payload(
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
    decision_trees: list[DecisionTree],
    existing_gaps: list[Gap],
) -> dict[str, Any]:
    """Compact JSON payload for the critic's user message."""
    video_blocks: list[dict[str, Any]] = []
    for va in videos:
        keyframes = [
            {
                "t": _format_timestamp(kf.timestamp_sec),
                "labels": [
                    {"label": el.label, "type": el.element_type}
                    for el in kf.ui_elements
                ],
            }
            for kf in va.keyframes
        ]
        audio = [
            {
                "t": _format_timestamp(seg.start_sec),
                "text": seg.text[:200],
            }
            for seg in va.audio_segments
        ]
        video_blocks.append(
            {
                "filename": va.filename,
                "keyframes": keyframes,
                "audio": audio,
            }
        )

    pdf_blocks: list[dict[str, Any]] = []
    for pdf in pdfs:
        sections = [
            {"heading": s.heading, "excerpt": s.text[:200]}
            for s in pdf.sections
        ]
        pdf_blocks.append({"filename": pdf.filename, "sections": sections})

    tree_blocks: list[dict[str, Any]] = []
    for tree in decision_trees:
        tree_blocks.append(
            {
                "root_screen_id": tree.root_screen_id,
                "screen_titles": {
                    sid: s.title for sid, s in tree.screens.items()
                },
            }
        )

    existing = [
        {
            "gap_id": g.gap_id,
            "severity": g.severity,
            "description": g.description,
        }
        for g in existing_gaps
    ]

    return {
        "videos": video_blocks,
        "pdfs": pdf_blocks,
        "decision_trees": tree_blocks,
        "existing_gaps": existing,
    }


async def critique_contradictions(
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
    decision_trees: list[DecisionTree],
    existing_gaps: list[Gap],
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> list[Gap]:
    """Return gaps the LLM critic found beyond the deterministic set.

    Returns an empty list when ``Settings().QA_ENABLE_LLM_CRITIC`` is False
    (no HTTP calls). Duplicates (by ``gap_id``) against ``existing_gaps``
    are filtered out before returning.
    """
    settings = Settings()
    if not settings.QA_ENABLE_LLM_CRITIC:
        return []

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    system = compose_system_prompt(
        FIDELITY_STANDARD,
        INVARIANTS,
        AUTHORITY_HIERARCHY,
        EVIDENCE_CITATION_RULES,
        task=TASK_PROMPT,
    )
    payload = _build_payload(videos, pdfs, decision_trees, existing_gaps)

    try:
        response = await run_structured_json(
            client,
            model=settings.CONTRADICTION_CRITIC_MODEL,
            system=system,
            user=json.dumps(payload),
            schema=LLMGapsResponse,
        )
    except ValueError:
        logger.warning(
            "contradictions_critic: LLM call failed schema validation; "
            "returning no additions"
        )
        return []

    if settings.ENABLE_SELF_CRITIQUE:
        source_excerpts = _source_excerpts(videos, pdfs)
        v1_dict = response.model_dump(mode="json")
        v2_dict = await surgical_review(
            client,
            model=settings.SELF_CRITIQUE_MODEL,
            v1_output=v1_dict,
            source_excerpts=source_excerpts,
            schema=LLMGapsResponse,
        )
        response = LLMGapsResponse.model_validate(v2_dict)

    combined = _deduplicate_gaps(existing_gaps + response.gaps)
    existing_ids = {g.gap_id for g in existing_gaps}
    return [g for g in combined if g.gap_id not in existing_ids]
