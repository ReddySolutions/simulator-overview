"""Three-way cross-reference contradiction detection across video, audio, and PDF.

Independently compares video-observed UI elements, audio narration, and PDF
documentation to surface label mismatches, step count disagreements, control
type conflicts, policy gaps, and cross-video behavioral conflicts. Every gap
includes evidence from at least two sources (M2) and is classified by severity
(M3). No source is treated as authoritative (N4).
"""

from __future__ import annotations

import hashlib
from typing import Literal

from walkthrough.models.pdf import PDFExtraction
from walkthrough.models.project import Gap
from walkthrough.models.video import AudioSegment, VideoAnalysis
from walkthrough.models.workflow import DecisionTree, SourceRef


def _gap_id(description: str) -> str:
    """Derive a stable gap_id from the description hash."""
    digest = hashlib.sha256(description.encode()).hexdigest()[:10]
    return f"gap_{digest}"


def _format_timestamp(seconds: float) -> str:
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Source extraction helpers
# ---------------------------------------------------------------------------


def _collect_video_labels(
    videos: list[VideoAnalysis],
) -> dict[str, list[SourceRef]]:
    """Collect all UI element labels from video keyframes with source refs.

    Returns a mapping of normalized label -> list of SourceRefs.
    """
    labels: dict[str, list[SourceRef]] = {}
    for va in videos:
        for kf in va.keyframes:
            ts = _format_timestamp(kf.timestamp_sec)
            for el in kf.ui_elements:
                key = el.label.strip().lower()
                if not key:
                    continue
                ref = SourceRef(
                    source_type="video",
                    reference=f"{va.filename}:{ts}",
                    excerpt=f"UI element '{el.label}' ({el.element_type})",
                )
                labels.setdefault(key, []).append(ref)
    return labels


def _collect_video_element_types(
    videos: list[VideoAnalysis],
) -> dict[str, list[tuple[str, SourceRef]]]:
    """Collect UI element types keyed by normalized label.

    Returns label -> list of (element_type, SourceRef).
    """
    types: dict[str, list[tuple[str, SourceRef]]] = {}
    for va in videos:
        for kf in va.keyframes:
            ts = _format_timestamp(kf.timestamp_sec)
            for el in kf.ui_elements:
                key = el.label.strip().lower()
                if not key:
                    continue
                ref = SourceRef(
                    source_type="video",
                    reference=f"{va.filename}:{ts}",
                    excerpt=f"Shown as '{el.element_type}' with label '{el.label}'",
                )
                types.setdefault(key, []).append((el.element_type, ref))
    return types


def _collect_pdf_labels(
    pdfs: list[PDFExtraction],
) -> dict[str, list[SourceRef]]:
    """Collect UI element labels mentioned in PDF text and images."""
    labels: dict[str, list[SourceRef]] = {}

    for pdf in pdfs:
        # From PDF images with analyzed UI elements
        for img in pdf.images:
            if not img.ui_elements:
                continue
            for el in img.ui_elements:
                key = el.label.strip().lower()
                if not key:
                    continue
                ref = SourceRef(
                    source_type="pdf",
                    reference=f"{pdf.filename}:page {img.page_number}",
                    excerpt=f"UI element '{el.label}' ({el.element_type}) in screenshot",
                )
                labels.setdefault(key, []).append(ref)

        # From PDF section text — look for quoted UI labels
        for section in pdf.sections:
            ref = SourceRef(
                source_type="pdf",
                reference=f"{pdf.filename}:Section '{section.heading}'",
                excerpt=section.text[:200],
            )
            # Store the section text for label cross-referencing
            words = section.text.strip().lower()
            if words:
                labels.setdefault(f"__section__{section.heading.lower()}", []).append(ref)

    return labels


def _collect_pdf_element_types(
    pdfs: list[PDFExtraction],
) -> dict[str, list[tuple[str, SourceRef]]]:
    """Collect element types from PDF images keyed by normalized label."""
    types: dict[str, list[tuple[str, SourceRef]]] = {}
    for pdf in pdfs:
        for img in pdf.images:
            if not img.ui_elements:
                continue
            for el in img.ui_elements:
                key = el.label.strip().lower()
                if not key:
                    continue
                ref = SourceRef(
                    source_type="pdf",
                    reference=f"{pdf.filename}:page {img.page_number}",
                    excerpt=f"Shown as '{el.element_type}' with label '{el.label}'",
                )
                types.setdefault(key, []).append((el.element_type, ref))
    return types


