"""QA validator fan-out runner.

Runs every QA validator in parallel via ``asyncio.gather`` (with
``return_exceptions=True``), coerces raised exceptions into structured
error findings, serializes the aggregated :class:`QAReport` to
``phases/qa.json``, and returns the report.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from walkthrough.ai.qa import (
    decision_tree_structure,
    output_schema,
    video_coverage,
)
from walkthrough.models.project import Project
from walkthrough.models.qa import QAReport, ValidatorFinding, ValidatorResult
from walkthrough.storage.phase_artifacts import write_phase_artifact

ValidatorFn = Callable[[Project], Awaitable[ValidatorResult]]

VALIDATORS: list[tuple[str, ValidatorFn]] = [
    ("decision_tree_structure", decision_tree_structure.validate),
    ("output_schema", output_schema.validate),
    ("video_coverage", video_coverage.validate),
]


def _error_result(name: str, exc: BaseException) -> ValidatorResult:
    return ValidatorResult(
        validator=name,
        ok=False,
        findings=[
            ValidatorFinding(
                severity="critical",
                code="validator_error",
                message=str(exc),
            )
        ],
    )


async def run_qa(project: Project) -> QAReport:
    """Run all QA validators in parallel and persist the report."""
    raw = await asyncio.gather(
        *(fn(project) for _, fn in VALIDATORS),
        return_exceptions=True,
    )

    results: list[ValidatorResult] = []
    for (name, _), outcome in zip(VALIDATORS, raw):
        if isinstance(outcome, BaseException):
            results.append(_error_result(name, outcome))
        elif isinstance(outcome, ValidatorResult):
            results.append(outcome)
        else:
            # Validator returned something other than a ValidatorResult —
            # treat as a programming error, coerce so the pipeline doesn't crash.
            results.append(
                _error_result(
                    name,
                    TypeError(
                        f"validator returned {type(outcome).__name__}, "
                        f"expected ValidatorResult"
                    ),
                )
            )

    has_critical = any(
        f.severity == "critical" for r in results for f in r.findings
    )

    report = QAReport(
        project_id=project.project_id,
        results=results,
        has_critical=has_critical,
        generated_at=datetime.now(timezone.utc),
    )

    await write_phase_artifact(
        project.project_id, "qa", report.model_dump(mode="json")
    )

    return report
