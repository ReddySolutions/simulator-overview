"""Tests for walkthrough/models/qa.py."""

from __future__ import annotations

from datetime import datetime, timezone

from walkthrough.models.qa import QAReport, ValidatorFinding, ValidatorResult
from walkthrough.models.workflow import SourceRef


class TestValidatorFindingRoundtrip:
    def test_minimal_roundtrip(self):
        finding = ValidatorFinding(
            severity="critical", code="self_loop", message="loops back"
        )
        dumped = finding.model_dump(mode="json")
        restored = ValidatorFinding.model_validate(dumped)
        assert restored == finding
        assert restored.screen_id is None
        assert restored.evidence == []

    def test_full_roundtrip_with_evidence(self):
        finding = ValidatorFinding(
            severity="medium",
            code="orphan_screen",
            message="screen X is orphaned",
            screen_id="screen_1",
            evidence=[
                SourceRef(
                    source_type="video",
                    reference="video1.mp4:00:15",
                    excerpt="user clicks Submit",
                )
            ],
        )
        dumped = finding.model_dump(mode="json")
        restored = ValidatorFinding.model_validate(dumped)
        assert restored == finding


class TestValidatorResultRoundtrip:
    def test_ok_result_no_findings(self):
        result = ValidatorResult(validator="decision_tree_structure", ok=True)
        dumped = result.model_dump(mode="json")
        restored = ValidatorResult.model_validate(dumped)
        assert restored == result
        assert restored.findings == []

    def test_with_findings(self):
        result = ValidatorResult(
            validator="output_schema",
            ok=False,
            findings=[
                ValidatorFinding(severity="critical", code="c1", message="m1"),
                ValidatorFinding(severity="low", code="c2", message="m2"),
            ],
        )
        dumped = result.model_dump(mode="json")
        restored = ValidatorResult.model_validate(dumped)
        assert restored == result


class TestQAReportRoundtrip:
    def test_roundtrip_serializes_datetime(self):
        generated_at = datetime(2026, 4, 16, 15, 58, tzinfo=timezone.utc)
        report = QAReport(
            project_id="proj1",
            results=[
                ValidatorResult(validator="video_coverage", ok=True),
                ValidatorResult(
                    validator="output_schema",
                    ok=False,
                    findings=[
                        ValidatorFinding(
                            severity="critical",
                            code="missing_screen_field",
                            message="screen missing title",
                            screen_id="s1",
                        )
                    ],
                ),
            ],
            has_critical=True,
            generated_at=generated_at,
        )
        dumped = report.model_dump(mode="json")
        assert isinstance(dumped["generated_at"], str)
        restored = QAReport.model_validate(dumped)
        assert restored == report


class TestHasCriticalSemantics:
    """has_critical is stored, not derived — tests assert caller sets it correctly
    based on any finding having severity=='critical'."""

    def test_has_critical_true_when_any_critical_finding(self):
        findings = [
            ValidatorFinding(severity="low", code="c1", message="m1"),
            ValidatorFinding(severity="critical", code="c2", message="m2"),
            ValidatorFinding(severity="medium", code="c3", message="m3"),
        ]
        results = [
            ValidatorResult(validator="v1", ok=False, findings=findings),
        ]
        has_critical = any(
            f.severity == "critical" for r in results for f in r.findings
        )
        report = QAReport(
            project_id="p",
            results=results,
            has_critical=has_critical,
            generated_at=datetime.now(timezone.utc),
        )
        assert report.has_critical is True

    def test_has_critical_false_when_no_critical_finding(self):
        findings = [
            ValidatorFinding(severity="low", code="c1", message="m1"),
            ValidatorFinding(severity="info", code="c2", message="m2"),
        ]
        results = [ValidatorResult(validator="v1", ok=True, findings=findings)]
        has_critical = any(
            f.severity == "critical" for r in results for f in r.findings
        )
        report = QAReport(
            project_id="p",
            results=results,
            has_critical=has_critical,
            generated_at=datetime.now(timezone.utc),
        )
        assert report.has_critical is False


class TestModelReExports:
    def test_qa_models_importable_from_models_package(self):
        from walkthrough.models import QAReport as QAReportFromPkg
        from walkthrough.models import ValidatorFinding as ValidatorFindingFromPkg
        from walkthrough.models import ValidatorResult as ValidatorResultFromPkg

        assert QAReportFromPkg is QAReport
        assert ValidatorFindingFromPkg is ValidatorFinding
        assert ValidatorResultFromPkg is ValidatorResult