def _collect_audio_mentions(
    videos: list[VideoAnalysis],
) -> list[tuple[str, AudioSegment, str]]:
    """Collect audio segments with their video filename.

    Returns list of (filename, AudioSegment, normalized_text).
    """
    mentions: list[tuple[str, AudioSegment, str]] = []
    for va in videos:
        for seg in va.audio_segments:
            text = seg.text.strip().lower()
            if text:
                mentions.append((va.filename, seg, text))
    return mentions


def _audio_ref(filename: str, seg: AudioSegment) -> SourceRef:
    ts = _format_timestamp(seg.start_sec)
    return SourceRef(
        source_type="audio",
        reference=f"{filename}:{ts}",
        excerpt=seg.text[:200],
    )


# ---------------------------------------------------------------------------
# Contradiction detection checks
# ---------------------------------------------------------------------------


def _detect_label_mismatches(
    video_labels: dict[str, list[SourceRef]],
    pdf_labels: dict[str, list[SourceRef]],
) -> list[Gap]:
    """Detect UI element labels in video that are not found in PDF, and vice versa."""
    gaps: list[Gap] = []

    # Get actual UI labels from PDFs (exclude section markers)
    pdf_ui_labels = {
        k: v for k, v in pdf_labels.items() if not k.startswith("__section__")
    }

    # Video labels not in PDF
    for label, v_refs in video_labels.items():
        if label not in pdf_ui_labels:
            # Check if the label is mentioned in any PDF section text
            mentioned_in_pdf = False
            pdf_evidence: list[SourceRef] = []
            for sec_key, sec_refs in pdf_labels.items():
                if sec_key.startswith("__section__"):
                    for ref in sec_refs:
                        if ref.excerpt and label in ref.excerpt.lower():
                            mentioned_in_pdf = True
                            pdf_evidence.append(ref)

            if not mentioned_in_pdf and pdf_ui_labels:
                desc = (
                    f"UI element '{v_refs[0].excerpt}' observed in video "
                    f"but not found in PDF documentation"
                )
                evidence = [v_refs[0]]
                # Add a PDF ref showing what IS documented
                if pdf_ui_labels:
                    first_pdf_ref = next(iter(pdf_ui_labels.values()))[0]
                    evidence.append(SourceRef(
                        source_type="pdf",
                        reference=first_pdf_ref.reference,
                        excerpt="Label not present in PDF UI elements",
                    ))
                gaps.append(Gap(
                    gap_id=_gap_id(desc),
                    severity="medium",
                    description=desc,
                    evidence=evidence,
                ))

    # PDF UI labels not in video
    for label, p_refs in pdf_ui_labels.items():
        if label not in video_labels:
            desc = (
                f"UI element '{p_refs[0].excerpt}' documented in PDF "
                f"but not observed in any video"
            )
            evidence = [p_refs[0]]
            if video_labels:
                first_v_ref = next(iter(video_labels.values()))[0]
                evidence.append(SourceRef(
                    source_type="video",
                    reference=first_v_ref.reference,
                    excerpt="Label not observed in video keyframes",
                ))
            gaps.append(Gap(
                gap_id=_gap_id(desc),
                severity="medium",
                description=desc,
                evidence=evidence,
            ))

    return gaps


