"""Generate walkthrough tool — produces final structured JSON for the web app.

Transforms a fully-analyzed Project into a self-contained JSON output that the
frontend can render without additional API calls. Includes decision trees,
wireframe screen data derived from video keyframes (M5), evidence tier markings
(M9), warnings for unresolved critical gaps (N3), and open questions for
unresolved medium/low gaps (S6). No inferred screens or branches (N1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from walkthrough.models.project import Gap, Project
from walkthrough.models.workflow import (
    BranchPoint,
    DecisionTree,
    SourceRef,
    WorkflowScreen,
)


def _source_ref_to_dict(ref: SourceRef) -> dict[str, Any]:
    """Convert a SourceRef to a frontend-friendly dict."""
    d: dict[str, Any] = {
        "source_type": ref.source_type,
        "reference": ref.reference,
    }
    if ref.excerpt:
        d["excerpt"] = ref.excerpt
    return d


def _build_screen_wireframe(screen: WorkflowScreen) -> dict[str, Any]:
    """Build wireframe data for a single screen from video keyframe UI descriptions (M5).

    Element types, labels, and states come directly from Gemini video analysis —
    NOT from Claude's general knowledge.
    """
    elements: list[dict[str, Any]] = []
    for el in screen.ui_elements:
        element_data: dict[str, Any] = {
            "element_type": el.element_type,
            "label": el.label,
        }
        if el.state:
            element_data["state"] = el.state
        elements.append(element_data)

    wireframe: dict[str, Any] = {
        "screen_id": screen.screen_id,
        "title": screen.title,
        "elements": elements,
        "evidence_tier": screen.evidence_tier,
        "source_refs": [_source_ref_to_dict(r) for r in screen.source_refs],
    }

    if screen.narrative:
        wireframe["narrative"] = {
            "what": screen.narrative.what,
            "why": screen.narrative.why,
        }
        if screen.narrative.when_condition:
            wireframe["narrative"]["when_condition"] = screen.narrative.when_condition

    return wireframe


def _build_decision_tree_output(tree: DecisionTree) -> dict[str, Any]:
    """Serialize a DecisionTree to a frontend-friendly dict preserving full structure (M6)."""
    screens: dict[str, dict[str, Any]] = {}
    for screen_id, screen in tree.screens.items():
        screens[screen_id] = _build_screen_wireframe(screen)

    branches: list[dict[str, Any]] = []
    for bp in tree.branches:
        branches.append({
            "screen_id": bp.screen_id,
            "condition": bp.condition,
            "paths": dict(bp.paths),
        })

    return {
        "root_screen_id": tree.root_screen_id,
        "screens": screens,
        "branches": branches,
    }


def _find_affected_screens(
    gap: Gap,
    decision_trees: list[DecisionTree],
) -> list[str]:
    """Find screen_ids affected by a gap based on evidence references.

    Matches gap evidence references against screen source_refs to identify
    which screens should carry the warning.
    """
    affected: list[str] = []
    gap_refs = {ref.reference for ref in gap.evidence}

    for tree in decision_trees:
        for screen_id, screen in tree.screens.items():
            screen_refs = {r.reference for r in screen.source_refs}
            if gap_refs & screen_refs:
                affected.append(screen_id)

    # If no direct match, check for label overlap in gap description
    if not affected:
        desc_lower = gap.description.lower()
        for tree in decision_trees:
            for screen_id, screen in tree.screens.items():
                for el in screen.ui_elements:
                    if el.label.strip().lower() in desc_lower:
                        affected.append(screen_id)
                        break

    return affected


def _build_warnings(
    gaps: list[Gap],
    decision_trees: list[DecisionTree],
) -> list[dict[str, Any]]:
    """Build warnings from unresolved critical gaps (N3).

    Each warning is placed on affected screens with the conflicting evidence
    cited. Unanswerable critical gaps produce prominent warnings.
    """
    warnings: list[dict[str, Any]] = []

    for gap in gaps:
        if gap.severity != "critical" or gap.resolved:
            continue

        affected_screens = _find_affected_screens(gap, decision_trees)

        warnings.append({
            "gap_id": gap.gap_id,
            "severity": gap.severity,
            "description": gap.description,
            "evidence": [_source_ref_to_dict(r) for r in gap.evidence],
            "affected_screens": affected_screens,
            "resolution": gap.resolution,
        })

    return warnings


def _build_open_questions(gaps: list[Gap]) -> list[dict[str, Any]]:
    """Build open questions from unresolved medium/low gaps (S6).

    Each entry includes severity and source refs so the frontend can
    display them with appropriate context.
    """
    questions: list[dict[str, Any]] = []

    for gap in gaps:
        if gap.resolved:
            continue
        if gap.severity == "critical":
            # Critical gaps go to warnings, not open_questions
            continue

        questions.append({
            "gap_id": gap.gap_id,
            "severity": gap.severity,
            "description": gap.description,
            "evidence": [_source_ref_to_dict(r) for r in gap.evidence],
            "resolution": gap.resolution,
        })

    return questions


def _count_paths(branches: list[BranchPoint]) -> int:
    """Count distinct decision paths from branch points."""
    if not branches:
        return 1
    return sum(len(bp.paths) for bp in branches)


async def generate_walkthrough(project: Project) -> dict[str, Any]:
    """Generate the final structured walkthrough JSON for the web app.

    Produces a self-contained JSON output that the frontend can render
    without additional API calls. Includes:
    - Project metadata
    - Decision trees with full structure (M6)
    - Wireframe screen data from video keyframes (M5)
    - Evidence tier markings on every screen (M9)
    - Warnings for unresolved critical gaps on affected screens (N3)
    - Open questions for unresolved medium/low gaps (S6)

    No inferred screens or branches are included (N1) — only what was
    observed in video or mentioned in audio/PDF.

    Args:
        project: Fully analyzed project with decision trees, gaps, and questions.

    Returns:
        Self-contained JSON dict for frontend rendering.
    """
    # Project metadata
    metadata: dict[str, Any] = {
        "project_id": project.project_id,
        "name": project.name,
        "status": project.status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": {
            "videos": [
                {"video_id": v.video_id, "filename": v.filename}
                for v in project.videos
            ],
            "pdfs": [
                {"pdf_id": p.pdf_id, "filename": p.filename}
                for p in project.pdfs
            ],
        },
    }

    # Decision trees — full structure preserved (M6)
    decision_trees = [
        _build_decision_tree_output(tree) for tree in project.decision_trees
    ]

    # Aggregate screen data across all trees for the flat screens index
    all_screens: dict[str, dict[str, Any]] = {}
    for tree in project.decision_trees:
        for screen_id, screen in tree.screens.items():
            if screen_id not in all_screens:
                all_screens[screen_id] = _build_screen_wireframe(screen)

    # Warnings — unresolved critical gaps placed on affected screens (N3)
    warnings = _build_warnings(project.gaps, project.decision_trees)

    # Attach warnings to individual screens
    warning_map: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        for sid in warning["affected_screens"]:
            warning_map.setdefault(sid, []).append({
                "gap_id": warning["gap_id"],
                "description": warning["description"],
                "evidence": warning["evidence"],
            })

    for screen_id, screen_data in all_screens.items():
        screen_warnings = warning_map.get(screen_id, [])
        if screen_warnings:
            screen_data["warnings"] = screen_warnings

    # Open questions — unresolved medium/low gaps (S6)
    open_questions = _build_open_questions(project.gaps)

    # Stats for the hero dashboard
    total_screens = len(all_screens)
    total_branches = sum(
        len(tree.branches) for tree in project.decision_trees
    )
    total_paths = sum(
        _count_paths(tree.branches) for tree in project.decision_trees
    )

    return {
        "metadata": metadata,
        "decision_trees": decision_trees,
        "screens": all_screens,
        "warnings": warnings,
        "open_questions": open_questions,
        "stats": {
            "total_screens": total_screens,
            "total_branch_points": total_branches,
            "total_paths": total_paths,
            "open_questions_count": len(open_questions),
            "warnings_count": len(warnings),
        },
    }
