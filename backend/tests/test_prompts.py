"""Tests for walkthrough/ai/prompts/fidelity.py."""

from __future__ import annotations

from walkthrough.ai.prompts.fidelity import (
    AUTHORITY_HIERARCHY,
    EVIDENCE_CITATION_RULES,
    FIDELITY_STANDARD,
    INVARIANTS,
)


class TestFidelityStandard:
    def test_is_non_empty_str(self):
        assert isinstance(FIDELITY_STANDARD, str)
        assert FIDELITY_STANDARD.strip()

    def test_contains_unreadable_marker(self):
        assert "__unreadable__" in FIDELITY_STANDARD


class TestInvariants:
    def test_is_non_empty_str(self):
        assert isinstance(INVARIANTS, str)
        assert INVARIANTS.strip()

    def test_contains_m1_marker(self):
        assert "M1" in INVARIANTS

    def test_contains_full_m1_n7_range(self):
        # All nine mandatory + seven negative invariant tags must be present.
        for tag in [
            "M1",
            "M2",
            "M3",
            "M4",
            "M5",
            "M6",
            "M7",
            "M8",
            "M9",
            "N1",
            "N2",
            "N3",
            "N4",
            "N5",
            "N6",
            "N7",
        ]:
            assert tag in INVARIANTS, f"missing invariant tag {tag}"


class TestAuthorityHierarchy:
    def test_is_non_empty_str(self):
        assert isinstance(AUTHORITY_HIERARCHY, str)
        assert AUTHORITY_HIERARCHY.strip()

    def test_contains_authority_marker(self):
        # AC: 'authority' (case-insensitive) must appear in AUTHORITY_HIERARCHY.
        assert "authority" in AUTHORITY_HIERARCHY.lower()


class TestEvidenceCitationRules:
    def test_is_non_empty_str(self):
        assert isinstance(EVIDENCE_CITATION_RULES, str)
        assert EVIDENCE_CITATION_RULES.strip()

    def test_contains_sourceref_marker(self):
        assert "SourceRef" in EVIDENCE_CITATION_RULES