def _detect_control_type_conflicts(
    video_types: dict[str, list[tuple[str, SourceRef]]],
    pdf_types: dict[str, list[tuple[str, SourceRef]]],
    audio_mentions: list[tuple[str, AudioSegment, str]],
) -> list[Gap]:
    """Detect cases where the same label has different control types across sources."""
    gaps: list[Gap] = []

    # Video vs PDF type conflicts
    for label in set(video_types) & set(pdf_types):
        v_element_types = {t for t, _ in video_types[label]}
        p_element_types = {t for t, _ in pdf_types[label]}

        if v_element_types != p_element_types and not v_element_types & p_element_types:
            v_type_str = ", ".join(sorted(v_element_types))
            p_type_str = ", ".join(sorted(p_element_types))
            desc = (
                f"Control type conflict for '{label}': "
                f"video shows {v_type_str}, PDF shows {p_type_str}"
            )
            evidence = [
                video_types[label][0][1],
                pdf_types[label][0][1],
            ]
            gaps.append(Gap(
                gap_id=_gap_id(desc),
                severity="critical",
                description=desc,
                evidence=evidence,
            ))

    # Audio mentions of control types vs video
    control_type_keywords = {
        "button", "dropdown", "text field", "text box", "input",
        "checkbox", "radio", "tab", "link", "table", "menu",
        "select", "toggle",
    }
    type_aliases: dict[str, str] = {
        "text box": "text_field",
        "input": "text_field",
        "select": "dropdown",
        "menu": "dropdown",
        "toggle": "checkbox",
    }

    for filename, seg, text in audio_mentions:
        for keyword in control_type_keywords:
            if keyword not in text:
                continue
            # Find what label the audio associates with this type
            for label, v_entries in video_types.items():
                if label not in text:
                    continue
                canonical = type_aliases.get(keyword, keyword)
                v_types_for_label = {t for t, _ in v_entries}
                if canonical not in v_types_for_label and keyword not in v_types_for_label:
                    desc = (
                        f"Audio refers to '{label}' as a {keyword}, "
                        f"but video shows it as {', '.join(sorted(v_types_for_label))}"
                    )
                    evidence = [
                        _audio_ref(filename, seg),
                        v_entries[0][1],
                    ]
                    gaps.append(Gap(
                        gap_id=_gap_id(desc),
                        severity="critical",
                        description=desc,
                        evidence=evidence,
                    ))

    return gaps


def _detect_step_count_disagreements(
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
) -> list[Gap]:
    """Detect disagreements in the number of workflow steps between video and PDF."""
    gaps: list[Gap] = []

    total_video_steps = 0
    video_refs: list[SourceRef] = []
    for va in videos:
        step_count = len(va.keyframes)
        total_video_steps += step_count
        video_refs.append(SourceRef(
            source_type="video",
            reference=va.filename,
            excerpt=f"{step_count} keyframe screens extracted",
        ))

    # Count PDF sections that describe procedural steps
    total_pdf_steps = 0
    pdf_refs: list[SourceRef] = []
    for pdf in pdfs:
        step_sections = [
            s for s in pdf.sections
            if _is_procedural_section(s.heading, s.text)
        ]
        count = len(step_sections)
        total_pdf_steps += count
        if count > 0:
            pdf_refs.append(SourceRef(
                source_type="pdf",
                reference=pdf.filename,
                excerpt=f"{count} procedural sections found",
            ))

    # Only flag if both sources have steps and they differ significantly
    if total_video_steps > 0 and total_pdf_steps > 0:
        ratio = max(total_video_steps, total_pdf_steps) / max(
            min(total_video_steps, total_pdf_steps), 1
        )
        if ratio >= 1.5:
            desc = (
                f"Step count disagreement: videos show {total_video_steps} screens "
                f"but PDF documents {total_pdf_steps} procedural steps"
            )
            evidence = []
            if video_refs:
                evidence.append(video_refs[0])
            if pdf_refs:
                evidence.append(pdf_refs[0])
            if len(evidence) >= 2:
                gaps.append(Gap(
                    gap_id=_gap_id(desc),
                    severity="medium",
                    description=desc,
                    evidence=evidence,
                ))

    return gaps


def _is_procedural_section(heading: str, text: str) -> bool:
    """Heuristic: does this PDF section describe a procedural step?"""
    heading_lower = heading.lower()
    text_lower = text.lower()

    step_indicators = [
        "step", "click", "select", "enter", "navigate", "open",
        "press", "choose", "verify", "confirm", "submit",
    ]
    return any(word in heading_lower or word in text_lower[:100] for word in step_indicators)


