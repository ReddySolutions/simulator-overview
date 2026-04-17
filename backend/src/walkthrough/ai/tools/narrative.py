"""Narrative synthesis — merges audio transcripts with PDF text into per-step what/why/when.

For each WorkflowScreen in the decision trees, produces a Narrative with:
- what: the observed action from the video keyframe
- why: rationale from audio transcript (primary) + PDF policy (supplementary)
- when_condition: branch condition from the decision tree logic

Every narrative field includes inline source citations (M7). Audio transcripts
are primary for 'why'; PDF text is supplementary context. Implements Phase 4
of the pipeline.
"""

from __future__ import annotations

import re

from walkthrough.models.pdf import PDFExtraction
from walkthrough.models.video import AudioSegment, VideoAnalysis
from walkthrough.models.workflow import (
    BranchPoint,
    DecisionTree,
    Narrative,
    SourceRef,
    WorkflowScreen,
)


def _format_timestamp(seconds: float) -> str:
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


def _parse_timestamp_from_ref(reference: str) -> float | None:
    """Extract timestamp in seconds from a SourceRef reference like 'file.mp4:01:23'."""
    match = re.search(r":(\d{2}):(\d{2})$", reference)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    return None


def _find_overlapping_audio(
    timestamp_sec: float,
    video: VideoAnalysis,
    tolerance: float = 5.0,
) -> list[tuple[AudioSegment, str]]:
    """Find audio segments overlapping a given timestamp within tolerance.

    Returns list of (AudioSegment, filename) pairs ordered by proximity.
    """
    matches: list[tuple[float, AudioSegment]] = []
    for seg in video.audio_segments:
        if seg.start_sec - tolerance <= timestamp_sec <= seg.end_sec + tolerance:
            distance = abs((seg.start_sec + seg.end_sec) / 2 - timestamp_sec)
            matches.append((distance, seg))

    matches.sort(key=lambda x: x[0])
    return [(seg, video.filename) for _, seg in matches]


def _find_relevant_pdf_sections(
    screen: WorkflowScreen,
    pdfs: list[PDFExtraction],
) -> list[tuple[str, str]]:
    """Find PDF sections relevant to a screen's UI elements or title.

    Returns list of (excerpt, reference) tuples.
    """
    screen_labels = {
        el.label.strip().lower()
        for el in screen.ui_elements
        if el.label.strip()
    }
    title_words = set(screen.title.strip().lower().split())

    results: list[tuple[float, str, str]] = []
    for pdf in pdfs:
        for section in pdf.sections:
            section_lower = section.text.strip().lower()

            # Score by label overlap
            label_hits = sum(1 for lbl in screen_labels if lbl in section_lower)
            # Score by title word overlap
            title_hits = sum(1 for w in title_words if len(w) > 3 and w in section_lower)

            score = label_hits * 2 + title_hits
            if score > 0:
                ref = f"{pdf.filename}:Section '{section.heading}'"
                excerpt = section.text[:200].strip()
                results.append((score, excerpt, ref))

    results.sort(key=lambda x: -x[0])
    return [(excerpt, ref) for _, excerpt, ref in results[:3]]


def _build_what(
    screen: WorkflowScreen,
) -> str:
    """Build the 'what' narrative — observed action from video keyframes."""
    # Find the video source ref to get the timestamp and filename
    video_ref = next(
        (r for r in screen.source_refs if r.source_type == "video"),
        None,
    )

    if video_ref and video_ref.excerpt:
        citation = f" [Source: {video_ref.reference}]"
        return f"{video_ref.excerpt}{citation}"

    # Fallback: describe from UI elements
    element_descriptions = []
    for el in screen.ui_elements[:5]:
        element_descriptions.append(f"{el.element_type} '{el.label}'")

    if element_descriptions:
        elements_str = ", ".join(element_descriptions)
        return f"Screen with {elements_str}"

    return f"Screen: {screen.title}"


def _build_why(
    screen: WorkflowScreen,
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
) -> str:
    """Build the 'why' narrative — rationale from audio (primary) + PDF (supplementary)."""
    parts: list[str] = []

    # Primary: audio transcript segments
    video_ref = next(
        (r for r in screen.source_refs if r.source_type == "video"),
        None,
    )

    if video_ref:
        timestamp = _parse_timestamp_from_ref(video_ref.reference)
        # Find the video that matches this reference
        ref_filename = video_ref.reference.split(":")[0]
        for va in videos:
            if va.filename == ref_filename or (timestamp is not None):
                if timestamp is None:
                    continue
                audio_matches = _find_overlapping_audio(timestamp, va)
                for seg, filename in audio_matches[:2]:
                    ts = _format_timestamp(seg.start_sec)
                    text = seg.text.strip()
                    citation = f"[Audio: {filename} @ {ts}]"
                    if seg.intent:
                        parts.append(f"{text} (Intent: {seg.intent}) {citation}")
                    else:
                        parts.append(f"{text} {citation}")
                if audio_matches:
                    break

    # Supplementary: PDF policy context
    pdf_sections = _find_relevant_pdf_sections(screen, pdfs)
    for excerpt, ref in pdf_sections[:2]:
        # Truncate excerpt for readability
        short_excerpt = excerpt[:150].strip()
        if len(excerpt) > 150:
            short_excerpt += "..."
        citation = f"[PDF: {ref}]"
        parts.append(f"{short_excerpt} {citation}")

    if not parts:
        return "No rationale found in audio transcripts or PDF documentation for this step."

    return " | ".join(parts)


