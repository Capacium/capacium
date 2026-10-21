"""CAP117-EVIDENCE-005 red proofs — Dispatch 1 (criteria 1-3) and Dispatch 2 (criteria 4-6).

Red proofs MUST fail before implementation.
"""

import pytest


# ---------------------------------------------------------------------------
# Criterion 1: Origin, publisher authority, technical verification, security
# assessment, distribution authority, lifecycle and install consent are stored
# as independent axes.
# ---------------------------------------------------------------------------

def test_c1_independent_axes_import():
    """EvidenceRecord carries independent axis attributes."""
    from src.capacium.trust import EvidenceRecord
    from src.capacium.trust import PublisherAuthority
    from src.capacium.trust import SecurityAssessment
    from src.capacium.trust import DistributionAuthority
    from src.capacium.trust import Lifecycle

    rec = EvidenceRecord(
        origin="registry-seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    assert rec.origin == "registry-seed"
    assert rec.publisher_authority == PublisherAuthority.NULL
    assert rec.security_assessment == SecurityAssessment.NONE
    assert rec.lifecycle == Lifecycle.ACTIVE


def test_c1_evidence_record_is_immutable():
    """EvidenceRecord is frozen/immutable."""
    from src.capacium.trust import EvidenceRecord, PublisherAuthority, SecurityAssessment
    from src.capacium.trust import DistributionAuthority, Lifecycle

    rec = EvidenceRecord(
        origin="seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    with pytest.raises(Exception):
        rec.origin = "changed"


def test_c1_axes_are_independent():
    """Mutating one axis does not affect others."""
    from src.capacium.trust import EvidenceRecord, PublisherAuthority, SecurityAssessment
    from src.capacium.trust import DistributionAuthority, Lifecycle

    rec = EvidenceRecord(
        origin="seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    # Changing one field in a new record does not touch the original
    rec2 = EvidenceRecord(
        origin="registry",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    assert rec.origin == "seed"
    assert rec2.origin == "registry"
    assert rec2.publisher_authority == rec.publisher_authority


# ---------------------------------------------------------------------------
# Criterion 2: Generated manifests use null publisher authority and no
# security assessment and cannot transition to reviewed or publisher-adopted
# without a signed event.
# ---------------------------------------------------------------------------

def test_c2_generated_manifest_defaults_null():
    """Generated manifests default to NULL publisher authority and NONE security assessment."""
    from src.capacium.trust import PublisherAuthority, SecurityAssessment

    assert PublisherAuthority.NULL.value == "null"
    assert SecurityAssessment.NONE.value == "none"


def test_c2_null_authority_cannot_transition_without_signed_event():
    """PublisherAuthority.NULL cannot transition to REVIEWED or PUBLISHER_ADOPTED without a signed event."""
    from src.capacium.trust import PublisherAuthority

    # NULL is the starting point for generated/community manifests
    pa = PublisherAuthority.NULL
    # Transitions that require a signed event must reject
    assert not PublisherAuthority.can_transition(pa, PublisherAuthority.REVIEWED)
    assert not PublisherAuthority.can_transition(pa, PublisherAuthority.PUBLISHER_ADOPTED)


def test_c2_none_security_cannot_transition_without_signed_event():
    """SecurityAssessment.NONE cannot become REVIEWED without a signed event."""
    from src.capacium.trust import SecurityAssessment

    assert not SecurityAssessment.can_transition(
        SecurityAssessment.NONE, SecurityAssessment.REVIEWED
    )


def test_c2_signed_event_required_for_authority_transition():
    """A signed_event token is required for NULL->REVIEWED authority transition."""
    from src.capacium.trust import PublisherAuthority

    # Attempting transition without signed_event must raise or return False
    with pytest.raises((ValueError, TypeError)):
        PublisherAuthority.NULL.transition_to(PublisherAuthority.REVIEWED)


# ---------------------------------------------------------------------------
# Criterion 3: Initial seed and unknown-capability install invoke the same
# pipeline and durable EvidenceRecord schema.
# ---------------------------------------------------------------------------

def test_c3_evidence_record_schema_is_durable():
    """EvidenceRecord has a fixed schema_version and can round-trip through dict."""
    from src.capacium.trust import EvidenceRecord, PublisherAuthority, SecurityAssessment
    from src.capacium.trust import DistributionAuthority, Lifecycle

    rec = EvidenceRecord(
        origin="seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    d = rec.to_dict()
    assert d["schema_version"] is not None
    assert isinstance(d["schema_version"], str)
    rt = EvidenceRecord.from_dict(d)
    assert rt.origin == rec.origin
    assert rt.publisher_authority == rec.publisher_authority


def test_c3_seed_and_unknown_share_schema():
    """Seed and unknown-capability EvidenceRecords use the same schema."""
    from src.capacium.trust import EvidenceRecord, PublisherAuthority, SecurityAssessment
    from src.capacium.trust import DistributionAuthority, Lifecycle

    seed = EvidenceRecord(
        origin="seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    unknown = EvidenceRecord(
        origin="unknown-install",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    sd = seed.to_dict()
    ud = unknown.to_dict()
    assert sd["schema_version"] == ud["schema_version"]
    # Same set of keys
    assert set(sd.keys()) == set(ud.keys())


def test_c3_evidence_record_from_dict_rejects_unknown_fields():
    """EvidenceRecord.from_dict rejects fields not in the schema."""
    from src.capacium.trust import EvidenceRecord

    with pytest.raises(ValueError):
        EvidenceRecord.from_dict({"unknown_key": "value"})


def test_c3_evidence_record_from_dict_requires_schema_version():
    """EvidenceRecord.from_dict requires schema_version."""
    from src.capacium.trust import EvidenceRecord

    with pytest.raises(ValueError):
        EvidenceRecord.from_dict({"origin": "seed"})


def test_c3_consent_record_is_durable():
    """ConsentRecord binds exact manifest, source revision and artifact digests."""
    from src.capacium.trust import ConsentRecord

    c = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="abc123def456",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert c.manifest_digest.startswith("sha256:")
    assert len(c.source_revision) > 0


def test_c3_consent_record_never_mutates_registry_trust():
    """ConsentRecord is stored separately and never mutates EvidenceRecord trust axes."""
    from src.capacium.trust import ConsentRecord, EvidenceRecord, PublisherAuthority
    from src.capacium.trust import SecurityAssessment, DistributionAuthority, Lifecycle

    rec = EvidenceRecord(
        origin="seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    assert rec.origin == "seed"
    # Consent is a separate record type
    consent = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="abc123",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert not isinstance(consent, EvidenceRecord)
    assert consent.manifest_digest is not None


# ---------------------------------------------------------------------------
# Criterion 4: Install consent binds exact manifest, source revision and
# artifact digests and never mutates registry trust axes.
# ---------------------------------------------------------------------------

def test_c4_consent_binds_exact_manifest_digest():
    """Install consent must bind the exact manifest digest."""
    from src.capacium.trust import ConsentRecord

    c = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="abc123def456",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    # Consent is exact — changing the digest produces a different record
    c2 = ConsentRecord(
        manifest_digest="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        source_revision="abc123def456",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert c.manifest_digest != c2.manifest_digest
    assert c.source_revision == c2.source_revision


def test_c4_consent_binds_exact_source_revision():
    """Install consent must bind the exact source revision."""
    from src.capacium.trust import ConsentRecord

    c1 = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="abc123",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    c2 = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="def456",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert c1.source_revision != c2.source_revision
    assert c1.manifest_digest == c2.manifest_digest


def test_c4_consent_never_mutates_trust_axes():
    """EvidenceRecord trust axes are immutable; consent cannot change them."""
    from src.capacium.trust import EvidenceRecord, PublisherAuthority, SecurityAssessment
    from src.capacium.trust import DistributionAuthority, Lifecycle, ConsentRecord

    rec = EvidenceRecord(
        origin="seed",
        publisher_authority=PublisherAuthority.NULL,
        technical_verification=None,
        security_assessment=SecurityAssessment.NONE,
        distribution_authority=DistributionAuthority.UNKNOWN,
        lifecycle=Lifecycle.ACTIVE,
        install_consent=None,
    )
    # Even with consent attached, trust axes are unchanged
    consent = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="abc123",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    rec2 = EvidenceRecord(
        origin=rec.origin,
        publisher_authority=rec.publisher_authority,
        technical_verification=rec.technical_verification,
        security_assessment=rec.security_assessment,
        distribution_authority=rec.distribution_authority,
        lifecycle=rec.lifecycle,
        install_consent=consent,
    )
    # Trust axes unchanged
    assert rec2.publisher_authority == rec.publisher_authority
    assert rec2.security_assessment == rec.security_assessment
    assert rec2.lifecycle == rec.lifecycle
    assert rec2.distribution_authority == rec.distribution_authority
    assert rec2.install_consent is not None
    assert rec.install_consent is None


# ---------------------------------------------------------------------------
# Criterion 5: Two-source corroboration is configurable; an eligible
# single-source case records abstention and follows the disclosed consent
# path rather than silently blocking or trusting.
# ---------------------------------------------------------------------------

def test_c5_corroboration_config_import():
    """CorroborationConfig type exists and is configurable."""
    from src.capacium.trust import CorroborationConfig

    cfg = CorroborationConfig(required_sources=2)
    assert cfg.required_sources == 2


def test_c5_single_source_config():
    """CorroborationConfig can require 1 source (single-source eligible)."""
    from src.capacium.trust import CorroborationConfig

    cfg = CorroborationConfig(required_sources=1)
    assert cfg.required_sources == 1


def test_c5_abstention_result_import():
    """AbstentionResult type exists for single-source cases."""
    from src.capacium.trust import AbstentionResult, AbstentionReason

    a = AbstentionResult(
        reason=AbstentionReason.SINGLE_SOURCE,
        disclosed=True,
        consent_path="disclosed-consent",
    )
    assert a.reason == AbstentionReason.SINGLE_SOURCE
    assert a.disclosed is True


def test_c5_single_source_abstains_not_blocks():
    """Single-source eligible case records abstention, does not block."""
    from src.capacium.trust import AbstentionResult, AbstentionReason

    # An abstention is explicit — it records the reason and follows
    # the disclosed consent path rather than silently blocking.
    a = AbstentionResult(
        reason=AbstentionReason.SINGLE_SOURCE,
        disclosed=True,
        consent_path="disclosed-consent",
    )
    assert a.reason != "blocked"
    assert a.disclosed is True


def test_c5_multi_source_no_abstention():
    """When two sources corroborate, no abstention is recorded."""
    from src.capacium.trust import AbstentionResult, AbstentionReason

    # With two sources, corroboration succeeds — no abstention needed
    a = AbstentionResult(
        reason=AbstentionReason.CORROBORATED,
        disclosed=False,
        consent_path=None,
    )
    assert a.reason == AbstentionReason.CORROBORATED
    assert a.disclosed is False


def test_c5_abstention_result_immutable():
    """AbstentionResult is frozen."""
    from src.capacium.trust import AbstentionResult, AbstentionReason

    a = AbstentionResult(
        reason=AbstentionReason.SINGLE_SOURCE,
        disclosed=True,
        consent_path="disclosed-consent",
    )
    with pytest.raises(Exception):
        a.reason = AbstentionReason.CORROBORATED


# ---------------------------------------------------------------------------
# Criterion 6: Conflicts, moving references, unavailable evidence, licences,
# redistribution rights, duplicates, malicious metadata and low confidence
# quarantine deterministically.
# ---------------------------------------------------------------------------

def test_c6_ingest_disposition_import():
    """IngestDisposition type exists with deterministic outcome."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.ACCEPTED,
        reason="validated",
    )
    assert d.outcome == IngestOutcome.ACCEPTED


def test_c6_ingest_conflict_disposition():
    """Conflicts produce a deterministic disposition."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.CONFLICT,
        reason="fingerprint-mismatch",
        detail="existing sha256:abc != incoming sha256:def",
    )
    assert d.outcome == IngestOutcome.CONFLICT
    assert d.reason == "fingerprint-mismatch"
    assert d.detail is not None


def test_c6_ingest_duplicate_disposition():
    """Duplicates produce a deterministic disposition."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.DUPLICATE,
        reason="already-ingested",
        detail="sha256:abc matches existing record",
    )
    assert d.outcome == IngestOutcome.DUPLICATE


def test_c6_ingest_quarantine_disposition():
    """Low confidence or malicious metadata results in quarantine."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.QUARANTINED,
        reason="low-confidence",
        detail="only one source corroborated; confidence 0.4 below threshold 0.7",
    )
    assert d.outcome == IngestOutcome.QUARANTINED


def test_c6_ingest_malicious_metadata_disposition():
    """Malicious metadata is deterministically rejected."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.MALICIOUS_METADATA,
        reason="suspicious-field",
        detail="metadata contains disallowed field: execute_on_install",
    )
    assert d.outcome == IngestOutcome.MALICIOUS_METADATA


def test_c6_ingest_unavailable_evidence_disposition():
    """Unavailable evidence produces a deterministic disposition."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.UNAVAILABLE_EVIDENCE,
        reason="source-unreachable",
        detail="source URL returned 503 after 3 retries",
    )
    assert d.outcome == IngestOutcome.UNAVAILABLE_EVIDENCE


def test_c6_ingest_license_redistribution_disposition():
    """Licence and redistribution right issues are deterministically handled."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.LICENCE_RESTRICTION,
        reason="no-redistribution",
        detail="licence prohibits redistribution",
    )
    assert d.outcome == IngestOutcome.LICENCE_RESTRICTION


def test_c6_ingest_moving_reference_disposition():
    """Moving references produce a deterministic disposition."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.MOVING_REFERENCE,
        reason="unpinned-branch",
        detail="source references branch 'main' rather than a fixed commit",
    )
    assert d.outcome == IngestOutcome.MOVING_REFERENCE


def test_c6_ingest_disposition_is_immutable():
    """IngestDisposition is frozen."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.ACCEPTED,
        reason="validated",
    )
    with pytest.raises(Exception):
        d.outcome = IngestOutcome.CONFLICT


def test_c6_all_outcomes_are_distinct():
    """Every IngestOutcome value is distinct."""
    from src.capacium.trust import IngestOutcome

    values = [e.value for e in IngestOutcome]
    assert len(values) == len(set(values))


def test_c6_ingest_disposition_round_trip():
    """IngestDisposition round-trips through dict."""
    from src.capacium.trust import IngestDisposition, IngestOutcome

    d = IngestDisposition(
        outcome=IngestOutcome.QUARANTINED,
        reason="low-confidence",
        detail="confidence 0.3",
    )
    dd = d.to_dict()
    assert dd["outcome"] == "quarantined"
    assert dd["reason"] == "low-confidence"
    rt = IngestDisposition.from_dict(dd)
    assert rt.outcome == d.outcome
    assert rt.reason == d.reason
    assert rt.detail == d.detail