def _detect_policy_gaps(
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
) -> list[Gap]:
    """Detect policies or exceptions mentioned in audio but absent from PDF."""
    gaps: list[Gap] = []

    policy_keywords = [
        "exception", "policy", "rule", "must", "never", "always",
        "required", "mandatory", "prohibited", "if the customer",
        "in case of", "when the", "make sure", "do not", "escalate",
    ]

    # Collect all PDF text for checking
    pdf_text_corpus = ""
    pdf_corpus_refs: list[SourceRef] = []
    for pdf in pdfs:
        for section in pdf.sections:
            pdf_text_corpus += " " + section.text.lower()
            if not pdf_corpus_refs:
                pdf_corpus_refs.append(SourceRef(
                    source_type="pdf",
                    reference=f"{pdf.filename}:Section '{section.heading}'",
                    excerpt=section.text[:200],
                ))

    if not pdf_text_corpus.strip():
        return gaps

    for va in videos:
        for seg in va.audio_segments:
            text_lower = seg.text.strip().lower()
            for keyword in policy_keywords:
                if keyword not in text_lower:
                    continue
                # Extract the sentence containing the keyword
                sentence = _extract_sentence(seg.text, keyword)
                if not sentence:
                    continue

                # Check if the core policy content appears in PDF
                policy_words = set(sentence.lower().split()) - {
                    "the", "a", "an", "is", "are", "to", "and", "or",
                    "of", "in", "on", "it", "that", "this", "for",
                }
                match_count = sum(
                    1 for w in policy_words if w in pdf_text_corpus
                )
                coverage = match_count / max(len(policy_words), 1)

                if coverage < 0.4:
                    desc = (
                        f"Policy mentioned in audio not found in PDF: "
                        f"'{sentence[:120]}'"
                    )
                    evidence = [
                        _audio_ref(va.filename, seg),
                    ]
                    if pdf_corpus_refs:
                        evidence.append(SourceRef(
                            source_type="pdf",
                            reference=pdf_corpus_refs[0].reference,
                            excerpt="Policy not found in PDF documentation",
                        ))
                    if len(evidence) >= 2:
                        gaps.append(Gap(
                            gap_id=_gap_id(desc),
                            severity="medium",
                            description=desc,
                            evidence=evidence,
                        ))
                break  # One policy keyword match per segment is enough

    return gaps


def _extract_sentence(text: str, keyword: str) -> str | None:
    """Extract the sentence from text that contains the keyword."""
    lower = text.lower()
    idx = lower.find(keyword)
    if idx == -1:
        return None

    # Find sentence boundaries
    start = max(0, text.rfind(".", 0, idx) + 1)
    end = text.find(".", idx)
    if end == -1:
        end = len(text)
    else:
        end += 1

    sentence = text[start:end].strip()
    return sentence if sentence else None


def _detect_cross_video_conflicts(
    videos: list[VideoAnalysis],
    decision_trees: list[DecisionTree],
) -> list[Gap]:
    """Detect behavioral conflicts between different videos showing the same screens."""
    gaps: list[Gap] = []

    if len(videos) < 2:
        return gaps

    for tree in decision_trees:
        for screen_id, screen in tree.screens.items():
            # Only check screens observed in multiple videos
            video_refs = [
                r for r in screen.source_refs if r.source_type == "video"
            ]
            if len(video_refs) < 2:
                continue

            # Check if the same screen leads to different outcomes in the tree
            branches_from_screen = [
                b for b in tree.branches if b.screen_id == screen_id
            ]
            for branch in branches_from_screen:
                if len(branch.paths) > 1:
                    paths_desc = ", ".join(
                        f"'{action}' -> {target}"
                        for action, target in branch.paths.items()
                    )
                    desc = (
                        f"Cross-video conflict at screen '{screen.title}': "
                        f"different videos show different paths: {paths_desc}"
                    )
                    evidence = video_refs[:2]
                    gaps.append(Gap(
                        gap_id=_gap_id(desc),
                        severity="critical",
                        description=desc,
                        evidence=evidence,
                    ))

    return gaps


def _detect_audio_video_narration_mismatch(
    videos: list[VideoAnalysis],
) -> list[Gap]:
    """Detect mismatches between what audio describes and what video shows."""
    gaps: list[Gap] = []

    for va in videos:
        for seg in va.audio_segments:
            text_lower = seg.text.strip().lower()
            if not text_lower:
                continue

            # Find keyframes that overlap with this audio segment's timeframe
            overlapping_keyframes = [
                kf for kf in va.keyframes
                if kf.timestamp_sec >= seg.start_sec - 2.0
                and kf.timestamp_sec <= seg.end_sec + 2.0
            ]

            if not overlapping_keyframes:
                continue

            # Collect all video UI labels visible during this audio segment
            visible_labels = set()
            for kf in overlapping_keyframes:
                for el in kf.ui_elements:
                    visible_labels.add(el.label.strip().lower())

            # Check if audio mentions clicking/selecting something not visible
            action_verbs = ["click", "select", "press", "choose", "tap"]
            for verb in action_verbs:
                if verb not in text_lower:
                    continue
                # Extract what follows the verb
                idx = text_lower.find(verb)
                after_verb = text_lower[idx + len(verb):idx + len(verb) + 50]
                mentioned_labels = [
                    lbl for lbl in visible_labels if lbl in after_verb
                ]
                if not mentioned_labels:
                    # Audio says to act on something, but it may reference
                    # a label that doesn't match anything visible
                    words_after = after_verb.strip().split()[:5]
                    target = " ".join(words_after).strip(" .,;:'\"")
                    if target and len(target) > 3:
                        # Check if this target is not among visible labels
                        if not any(target in lbl or lbl in target for lbl in visible_labels):
                            desc = (
                                f"Audio narration mentions '{verb} {target}' "
                                f"but no matching UI element visible in video "
                                f"at that timestamp"
                            )
                            ts = _format_timestamp(seg.start_sec)
                            evidence = [
                                _audio_ref(va.filename, seg),
                                SourceRef(
                                    source_type="video",
                                    reference=f"{va.filename}:{ts}",
                                    excerpt=(
                                        f"Visible elements: "
                                        f"{', '.join(sorted(visible_labels)[:5])}"
                                    ),
                                ),
                            ]
                            gaps.append(Gap(
                                gap_id=_gap_id(desc),
                                severity="low",
                                description=desc,
                                evidence=evidence,
                            ))

    return gaps


