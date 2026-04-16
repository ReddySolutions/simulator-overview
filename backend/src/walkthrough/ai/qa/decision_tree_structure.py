"""Decision-tree structural validator.

Pure-Python checks that catch structural defects in ``DecisionTree`` objects
before they reach the UI. Designed to surface the known self-loop bug
(e.g. ``screen_d3af07fa2d51`` branching back to itself) plus orphan and
unreachable screens, and dangling branch targets.
"""

from __future__ import annotations

from collections import deque

from walkthrough.models.project import Project
from walkthrough.models.qa import ValidatorFinding, ValidatorResult
from walkthrough.models.workflow import DecisionTree


def _collect_tree_findings(
    tree: DecisionTree, tree_index: int
) -> list[ValidatorFinding]:
    findings: list[ValidatorFinding] = []

    branch_targets: set[str] = set()
    for branch in tree.branches:
        for action, next_screen_id in branch.paths.items():
            branch_targets.add(next_screen_id)

            if next_screen_id == branch.screen_id:
                findings.append(
                    ValidatorFinding(
                        severity="critical",
                        code="self_loop",
                        message=(
                            f"Branch on screen '{branch.screen_id}' "
                            f"(tree #{tree_index}) loops back to itself "
                            f"via action '{action}'."
                        ),
                        screen_id=branch.screen_id,
                    )
                )

            if next_screen_id not in tree.screens:
                findings.append(
                    ValidatorFinding(
                        severity="critical",
                        code="dangling_branch_target",
                        message=(
                            f"Branch on screen '{branch.screen_id}' "
                            f"(tree #{tree_index}) action '{action}' "
                            f"targets screen '{next_screen_id}' which is "
                            f"not in tree.screens."
                        ),
                        screen_id=branch.screen_id,
                    )
                )

    reachable: set[str] = set()
    if tree.root_screen_id in tree.screens:
        queue: deque[str] = deque([tree.root_screen_id])
        reachable.add(tree.root_screen_id)
        paths_by_screen: dict[str, dict[str, str]] = {
            b.screen_id: b.paths for b in tree.branches
        }
        while queue:
            current = queue.popleft()
            for next_screen_id in paths_by_screen.get(current, {}).values():
                if (
                    next_screen_id in tree.screens
                    and next_screen_id not in reachable
                ):
                    reachable.add(next_screen_id)
                    queue.append(next_screen_id)

    for screen_id in tree.screens:
        if screen_id == tree.root_screen_id:
            continue
        if screen_id not in branch_targets:
            findings.append(
                ValidatorFinding(
                    severity="medium",
                    code="orphan_screen",
                    message=(
                        f"Screen '{screen_id}' (tree #{tree_index}) is not "
                        f"the root and is not targeted by any branch path."
                    ),
                    screen_id=screen_id,
                )
            )
        if screen_id not in reachable:
            findings.append(
                ValidatorFinding(
                    severity="medium",
                    code="unreachable_screen",
                    message=(
                        f"Screen '{screen_id}' (tree #{tree_index}) is not "
                        f"reachable from root '{tree.root_screen_id}' via BFS."
                    ),
                    screen_id=screen_id,
                )
            )

    return findings


async def validate(project: Project) -> ValidatorResult:
    """Run structural checks across every decision tree on ``project``."""
    findings: list[ValidatorFinding] = []
    for index, tree in enumerate(project.decision_trees):
        findings.extend(_collect_tree_findings(tree, index))

    ok = not any(f.severity == "critical" for f in findings)
    return ValidatorResult(
        validator="decision_tree_structure",
        ok=ok,
        findings=findings,
    )