def _build_when_condition(
    screen: WorkflowScreen,
    branches: list[BranchPoint],
    screens: dict[str, WorkflowScreen],
) -> str | None:
    """Build 'when_condition' — the branch condition that leads to this screen.

    Searches the branch list for any branch whose paths include this screen
    as a destination, and returns the condition + action that leads here.
    """
    for branch in branches:
        for action, target_id in branch.paths.items():
            if target_id == screen.screen_id:
                parent = screens.get(branch.screen_id)
                parent_title = parent.title if parent else branch.screen_id
                if len(branch.paths) > 1:
                    return (
                        f"Reached when '{action}' is chosen at "
                        f"'{parent_title}' (branch condition: {branch.condition})"
                    )
                return f"Reached after '{action}' at '{parent_title}'"

    return None


def _add_narrative_source_refs(
    screen: WorkflowScreen,
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
) -> list[SourceRef]:
    """Collect additional SourceRefs for narrative citations not already on the screen."""
    extra_refs: list[SourceRef] = []
    existing = {r.reference for r in screen.source_refs}

    # Add audio refs for overlapping segments
    video_ref = next(
        (r for r in screen.source_refs if r.source_type == "video"),
        None,
    )
    if video_ref:
        timestamp = _parse_timestamp_from_ref(video_ref.reference)
        if timestamp is not None:
            ref_filename = video_ref.reference.split(":")[0]
            for va in videos:
                if va.filename == ref_filename:
                    audio_matches = _find_overlapping_audio(timestamp, va)
                    for seg, filename in audio_matches[:2]:
                        ts = _format_timestamp(seg.start_sec)
                        ref_str = f"{filename}:{ts}"
                        if ref_str not in existing:
                            extra_refs.append(SourceRef(
                                source_type="audio",
                                reference=ref_str,
                                excerpt=seg.text[:200].strip(),
                            ))
                            existing.add(ref_str)
                    break

    # Add PDF refs for relevant sections
    pdf_sections = _find_relevant_pdf_sections(screen, pdfs)
    for excerpt, ref_str in pdf_sections[:2]:
        if ref_str not in existing:
            extra_refs.append(SourceRef(
                source_type="pdf",
                reference=ref_str,
                excerpt=excerpt[:200].strip(),
            ))
            existing.add(ref_str)

    return extra_refs


async def synthesize_narrative(
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
    decision_trees: list[DecisionTree],
) -> list[DecisionTree]:
    """Synthesize narrative for each WorkflowScreen in the decision trees.

    For each screen, produces a Narrative with:
    - what: observed action from video keyframe with citation
    - why: rationale from audio transcripts (primary) + PDF text (supplementary)
    - when_condition: branch condition from the decision tree logic

    Audio transcripts are the primary source for 'why'; PDF text provides
    supplementary policy context. Every field cites sources inline (M7).

    After synthesis, narrative text is available for compression while
    workflow structures (screens, branches, elements) remain intact (M6).

    Args:
        videos: All analyzed videos for the project.
        pdfs: All extracted PDFs for the project.
        decision_trees: Decision trees from merge_paths to annotate.

    Returns:
        Updated decision trees with Narrative populated on each screen.
    """
    updated_trees: list[DecisionTree] = []

    for tree in decision_trees:
        updated_screens: dict[str, WorkflowScreen] = {}

        for screen_id, screen in tree.screens.items():
            # Build narrative components
            what = _build_what(screen)
            why = _build_why(screen, videos, pdfs)
            when_condition = _build_when_condition(
                screen, tree.branches, tree.screens
            )

            narrative = Narrative(
                what=what,
                why=why,
                when_condition=when_condition,
            )

            # Collect additional source refs from narrative sources
            extra_refs = _add_narrative_source_refs(screen, videos, pdfs)

            updated_screens[screen_id] = WorkflowScreen(
                screen_id=screen.screen_id,
                title=screen.title,
                ui_elements=screen.ui_elements,
                narrative=narrative,
                evidence_tier=screen.evidence_tier,
                source_refs=list(screen.source_refs) + extra_refs,
            )

        updated_trees.append(DecisionTree(
            root_screen_id=tree.root_screen_id,
            screens=updated_screens,
            branches=list(tree.branches),
        ))

    return updated_trees
