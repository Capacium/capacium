"""CAP117-GATE-008 audit A10: Capacium content is English only.

AGENTS.md (Standards > Language) requires English for all Capacium content.
The ``IngestCondition`` enum carried German member names and German string
values. This module pins the required English spelling of both, and pins that
the rename changed no behaviour: every condition still maps to the same
outcome with the same reason and the same fail-closed arms.

The German spelling accepted as the reference for "before" is recorded here so
that the red proof is explicit about what it rejects.
"""

from __future__ import annotations

import pytest

from src.capacium.trust import (
    IngestCondition,
    IngestOutcome,
    classify_ingest,
)

#: member -> (value, outcome, reason). English is the required spelling.
EXPECTED_CONDITIONS = {
    "DUPLICATE": ("duplicate", IngestOutcome.DUPLICATE, "already-ingested"),
    "CONFLICT": ("conflict", IngestOutcome.CONFLICT, "fingerprint-mismatch"),
    "MOVING_REFERENCE": (
        "moving_reference",
        IngestOutcome.MOVING_REFERENCE,
        "unpinned-reference",
    ),
    "MISSING_EVIDENCE": (
        "missing_evidence",
        IngestOutcome.UNAVAILABLE_EVIDENCE,
        "evidence-unavailable",
    ),
    "LICENCE_RESTRICTION": (
        "licence_restriction",
        IngestOutcome.LICENCE_RESTRICTION,
        "no-redistribution",
    ),
    "HOSTILE_METADATA": (
        "hostile_metadata",
        IngestOutcome.MALICIOUS_METADATA,
        "hostile-metadata",
    ),
    "LOW_CONFIDENCE": ("low_confidence", IngestOutcome.QUARANTINED, "low-confidence"),
    "DECISION_RESERVED": ("decision_reserved", IngestOutcome.ACCEPTED, "validated"),
}

_GERMAN_MEMBERS = (
    "DOPPELT",
    "KONFLIKT",
    "UMGEZOGENER_VERWEIS",
    "FEHLENDE_EVIDENZ",
    "LIZENZ_EINSCHRAENKUNG",
    "HOSTILE_METADATEN",
    "GERINGE_KONFIDENZ",
    "ABSTIMMUNG_VORBEHALTEN",
)

_GERMAN_VALUES = (
    "doppelt",
    "konflikt",
    "umgezogener_verweis",
    "fehlende_evidenz",
    "lizenz_einschraenkung",
    "hostile_metadaten",
    "geringe_konfidenz",
    "abstimmung_vorbehalten",
)


def test_a10_enum_member_names_are_english():
    """No German member name survives on the enum."""
    present = {member.name for member in IngestCondition}
    german = present & set(_GERMAN_MEMBERS)
    assert not german, f"German enum member names remain: {sorted(german)}"
    assert present == set(EXPECTED_CONDITIONS), (
        f"unexpected member set: {sorted(present ^ set(EXPECTED_CONDITIONS))}"
    )


def test_a10_enum_values_are_english():
    """No German string value survives on the enum."""
    values = {member.value for member in IngestCondition}
    german = values & set(_GERMAN_VALUES)
    assert not german, f"German enum values remain: {sorted(german)}"
    assert values == {v for v, _, _ in EXPECTED_CONDITIONS.values()}, (
        f"unexpected value set: {sorted(values)}"
    )


def test_a10_every_condition_keeps_its_outcome_and_reason():
    """The rename is spelling only: outcome and reason are unchanged."""
    for name, (value, outcome, reason) in EXPECTED_CONDITIONS.items():
        condition = getattr(IngestCondition, name)
        assert condition.value == value
        disposition = classify_ingest(
            condition,
            existing_digest="sha256:" + "a" * 64,
            incoming_digest="sha256:" + "b" * 64,
        )
        assert disposition.outcome is outcome, name
        assert disposition.reason == reason, name


def test_a10_conflict_still_fails_closed_without_digests():
    """The fail-closed arm survived the rename."""
    with pytest.raises(ValueError, match="existing_digest"):
        classify_ingest(IngestCondition.CONFLICT, incoming_digest="sha256:" + "b" * 64)


def test_a10_duplicate_still_requires_an_incoming_digest():
    """The duplicate arm survived the rename."""
    with pytest.raises(ValueError, match="incoming_digest"):
        classify_ingest(IngestCondition.DUPLICATE)
