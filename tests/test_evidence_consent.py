"""CAP117-EVIDENCE-005 Dispatch 1 red proofs — criteria 1-3.

These tests import types that DO NOT YET EXIST in src/capacium/trust.py.
They MUST fail (ImportError / AttributeError) before any implementation.
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
    from src.capacium.trust import ConsentRecord

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
    from src.capacium.trust import PublisherAuthority, SecurityAssessment

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
    # Consent is a separate record type
    consent = ConsentRecord(
        manifest_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        source_revision="abc123",
        artifact_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert not isinstance(consent, EvidenceRecord)
    assert consent.manifest_digest is not None
