"""Clarification tool — generates batched questions from detected gaps with evidence.

Produces ClarificationQuestion objects ordered by severity (critical first, M4),
with evidence from relevant sources (M2, M7). Contradictions are presented with
both versions for the user to adjudicate (N2). The clarification phase always
runs, even with zero contradictions (N7). Unanswerable critical gaps produce
warning metadata for affected screens (N3).
"""

from __future__ import annotations

import hashlib

from walkthrough.models.project import ClarificationQuestion, Gap
from walkthrough.models.workflow import SourceRef


def _question_id(description: str) -> str:
    """Derive a stable question_id from the gap description hash."""
    digest = hashlib.sha256(description.encode()).hexdigest()[:10]
    return f"q_{digest}"


def _build_question_text(gap: Gap) -> str:
    """Build a clear question from a gap, presenting both sides for contradictions (N2)."""
    desc = gap.description

    # Group evidence by source type for presentation
    sources_by_type: dict[str, list[SourceRef]] = {}
    for ref in gap.evidence:
        sources_by_type.setdefault(ref.source_type, []).append(ref)

    # For contradictions (evidence from 2+ source types), present both versions
    if len(sources_by_type) >= 2:
        versions: list[str] = []
        for source_type, refs in sources_by_type.items():
            excerpt = refs[0].excerpt or refs[0].reference
            versions.append(f"- {source_type.capitalize()} shows: {excerpt}")
        versions_text = "\n".join(versions)
        return (
            f"{desc}\n\n"
            f"The following sources disagree:\n{versions_text}\n\n"
            f"Which version is correct, or how should this be resolved?"
        )

    return f"{desc}\n\nPlease clarify how this should be handled."


def _gap_to_question(gap: Gap) -> ClarificationQuestion:
    """Convert a single Gap into a ClarificationQuestion with evidence."""
    return ClarificationQuestion(
        question_id=_question_id(gap.gap_id),
        text=_build_question_text(gap),
        severity=gap.severity,
        evidence=list(gap.evidence),
    )


async def generate_questions(
    gaps: list[Gap],
) -> list[ClarificationQuestion]:
    """Generate batched clarification questions from detected gaps.

    Questions are ordered by severity — critical first (M4). Each question
    includes evidence from relevant sources with SourceRef citations (M2, M7).
    Contradictions are presented with both versions for user adjudication (N2).

    If no gaps exist, returns a single confirmation question to satisfy N7
    (clarification phase always runs).

    Args:
        gaps: List of gaps from detect_contradictions.

    Returns:
        List of ClarificationQuestion sorted by severity (critical first).
    """
    # N7: clarification phase always runs, even with zero contradictions
    if not gaps:
        return [
            ClarificationQuestion(
                question_id=_question_id("no_gaps_confirmation"),
                text=(
                    "No contradictions were detected between the video, audio, "
                    "and PDF sources. The extracted workflow appears consistent "
                    "across all inputs.\n\n"
                    "Please confirm that the analysis looks correct, or note "
                    "any issues you've noticed that the automated checks may "
                    "have missed."
                ),
                severity="low",
                evidence=[],
            )
        ]

    # Convert gaps to questions, skipping already-resolved gaps
    questions: list[ClarificationQuestion] = []
    for gap in gaps:
        if gap.resolved:
            continue
        questions.append(_gap_to_question(gap))

    # Sort by severity: critical first (M4)
    severity_order = {"critical": 0, "medium": 1, "low": 2}
    questions.sort(key=lambda q: severity_order.get(q.severity, 3))

    return questions


async def apply_answer(
    question_id: str,
    answer: str,
    gaps: list[Gap],
) -> list[Gap]:
    """Process a user's answer to a clarification question.

    Finds the gap corresponding to the question and marks it as resolved
    with the user's answer as the resolution. If the answer indicates the
    question is unanswerable, marks the gap accordingly — unanswerable
    critical gaps retain resolved=False so they produce warning metadata
    on affected screens (N3).

    Args:
        question_id: The question_id being answered.
        answer: The user's answer text.
        gaps: Current list of gaps to update.

    Returns:
        Updated list of gaps with the answered gap marked resolved.
    """
    for gap in gaps:
        derived_qid = _question_id(gap.gap_id)
        if derived_qid != question_id:
            continue

        gap.resolution = answer
        gap.resolved = True
        break

    return gaps


async def mark_unanswerable(
    question_id: str,
    gaps: list[Gap],
) -> list[Gap]:
    """Mark a clarification question as unanswerable.

    For critical gaps, the gap stays unresolved (resolved=False) so that
    downstream generation (N3) places warning metadata on affected screens.
    For medium/low gaps, the gap is marked resolved with an unanswerable note.

    Args:
        question_id: The question_id being marked unanswerable.
        gaps: Current list of gaps to update.

    Returns:
        Updated list of gaps.
    """
    for gap in gaps:
        derived_qid = _question_id(gap.gap_id)
        if derived_qid != question_id:
            continue

        gap.resolution = "Marked unanswerable by user"

        if gap.severity == "critical":
            # N3: critical gaps stay unresolved — warning metadata on screens
            gap.resolved = False
        else:
            gap.resolved = True
        break

    return gaps
