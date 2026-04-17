"""Best-guess tool — propose an answer for a single clarification question.

Given a question's evidence plus the user's already-answered questions
(used as few-shot context for consistency of voice and preference), ask
Gemini to propose the most likely answer and a brief rationale. The
returned answer is NOT persisted — the UI shows it for the user to
confirm or reject.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from walkthrough.config import Settings
from walkthrough.models.project import ClarificationQuestion

logger = logging.getLogger(__name__)

MAX_PRIOR_ANSWERS = 10

BEST_GUESS_PROMPT = """\
You are assisting a user in clarifying gaps detected by a pipeline that
analyzes call-center training videos and SOP PDFs. Given a single
clarification question, its evidence, and the user's previous answers
in this session, propose the single best answer the user would most
likely give and a brief rationale.

Previously answered questions (for tone/preference consistency):
{prior}

Current question (severity={severity}):
{text}

Evidence:
{evidence}

Available preset choices (if any):
{choices}

Return ONLY valid JSON with this schema:
{{
  "answer": "<the proposed answer as the user would type it>",
  "rationale": "<1-2 sentences on why this is the best guess>"
}}

RULES:
- If preset choices exist and one clearly fits the evidence, return that
  choice's label verbatim as the answer.
- Keep the answer concise — typically 1-10 words unless the question
  genuinely needs more.
- The rationale should reference the evidence and any consistency with
  prior answers.
- No markdown fencing. JSON only.\
"""


@dataclass
class BestGuess:
    answer: str
    rationale: str


async def propose_best_guess(
    question: ClarificationQuestion,
    prior_answers: list[ClarificationQuestion],
) -> BestGuess | None:
    """Ask Gemini to propose an answer + rationale for a single question.

    Returns None when the LLM is unavailable or its response can't be
    parsed — the UI falls back to showing the manual answer flow.
    """
    settings = Settings()
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.info("GEMINI_API_KEY not set; best-guess disabled")
        return None

    prompt = BEST_GUESS_PROMPT.format(
        prior=_format_prior(prior_answers),
        severity=question.severity,
        text=question.text,
        evidence=_format_evidence(question),
        choices=_format_choices(question),
    )

    try:
        raw = await _call_gemini(api_key, settings.GEMINI_MODEL, prompt)
    except Exception:
        logger.exception("Best-guess LLM call failed")
        return None

    return _parse_best_guess(raw)


def _format_prior(prior: list[ClarificationQuestion]) -> str:
    # Keep only answered, cap at MAX_PRIOR_ANSWERS to control context size.
    answered = [q for q in prior if q.answer and q.answer != "Marked unanswerable by user"]
    recent = answered[-MAX_PRIOR_ANSWERS:]
    if not recent:
        return "(none yet)"
    return "\n".join(
        f"- Q: {q.text[:120]}... -> A: {q.answer}" for q in recent
    )


def _format_evidence(q: ClarificationQuestion) -> str:
    if not q.evidence:
        return "(no evidence captured)"
    return "\n".join(
        f"- [{ref.source_type}] {ref.reference}"
        + (f" :: {ref.excerpt}" if ref.excerpt else "")
        for ref in q.evidence
    )


def _format_choices(q: ClarificationQuestion) -> str:
    if not q.choices:
        return "(no presets — free-text answer expected)"
    return "\n".join(
        f"- {c.label}" + (f" ({c.description})" if c.description else "")
        for c in q.choices
    )


async def _call_gemini(api_key: str, model: str, prompt: str) -> str:
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
        raise ValueError("Best-guess LLM returned empty response")
    return text


def _parse_best_guess(raw: str) -> BestGuess | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Best-guess returned non-JSON: %s", text[:200])
        return None

    if not isinstance(data, dict):
        return None

    answer = (data.get("answer") or "").strip()
    rationale = (data.get("rationale") or "").strip()
    if not answer:
        return None

    return BestGuess(answer=answer, rationale=rationale)
