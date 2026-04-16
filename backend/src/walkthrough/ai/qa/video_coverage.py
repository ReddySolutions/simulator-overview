"""Video-coverage validator.

Pure-Python checks that every ``WorkflowScreen`` across all decision trees
has at least one source reference, and that any screen tagged as
``observed`` carries at least one video-typed reference.
"""

from __future__ import annotations

from walkthrough.models.project import Project
from walkthrough.models.qa import ValidatorFinding, ValidatorResult


async def validate(project: Project) -> ValidatorResult:
    """Verify source-reference coverage on every screen."""
    findings: list[ValidatorFinding] = []

    for tree_index, tree in enumerate(project.decision_trees):
        for screen_id, screen in tree.screens.items():
            if len(screen.source_refs) == 0:
                findings.append(
                    ValidatorFinding(
                        severity="critical",
                        code="screen_without_any_ref",
                        message=(
                            f"Screen '{screen_id}' (tree #{tree_index}) "
                            f"has no source_refs — every screen must cite "
                            f"at least one source."
                        ),
                        screen_id=screen_id,
                    )
                )
                continue

            if screen.evidence_tier == "observed" and not any(
                ref.source_type == "video" for ref in screen.source_refs
            ):
                findings.append(
                    ValidatorFinding(
                        severity="critical",
                        code="observed_without_video_ref",
                        message=(
                            f"Screen '{screen_id}' (tree #{tree_index}) is "
                            f"tagged evidence_tier='observed' but has no "
                            f"source_refs with source_type='video'."
                        ),
                        screen_id=screen_id,
                    )
                )

    ok = not any(f.severity == "critical" for f in findings)
    return ValidatorResult(
        validator="video_coverage",
        ok=ok,
        findings=findings,
    )
