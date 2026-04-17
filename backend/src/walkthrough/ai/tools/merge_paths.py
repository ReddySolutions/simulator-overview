"""Merge multiple video analyses into unified decision trees.

Identifies shared screens across videos, detects branch points where
paths diverge, collapses shared prefixes, and produces stable screen IDs
derived from UI element signatures. Implements Phase 3 of the pipeline.
"""

from __future__ import annotations

import hashlib
from typing import Any

from walkthrough.models.video import Keyframe, VideoAnalysis
from walkthrough.models.workflow import (
    BranchPoint,
    DecisionTree,
    SourceRef,
    WorkflowScreen,
)


def _element_signature(keyframe: Keyframe) -> str:
    """Produce a stable signature from a keyframe's UI elements.

    Sorts elements by (element_type, label) to ensure consistent hashing
    regardless of extraction order.
    """
    parts = sorted(
        f"{el.element_type}:{el.label}" for el in keyframe.ui_elements
    )
    return "|".join(parts)


def _screen_id_from_signature(signature: str) -> str:
    """Derive a stable screen_id by hashing the element signature."""
    digest = hashlib.sha256(signature.encode()).hexdigest()[:12]
    return f"screen_{digest}"


def _format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS for human-readable references."""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


def _keyframe_to_source_ref(
    keyframe: Keyframe, filename: str
) -> SourceRef:
    """Build a SourceRef tracing a screen back to its video source."""
    ts = _format_timestamp(keyframe.timestamp_sec)
    return SourceRef(
        source_type="video",
        reference=f"{filename}:{ts}",
        excerpt=keyframe.screenshot_description,
    )


def _keyframe_to_screen(
    keyframe: Keyframe,
    screen_id: str,
    filename: str,
) -> WorkflowScreen:
    """Convert a single keyframe into a WorkflowScreen."""
    return WorkflowScreen(
        screen_id=screen_id,
        title=keyframe.screenshot_description[:80],
        ui_elements=list(keyframe.ui_elements),
        evidence_tier="observed",
        source_refs=[_keyframe_to_source_ref(keyframe, filename)],
    )


# Type alias for a screen entry as extracted from a single video.
_ScreenEntry = dict[str, Any]  # screen_id, keyframe, filename, index


def _extract_screen_sequence(
    analysis: VideoAnalysis,
) -> list[_ScreenEntry]:
    """Build an ordered sequence of screen entries from a VideoAnalysis.

    Each entry carries the derived screen_id, original keyframe,
    source filename, and the keyframe index within the video.
    """
    entries: list[_ScreenEntry] = []
    for idx, kf in enumerate(analysis.keyframes):
        sig = _element_signature(kf)
        sid = _screen_id_from_signature(sig)
        entries.append({
            "screen_id": sid,
            "keyframe": kf,
            "filename": analysis.filename,
            "index": idx,
        })
    return entries


def _find_shared_prefix_length(
    sequences: list[list[str]],
) -> int:
    """Return the length of the longest common prefix across all sequences."""
    if not sequences:
        return 0
    min_len = min(len(s) for s in sequences)
    for i in range(min_len):
        ids = {s[i] for s in sequences}
        if len(ids) > 1:
            return i
    return min_len


async def merge_paths(
    video_analyses: list[VideoAnalysis],
) -> list[DecisionTree]:
    """Merge multiple video analyses into unified decision trees.

    Algorithm:
    1. Convert each video's keyframes into a sequence of screen_ids
       (stable IDs derived from UI element signatures).
    2. Find the shared prefix — screens that are identical across all
       videos.
    3. After the prefix, detect where paths diverge to form branches.
    4. Build a single DecisionTree with the shared prefix leading to
       branch points.

    For a single video, returns a linear tree with no branches.
    """
    if not video_analyses:
        return []

    # Step 1: Build screen sequences per video
    all_sequences: list[list[_ScreenEntry]] = []
    for va in video_analyses:
        seq = _extract_screen_sequence(va)
        if seq:
            all_sequences.append(seq)

    if not all_sequences:
        return []

    # Step 2: Collect all unique screens across all videos, merging
    # source_refs for screens that appear in multiple videos.
    screen_map: dict[str, WorkflowScreen] = {}
    for seq in all_sequences:
        for entry in seq:
            sid: str = entry["screen_id"]
            kf: Keyframe = entry["keyframe"]
            fn: str = entry["filename"]
            if sid not in screen_map:
                screen_map[sid] = _keyframe_to_screen(kf, sid, fn)
            else:
                # Merge source refs from additional videos
                ref = _keyframe_to_source_ref(kf, fn)
                existing_refs = {
                    r.reference for r in screen_map[sid].source_refs
                }
                if ref.reference not in existing_refs:
                    screen_map[sid].source_refs.append(ref)

    # Step 3: Find shared prefix length across video sequences
    id_sequences = [[e["screen_id"] for e in seq] for seq in all_sequences]
    prefix_len = _find_shared_prefix_length(id_sequences)

    # Step 4: Build the decision tree
    branches: list[BranchPoint] = []

    if len(all_sequences) == 1:
        # Single video — linear chain, no branches
        seq = all_sequences[0]
        root_id = seq[0]["screen_id"]
        # Add transitions as simple sequential branches for navigation
        for i in range(len(seq) - 1):
            current_id = seq[i]["screen_id"]
            next_id = seq[i + 1]["screen_id"]
            # Find the transition action if available
            action = _find_transition_action(
                video_analyses[0], i
            )
            branches.append(BranchPoint(
                screen_id=current_id,
                condition=action,
                paths={action: next_id},
            ))
    else:
        # Multiple videos — shared prefix + divergence
        if prefix_len == 0:
            # No shared prefix — videos start at different screens.
            # Create a synthetic root that branches to each video's start.
            root_id = all_sequences[0][0]["screen_id"]
            diverge_paths: dict[str, str] = {}
            for i, seq in enumerate(all_sequences):
                if seq:
                    vid_fn = seq[0]["filename"]
                    action = f"Path from {vid_fn}"
                    diverge_paths[action] = seq[0]["screen_id"]
            if len(diverge_paths) > 1:
                branches.append(BranchPoint(
                    screen_id=root_id,
                    condition="Videos show different starting screens",
                    paths=diverge_paths,
                ))
        else:
            root_id = all_sequences[0][0]["screen_id"]

            # Add transitions within the shared prefix
            for i in range(prefix_len - 1):
                current_id = id_sequences[0][i]
                next_id = id_sequences[0][i + 1]
                action = _find_transition_action(video_analyses[0], i)
                branches.append(BranchPoint(
                    screen_id=current_id,
                    condition=action,
                    paths={action: next_id},
                ))

            # Branch point: last shared screen before divergence
            if prefix_len < max(len(s) for s in id_sequences):
                branch_screen_id = id_sequences[0][prefix_len - 1]
                diverge_paths = {}
                for seq_idx, id_seq in enumerate(id_sequences):
                    if prefix_len < len(id_seq):
                        next_screen = id_seq[prefix_len]
                        va = video_analyses[seq_idx]
                        action = _find_transition_action(
                            va, prefix_len - 1
                        )
                        # Disambiguate if actions collide
                        key = action
                        if key in diverge_paths:
                            key = f"{action} ({va.filename})"
                        diverge_paths[key] = next_screen

                if len(diverge_paths) > 1:
                    branches.append(BranchPoint(
                        screen_id=branch_screen_id,
                        condition="Paths diverge after this screen",
                        paths=diverge_paths,
                    ))
                elif len(diverge_paths) == 1:
                    # All videos go to the same next screen — not a branch
                    action, next_sid = next(iter(diverge_paths.items()))
                    branches.append(BranchPoint(
                        screen_id=branch_screen_id,
                        condition=action,
                        paths={action: next_sid},
                    ))

        # Add sequential transitions within each video's unique suffix
        for seq_idx, id_seq in enumerate(id_sequences):
            start = max(prefix_len, 1)
            for i in range(start, len(id_seq) - 1):
                current_id = id_seq[i]
                next_id = id_seq[i + 1]
                # Only add if not already covered
                existing = {
                    (b.screen_id, tuple(b.paths.values()))
                    for b in branches
                }
                if (current_id, (next_id,)) not in existing:
                    action = _find_transition_action(
                        video_analyses[seq_idx], i
                    )
                    branches.append(BranchPoint(
                        screen_id=current_id,
                        condition=action,
                        paths={action: next_id},
                    ))

    tree = DecisionTree(
        root_screen_id=root_id,
        screens=screen_map,
        branches=branches,
    )

    return [tree]


def _find_transition_action(
    analysis: VideoAnalysis, keyframe_index: int
) -> str:
    """Find the transition action between two consecutive keyframes.

    Searches the video's transitions for one that matches the timestamp
    range. Falls back to a generic description.
    """
    if keyframe_index >= len(analysis.keyframes) - 1:
        return "Continue"

    kf_from = analysis.keyframes[keyframe_index]
    kf_to = analysis.keyframes[keyframe_index + 1]

    for t in analysis.transitions:
        if (
            abs(t.from_timestamp - kf_from.timestamp_sec) < 1.0
            and abs(t.to_timestamp - kf_to.timestamp_sec) < 1.0
        ):
            return t.action

    # Fallback: use the trigger_element from the transition_from field
    if kf_to.transition_from:
        return kf_to.transition_from

    return "Next step"
