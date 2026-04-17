"""Generated-output schema validator.

Loads ``phases/generation.json`` and checks the dict shape emitted by
``walkthrough.ai.tools.generate.generate_walkthrough``. Catches the
field-name regressions that broke the frontend in the current session:
legacy ``elements`` key (should be ``ui_elements``), stats missing
``total_branches`` / ``open_questions`` or carrying legacy
``total_branch_points`` / ``open_questions_count`` / ``warnings_count``,
and malformed screen / ui_element entries.
"""

from __future__ import annotations

from typing import Any

from walkthrough.models.project import Project
from walkthrough.models.qa import ValidatorFinding, ValidatorResult
from walkthrough.storage.phase_artifacts import read_phase_artifact

REQUIRED_SCREEN_FIELDS: tuple[str, ...] = (
    "screen_id",
    "title",
    "ui_elements",
    "evidence_tier",
    "source_refs",
)

REQUIRED_UI_ELEMENT_FIELDS: tuple[str, ...] = ("element_type", "label")

REQUIRED_STATS_FIELDS: tuple[str, ...] = ("total_branches", "open_questions")

LEGACY_STATS_FIELDS: tuple[str, ...] = (
    "total_branch_points",
    "open_questions_count",
    "warnings_count",
)


def _check_screens(
    screens: dict[str, Any],
) -> list[ValidatorFinding]:
    findings: list[ValidatorFinding] = []

    for screen_id, screen in screens.items():
        if not isinstance(screen, dict):
            findings.append(
                ValidatorFinding(
                    severity="critical",
                    code="missing_screen_field",
                    message=(
                        f"Screen '{screen_id}' is not a dict "
                        f"(got {type(screen).__name__})."
                    ),
                    screen_id=screen_id,
                )
            )
            continue

        for field in REQUIRED_SCREEN_FIELDS:
            if field not in screen:
                findings.append(
                    ValidatorFinding(
                        severity="critical",
                        code="missing_screen_field",
                        message=(
                            f"Screen '{screen_id}' is missing required "
                            f"field '{field}'."
                        ),
                        screen_id=screen_id,
                    )
                )

        if "elements" in screen:
            findings.append(
                ValidatorFinding(
                    severity="critical",
                    code="legacy_elements_key",
                    message=(
                        f"Screen '{screen_id}' uses legacy key 'elements'; "
                        f"generate.py must emit 'ui_elements'."
                    ),
                    screen_id=screen_id,
                )
            )

        ui_elements = screen.get("ui_elements")
        if isinstance(ui_elements, list):
            for index, element in enumerate(ui_elements):
                if not isinstance(element, dict):
                    findings.append(
                        ValidatorFinding(
                            severity="critical",
                            code="bad_ui_element",
                            message=(
                                f"Screen '{screen_id}' ui_elements[{index}] "
                                f"is not a dict (got {type(element).__name__})."
                            ),
                            screen_id=screen_id,
                        )
                    )
                    continue
                for field in REQUIRED_UI_ELEMENT_FIELDS:
                    if field not in element:
                        findings.append(
                            ValidatorFinding(
                                severity="critical",
                                code="bad_ui_element",
                                message=(
                                    f"Screen '{screen_id}' ui_elements[{index}] "
                                    f"missing required field '{field}'."
                                ),
                                screen_id=screen_id,
                            )
                        )

    return findings


def _check_warnings(
    warnings: list[Any], screen_ids: set[str]
) -> list[ValidatorFinding]:
    findings: list[ValidatorFinding] = []

    for index, warning in enumerate(warnings):
        if not isinstance(warning, dict):
            continue
        screen_id = warning.get("screen_id")
        if not screen_id:
            continue
        if screen_id not in screen_ids:
            findings.append(
                ValidatorFinding(
                    severity="medium",
                    code="warning_references_missing_screen",
                    message=(
                        f"warnings[{index}] references screen_id "
                        f"'{screen_id}' which is not in output.screens."
                    ),
                    screen_id=screen_id,
                )
            )

    return findings


def _check_stats(stats: dict[str, Any]) -> list[ValidatorFinding]:
    findings: list[ValidatorFinding] = []

    for field in REQUIRED_STATS_FIELDS:
        if field not in stats:
            findings.append(
                ValidatorFinding(
                    severity="critical",
                    code="stats_field_mismatch",
                    message=(
                        f"stats is missing required field '{field}'."
                    ),
                )
            )

    for legacy in LEGACY_STATS_FIELDS:
        if legacy in stats:
            findings.append(
                ValidatorFinding(
                    severity="critical",
                    code="stats_field_mismatch",
                    message=(
                        f"stats contains legacy field '{legacy}' "
                        f"(regression — generate.py should not emit this)."
                    ),
                )
            )

    return findings


async def validate(project: Project) -> ValidatorResult:
    """Validate the generated-output dict for the current project."""
    artifact = await read_phase_artifact(project.project_id, "generation")

    if artifact is None:
        return ValidatorResult(
            validator="output_schema",
            ok=False,
            findings=[
                ValidatorFinding(
                    severity="critical",
                    code="generation_artifact_missing",
                    message=(
                        f"phases/generation.json is missing for project "
                        f"'{project.project_id}'."
                    ),
                )
            ],
        )

    findings: list[ValidatorFinding] = []

    screens = artifact.get("screens") or {}
    if isinstance(screens, dict):
        findings.extend(_check_screens(screens))
        screen_ids = set(screens.keys())
    else:
        screen_ids = set()

    warnings = artifact.get("warnings") or []
    if isinstance(warnings, list):
        findings.extend(_check_warnings(warnings, screen_ids))

    stats = artifact.get("stats")
    if isinstance(stats, dict):
        findings.extend(_check_stats(stats))
    else:
        findings.append(
            ValidatorFinding(
                severity="critical",
                code="stats_field_mismatch",
                message="stats is missing or not a dict.",
            )
        )

    ok = not any(f.severity == "critical" for f in findings)
    return ValidatorResult(
        validator="output_schema",
        ok=ok,
        findings=findings,
    )
