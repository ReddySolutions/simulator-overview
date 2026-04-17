"""Consolidator tool — collapse many detail-level gaps into a few meta-questions.

A typical project produces 50-100 clarification questions. Many of those
questions trace back to the same root cause: the client never recorded a
video of some flow, the PDF is missing a section, etc. The consolidator
asks an LLM to read all the detected gaps, cluster them by likely root
cause, and emit 3-8 *meta-questions* — umbrella questions whose answers
would resolve many individual gaps at once.

Meta-questions are the "what can we ask the client to minimize the
questions they need to answer" layer on top of the per-gap clarification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from walkthrough.config import Settings
from walkthrough.models.project import Choice, Gap, MetaQuestion
from walkthrough.models.pdf import PDFExtraction
from walkthrough.models.video import VideoAnalysis

logger = logging.getLogger(__name__)

MAX_GAPS_SENT = 120  # hard cap so the prompt stays within token limits
MAX_META_QUESTIONS = 8
MIN_GAPS_TO_CONSOLIDATE = 10  # below this, per-gap questions are manageable

CONSOLIDATOR_PROMPT = """\
You are the Consolidator agent for a call-center SOP-to-Simulation pipeline.
The pipeline produced a list of {gap_count} clarification gaps it wants to
ask the user. That list is too long. Your job: identify the smallest set of
*meta-questions* (3-8) whose answers would resolve as many individual gaps
as possible.

Most meta-questions fall into one of three shapes:
1. **Missing input** — "We have no video of the [flow] — can you record one?"
2. **Missing document section** — "Your PDF has no section on [topic] — \
can you provide one?"
3. **Single decision** — "You have many similar label mismatches between \
video and PDF. Should we always prefer the [video/PDF] label?"

Known source materials:
{sources}

Gaps to consolidate (each has id, severity, description):
{gaps}

Return ONLY valid JSON with this schema:
{{
  "meta_questions": [
    {{
      "text": "<the umbrella question as you'd ask the client>",
      "rationale": "<1-2 sentences on why answering this unlocks many gaps>",
      "affected_gap_ids": ["<gap_id>", "..."],
      "choices": [
        {{"label": "<short option>", "description": "<optional 1-line elaboration>"}}
      ]
    }}
  ]
}}

IMPORTANT RULES:
- Emit at most {max_meta} meta-questions. Fewer is better if coverage is high.
- Every affected_gap_id MUST appear in the Gaps list above. Do not invent ids.
- Prefer meta-questions that cover >=5 gaps each; a meta-question covering \
only 1-2 gaps is not worth asking separately.
- If the gap list is small or heterogeneous, return an empty meta_questions \
array — don't force umbrella questions where they don't exist.
- Include `choices` (2-4 options) when the question has a clean discrete \
answer space. Examples:
  * Missing-input questions → ["Yes, I can provide", "No, leave unanswerable", \
"The flow doesn't exist in practice"]
  * Source-preference questions → ["Always prefer video", "Always prefer PDF", \
"Case by case"]
  * PDF-coverage questions → ["PDF covers every screen", "PDF is a summary only"]
- Omit `choices` or return an empty array when the answer is genuinely \
open-ended (e.g. "describe the exception process").
- No markdown fencing. No commentary. JSON only.\
"""


async def consolidate_gaps(
    gaps: list[Gap],
    videos: list[VideoAnalysis] | None = None,
    pdfs: list[PDFExtraction] | None = None,
) -> list[MetaQuestion]:
    """Ask an LLM to emit meta-questions that cover many gaps.

    Returns an empty list below MIN_GAPS_TO_CONSOLIDATE, on LLM error, or
    when the model declines to group the gaps (heterogeneous set). Never
    raises — a broken consolidator must not block the clarification phase.
    """
    if len(gaps) < MIN_GAPS_TO_CONSOLIDATE:
        logger.info(
            "Consolidator skipped: %d gaps below threshold (%d)",
            len(gaps), MIN_GAPS_TO_CONSOLIDATE,
        )
        return []

    settings = Settings()
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; consolidator disabled")
        return []

    trimmed = gaps[:MAX_GAPS_SENT]
    prompt = CONSOLIDATOR_PROMPT.format(
        gap_count=len(trimmed),
        max_meta=MAX_META_QUESTIONS,
        sources=_format_sources(videos or [], pdfs or []),
        gaps=_format_gaps(trimmed),
    )

    try:
        raw = await _call_gemini(api_key, settings.GEMINI_MODEL, prompt)
    except Exception:
        logger.exception("Consolidator LLM call failed; returning empty")
        return []

    return _parse_meta_questions(raw, {g.gap_id for g in gaps})


def _format_sources(
    videos: list[VideoAnalysis], pdfs: list[PDFExtraction],
) -> str:
    lines: list[str] = []
    for v in videos:
        lines.append(f"- VIDEO: {v.filename} ({len(v.keyframes)} keyframes)")
    for p in pdfs:
        lines.append(f"- PDF: {p.filename} ({len(p.sections)} sections)")
    return "\n".join(lines) if lines else "(no source metadata)"


def _format_gaps(gaps: list[Gap]) -> str:
    return "\n".join(
        f"- id={g.gap_id} severity={g.severity} :: {g.description}"
        for g in gaps
    )


async def _call_gemini(api_key: str, model: str, prompt: str) -> str:
    """Run a single-turn Gemini text-only call; small + deterministic."""
    from google import genai
    from google.genai.types import GenerateContentConfig, Part

    client = genai.Client(api_key=api_key)
    config = GenerateContentConfig(temperature=0.2)

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=[Part.from_text(text=prompt)],
        config=config,
    )
    text = response.text or ""
    if not text.strip():
        raise ValueError("Consolidator LLM returned empty response")
    return text


def _parse_meta_questions(
    raw: str, valid_gap_ids: set[str],
) -> list[MetaQuestion]:
    """Parse the LLM response, discarding unknown gap_ids and empty entries."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Consolidator returned non-JSON; discarding: %s", text[:200])
        return []

    entries: list[dict[str, Any]] = data.get("meta_questions", []) if isinstance(data, dict) else []
    out: list[MetaQuestion] = []
    for entry in entries[:MAX_META_QUESTIONS]:
        text_field = (entry.get("text") or "").strip()
        rationale = (entry.get("rationale") or "").strip()
        if not text_field:
            continue

        affected = [
            gid
            for gid in entry.get("affected_gap_ids", [])
            if isinstance(gid, str) and gid in valid_gap_ids
        ]
        if not affected:
            # Meta-question that covers nothing real isn't useful.
            continue

        raw_choices = entry.get("choices") or []
        choices: list[Choice] = []
        for c in raw_choices[:4]:
            if not isinstance(c, dict):
                continue
            label = (c.get("label") or "").strip()
            if not label:
                continue
            desc = c.get("description")
            choices.append(
                Choice(label=label, description=desc.strip() if isinstance(desc, str) else None),
            )

        out.append(
            MetaQuestion(
                meta_question_id=_meta_id(text_field),
                text=text_field,
                rationale=rationale,
                affected_gap_ids=affected,
                choices=choices,
            )
        )
    return out


def _meta_id(text: str) -> str:
    return f"mq_{hashlib.sha256(text.encode()).hexdigest()[:10]}"