def _classify_severity(gap: Gap) -> Literal["critical", "medium", "low"]:
    """Re-classify gap severity based on content analysis (M3).

    Critical: ambiguous routing, conflicting procedures, control type conflicts.
    Medium: unclear labels, wording differences, step count disagreements.
    Low: cosmetic differences.
    """
    desc_lower = gap.description.lower()
    critical_signals = [
        "control type conflict",
        "cross-video conflict",
        "conflicting",
        "ambiguous routing",
        "different paths",
    ]
    if any(signal in desc_lower for signal in critical_signals):
        return "critical"

    medium_signals = [
        "not found in pdf",
        "not observed in",
        "step count",
        "policy mentioned",
        "label mismatch",
    ]
    if any(signal in desc_lower for signal in medium_signals):
        return "medium"

    return "low"


def _deduplicate_gaps(gaps: list[Gap]) -> list[Gap]:
    """Remove duplicate gaps based on gap_id."""
    seen: set[str] = set()
    unique: list[Gap] = []
    for gap in gaps:
        if gap.gap_id not in seen:
            seen.add(gap.gap_id)
            unique.append(gap)
    return unique


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def detect_contradictions(
    videos: list[VideoAnalysis],
    pdfs: list[PDFExtraction],
    decision_trees: list[DecisionTree],
) -> list[Gap]:
    """Perform three-way cross-reference across video, audio, and PDF sources.

    Independently compares all three source types (M1) and returns gaps
    classified by severity (M3) with evidence from at least two sources (M2).
    No source is treated as authoritative (N4).

    Checks performed:
    - Label mismatches: video UI labels vs PDF UI labels
    - Control type conflicts: same label, different element types
    - Step count disagreements: video keyframe count vs PDF procedural steps
    - Policy gaps: audio-mentioned policies absent from PDF
    - Cross-video behavioral conflicts: same screen, different outcomes
    - Audio-video narration mismatches: audio describes action on invisible element
    """
    # Extract structured data from each source type
    video_labels = _collect_video_labels(videos)
    video_types = _collect_video_element_types(videos)
    pdf_labels = _collect_pdf_labels(pdfs)
    pdf_types = _collect_pdf_element_types(pdfs)
    audio_mentions = _collect_audio_mentions(videos)

    # Run all contradiction checks
    all_gaps: list[Gap] = []
    all_gaps.extend(
        _detect_label_mismatches(video_labels, pdf_labels)
    )
    all_gaps.extend(
        _detect_control_type_conflicts(video_types, pdf_types, audio_mentions)
    )
    all_gaps.extend(
        _detect_step_count_disagreements(videos, pdfs)
    )
    all_gaps.extend(
        _detect_policy_gaps(videos, pdfs)
    )
    all_gaps.extend(
        _detect_cross_video_conflicts(videos, decision_trees)
    )
    all_gaps.extend(
        _detect_audio_video_narration_mismatch(videos)
    )

    # Re-classify severity based on content (M3)
    for gap in all_gaps:
        gap.severity = _classify_severity(gap)

    # Deduplicate and sort by severity
    all_gaps = _deduplicate_gaps(all_gaps)
    severity_order = {"critical": 0, "medium": 1, "low": 2}
    all_gaps.sort(key=lambda g: severity_order.get(g.severity, 3))

    return all_gaps
