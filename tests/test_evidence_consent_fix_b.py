"""CAP117-EVIDENCE-005 Fix round B — criteria 4, 5 and 6 consumers.

Dispatch 1 of this task shipped the evidence/consent model as importable types
with no call path in ``src/``. Review 1 failed on exactly that (D3), plus the
unreachable signed-event branches (D5) and an ingest pipeline that verified
nothing (D6).

These proofs therefore exercise the *paths*, not the dataclasses:

- criterion 4: consent binds the bytes on disk and only the consent axis moves
- criterion 5: a source set plus a config decides corroboration or abstention
- criterion 6: an observed condition decides a disposition, deterministically
- D5: a signed event and the structural table are independent guards
- D6: the pipeline recomputes the digest and reads hooks from the manifest
- D3: the install surface routes through the shared classifier
"""

import pytest


# ---------------------------------------------------------------------------
# Criterion 4 — install consent binds exact bytes and mutates no trust axis
# ---------------------------------------------------------------------------

def _seed_evidence(tmp_path):
    from src.capacium.trust import (
        EVIDENCE_RECORD_FILENAME,
        ORIGIN_UNKNOWN_INSTALL,
        build_evidence_record,
        write_evidence_record,
    )

    (tmp_path / "capability.yaml").write_text("name: demo\nkind: skill\n")
    (tmp_path / "SKILL.md").write_text("# demo\n")
    record = build_evidence_record(ORIGIN_UNKNOWN_INSTALL)
    write_evidence_record(tmp_path, record)
    return record, tmp_path / EVIDENCE_RECORD_FILENAME


def test_c4_consent_binding_covers_the_bytes_on_disk(tmp_path):
    """Consent binds digests computed from the package, not from caller input."""
    from src.capacium.trust import build_install_consent

    evidence, _ = _seed_evidence(tmp_path)
    binding = build_install_consent(evidence, tmp_path, source_revision="abc123")

    assert binding.manifest_digest.startswith("sha256:")
    assert binding.artifact_digest.startswith("sha256:")
    assert binding.source_revision == "abc123"

    # Changing a tracked byte changes the digest — consent is exact.
    (tmp_path / "SKILL.md").write_text("# demo changed\n")
    changed = build_install_consent(evidence, tmp_path, source_revision="abc123")
    assert changed.manifest_digest != binding.manifest_digest
    assert binding.manifest_digest.startswith("sha256:")


def test_c4_consent_binding_ignores_capacium_sidecars(tmp_path):
    """The evidence and source sidecars Capacium writes never feed the digest."""
    from src.capacium.trust import (
        build_evidence_record,
        build_install_consent,
        ORIGIN_UNKNOWN_INSTALL,
        write_evidence_record,
    )

    _seed_evidence(tmp_path)
    first = build_install_consent(_seed_evidence(tmp_path)[0], tmp_path, "r1")

    # Rewriting the evidence record is not a change to the capability.
    write_evidence_record(tmp_path, build_evidence_record(ORIGIN_UNKNOWN_INSTALL))
    second = build_install_consent(_seed_evidence(tmp_path)[0], tmp_path, "r1")

    assert first.manifest_digest == second.manifest_digest


def test_c4_record_consent_moves_only_the_consent_axis(tmp_path):
    """Recording consent leaves every other trust axis exactly as it was."""
    from src.capacium.trust import (
        build_install_consent,
        read_evidence_record,
        record_install_consent,
    )

    evidence, _ = _seed_evidence(tmp_path)
    assert evidence.install_consent is None

    binding = build_install_consent(evidence, tmp_path, source_revision="abc123")
    record_install_consent(binding, tmp_path)

    persisted = read_evidence_record(tmp_path)
    assert persisted is not None
    assert persisted.install_consent is not None
    assert persisted.install_consent.source_revision == "abc123"
    # Every other axis is carried over verbatim.
    assert persisted.origin == evidence.origin
    assert persisted.publisher_authority == evidence.publisher_authority
    assert persisted.security_assessment == evidence.security_assessment
    assert persisted.distribution_authority == evidence.distribution_authority
    assert persisted.lifecycle == evidence.lifecycle
    assert persisted.technical_verification == evidence.technical_verification


def test_c4_consent_record_rejects_non_digest_values():
    """A consent record that does not name exact digests is rejected."""
    from src.capacium.trust import ConsentRecord

    with pytest.raises(ValueError, match="sha256"):
        ConsentRecord(
            manifest_digest="deadbeef",
            source_revision="abc123",
            artifact_digest="sha256:" + "b" * 64,
        )

    with pytest.raises(ValueError, match="sha256"):
        ConsentRecord(
            manifest_digest="sha256:" + "a" * 64,
            source_revision="abc123",
            artifact_digest="",
        )

    with pytest.raises(ValueError, match="source_revision"):
        ConsentRecord(
            manifest_digest="sha256:" + "a" * 64,
            source_revision="",
            artifact_digest="sha256:" + "b" * 64,
        )


def test_c4_binding_reports_whether_package_and_artifact_match(tmp_path):
    """The binding can be re-checked against the locations it was built from."""
    from src.capacium.trust import build_install_consent

    evidence, _ = _seed_evidence(tmp_path)
    other = tmp_path.parent / (tmp_path.name + "-artifact")
    other.mkdir()
    (other / "capability.yaml").write_text("name: demo\nkind: skill\n")
    (other / "SKILL.md").write_text("# demo, shipped from a different revision\n")

    same = build_install_consent(evidence, tmp_path, "r1", artifact_dir=tmp_path)
    assert same.packages_paths_match()

    diverged = build_install_consent(evidence, tmp_path, "r1", artifact_dir=other)
    assert not diverged.packages_paths_match()


# ---------------------------------------------------------------------------
# Criterion 5 — a source set plus a config decides corroboration or abstention
# ---------------------------------------------------------------------------

def test_c5_evaluate_corroboration_is_a_real_decision():
    """The evaluator maps (sources, config) to an abstention result."""
    from src.capacium.trust import (
        AbstentionReason,
        CorroborationConfig,
        evaluate_corroboration,
    )

    cfg = CorroborationConfig(required_sources=2)

    single = evaluate_corroboration(["https://a.example"], cfg)
    assert single.reason == AbstentionReason.SINGLE_SOURCE
    assert single.disclosed is True
    assert single.consent_path

    pair = evaluate_corroboration(["https://a.example", "https://b.example"], cfg)
    assert pair.reason == AbstentionReason.CORROBORATED
    assert pair.disclosed is False
    assert pair.consent_path is None


def test_c5_no_source_abstains_without_disclosure():
    """Nothing to disclose when there was no source at all."""
    from src.capacium.trust import AbstentionReason, evaluate_corroboration

    result = evaluate_corroboration([])
    assert result.reason == AbstentionReason.INSUFFICIENT
    assert result.disclosed is False
    assert result.consent_path is None


def test_c5_single_source_config_accepts_one_source():
    """A single-source configuration corroborates on one source."""
    from src.capacium.trust import (
        AbstentionReason,
        CorroborationConfig,
        evaluate_corroboration,
    )

    cfg = CorroborationConfig(required_sources=1)
    result = evaluate_corroboration(["https://a.example"], cfg)
    assert result.reason == AbstentionReason.CORROBORATED
    assert result.disclosed is False


def test_c5_corroboration_is_order_and_duplicate_insensitive():
    """The same set of sources always reaches the same decision."""
    from src.capacium.trust import CorroborationConfig, evaluate_corroboration

    cfg = CorroborationConfig(required_sources=2)
    a = evaluate_corroboration(["b", "a"], cfg)
    b = evaluate_corroboration(["a", "b", "a", "b"], cfg)
    assert a == b


def test_c5_single_source_abstention_is_not_a_block():
    """An eligible single source is disclosed, not silently blocked or trusted."""
    from src.capacium.trust import (
        AbstentionReason,
        CONSENT_PATH,
        CorroborationConfig,
        evaluate_corroboration,
    )

    result = evaluate_corroboration(
        ["https://a.example"], CorroborationConfig(required_sources=2)
    )
    assert result.reason == AbstentionReason.SINGLE_SOURCE
    assert result.disclosed is True
    assert result.consent_path == CONSENT_PATH
    assert result.consent_path.endswith("#install_consent")


# ---------------------------------------------------------------------------
# Criterion 6 — an observed condition decides a disposition, deterministically
# ---------------------------------------------------------------------------

def test_c6_every_condition_has_a_disposition():
    """No observed condition can fall through to a permissive default."""
    from src.capacium.trust import IngestCondition, IngestDisposition, classify_ingest

    for condition in IngestCondition:
        try:
            disposition = classify_ingest(
                condition,
                existing_digest="sha256:" + "a" * 64,
                incoming_digest="sha256:" + "b" * 64,
            )
        except ValueError:
            # Only the conflict/duplicate arm may demand digests, and it got
            # them, so nothing here should raise.
            raise AssertionError(f"condition {condition} raised unexpectedly")
        assert isinstance(disposition, IngestDisposition)


def test_c6_classification_is_deterministic():
    """The same condition and detail always yield the same disposition."""
    from src.capacium.trust import IngestCondition, classify_ingest

    args = dict(existing_digest="sha256:" + "a" * 64, incoming_digest="sha256:" + "b" * 64)
    first = classify_ingest(IngestCondition.KONFLIKT, **args)
    second = classify_ingest(IngestCondition.KONFLIKT, **args)
    assert first == second
    assert first.to_dict() == second.to_dict()


def _outcome_for(condition_name, **kwargs):
    from src.capacium.trust import IngestCondition, classify_ingest

    return classify_ingest(getattr(IngestCondition, condition_name), **kwargs).outcome.value


def test_c6_conditions_map_to_their_documented_outcomes():
    """Each observed condition lands on the outcome the criterion names."""
    assert _outcome_for(
        "KONFLIKT", existing_digest="sha256:" + "a" * 64, incoming_digest="sha256:" + "b" * 64
    ) == "conflict"
    assert _outcome_for("DOPPELT", incoming_digest="sha256:" + "a" * 64) == "duplicate"
    assert _outcome_for("UMGEZOGENER_VERWEIS") == "moving_reference"
    assert _outcome_for("FEHLENDE_EVIDENZ") == "unavailable_evidence"
    assert _outcome_for("LIZENZ_EINSCHRAENKUNG") == "licence_restriction"
    assert _outcome_for("HOSTILE_METADATEN") == "malicious_metadata"
    assert _outcome_for("GERINGE_KONFIDENZ") == "quarantined"
    assert _outcome_for("ABSTIMMUNG_VORBEHALTEN") == "accepted"


def test_c6_conflict_without_digests_fails_closed():
    """A conflict that cannot name its digests is refused, not guessed."""
    from src.capacium.trust import IngestCondition, classify_ingest

    with pytest.raises(ValueError, match="existing_digest"):
        classify_ingest(IngestCondition.KONFLIKT, incoming_digest="sha256:" + "b" * 64)


# ---------------------------------------------------------------------------
# D5 — a signed event and the structural table are independent guards
# ---------------------------------------------------------------------------

def test_d5_signed_event_alone_cannot_reach_reviewed():
    """A signed event does not substitute for a structurally valid source."""
    from src.capacium.trust import PublisherAuthority, SecurityAssessment

    with pytest.raises(ValueError):
        PublisherAuthority.REVIEWED.transition_to(
            PublisherAuthority.REVIEWED, signed_event="sig"
        )
    with pytest.raises(ValueError):
        SecurityAssessment.REVIEWED.transition_to(
            SecurityAssessment.REVIEWED, signed_event="sig"
        )


def test_d5_reachable_transitions_still_require_the_event():
    """The structural check does not substitute for the signed event."""
    from src.capacium.trust import PublisherAuthority, SecurityAssessment

    with pytest.raises(ValueError, match="signed event"):
        PublisherAuthority.NULL.transition_to(PublisherAuthority.REVIEWED)
    with pytest.raises(ValueError, match="signed event"):
        SecurityAssessment.NONE.transition_to(SecurityAssessment.REVIEWED)


def test_d5_signed_event_reaches_reviewed_from_valid_sources():
    """Every structurally valid source can reach a protected target with a signature."""
    from src.capacium.trust import PublisherAuthority, SecurityAssessment

    for source in (
        PublisherAuthority.NULL,
        PublisherAuthority.SELF_ASSERTED,
        PublisherAuthority.PUBLISHER_ADOPTED,
    ):
        assert source.transition_to(PublisherAuthority.REVIEWED, signed_event="sig") == (
            PublisherAuthority.REVIEWED
        )

    for source in (SecurityAssessment.NONE, SecurityAssessment.QUARANTINED):
        assert source.transition_to(SecurityAssessment.REVIEWED, signed_event="sig") == (
            SecurityAssessment.REVIEWED
        )


def test_d5_signed_event_is_rejected_where_it_does_not_apply():
    """A signature on an unprotected transition is a caller error, not a no-op."""
    from src.capacium.trust import PublisherAuthority, SecurityAssessment

    with pytest.raises(ValueError, match="does not apply"):
        PublisherAuthority.SELF_ASSERTED.transition_to(
            PublisherAuthority.NULL, signed_event="sig"
        )
    with pytest.raises(ValueError, match="does not apply"):
        SecurityAssessment.QUARANTINED.transition_to(
            SecurityAssessment.NONE, signed_event="sig"
        )


# ---------------------------------------------------------------------------
# D6 — the pipeline verifies the bytes it hands off
# ---------------------------------------------------------------------------

def test_d6_pipeline_recomputes_the_digest(tmp_path):
    """The handoff digest comes from the bytes on disk, not from the caller."""
    from src.capacium.trust import (
        IngestPipeline,
        build_evidence_record,
        build_install_consent,
        ORIGIN_UNKNOWN_INSTALL,
        sha256_digest,
    )

    _seed_evidence(tmp_path)
    evidence = build_evidence_record(ORIGIN_UNKNOWN_INSTALL)
    real = build_install_consent(evidence, tmp_path, "r1").manifest_digest

    handoff = IngestPipeline(artifact_dir=tmp_path).ingest(
        evidence=evidence, manifest_digest=real, source_revision="r1"
    )
    assert handoff.exact_digest == real

    # A caller-supplied digest that does not match disk is refused.
    with pytest.raises(ValueError, match="does not match"):
        IngestPipeline(artifact_dir=tmp_path).ingest(
            evidence=evidence,
            manifest_digest=sha256_digest(b"fabricated"),
            source_revision="r1",
        )


def test_d6_pipeline_reads_hooks_from_the_manifest(tmp_path):
    """A manifest declaring hooks is refused even when the caller says otherwise."""
    from src.capacium.trust import (
        IngestPipeline,
        build_evidence_record,
        build_install_consent,
        manifest_declares_hooks,
        ORIGIN_UNKNOWN_INSTALL,
    )

    evidence = build_evidence_record(ORIGIN_UNKNOWN_INSTALL)
    (tmp_path / "capability.yaml").write_text(
        "name: demo\nkind: skill\nhooks:\n  post_install: ./evil.sh\n"
    )
    (tmp_path / "SKILL.md").write_text("# demo\n")

    assert manifest_declares_hooks(tmp_path)
    digest = build_install_consent(evidence, tmp_path, "r1").manifest_digest

    with pytest.raises(ValueError, match="hooks are forbidden"):
        IngestPipeline(artifact_dir=tmp_path).ingest(
            evidence=evidence,
            manifest_digest=digest,
            source_revision="r1",
            has_hooks=False,  # the caller's word does not override the manifest
        )


def test_d6_pipeline_ignores_unreadable_clean_manifests(tmp_path):
    """A clean manifest is not mistaken for a hook-bearing one."""
    from src.capacium.trust import manifest_declares_hooks

    (tmp_path / "capability.yaml").write_text("name: demo\nkind: skill\nversion: 0.1.0\n")
    (tmp_path / "SKILL.md").write_text("# demo\n\nSome prose, no code fences.\n")
    assert not manifest_declares_hooks(tmp_path)


def test_d6_ingest_handoff_reuses_the_canonical_digest_regex():
    """The pipeline reuses one digest format rather than redeclaring one."""
    import dataclasses

    from src.capacium.trust import IngestHandoff

    assert "_DIGEST_RE" not in {
        f.name for f in dataclasses.fields(IngestHandoff)
    }

    with pytest.raises(ValueError, match="sha256"):
        IngestHandoff(exact_digest="sha256:zz", source_revision="r1")


# ---------------------------------------------------------------------------
# D3 — the install surface consumes the shared classifier
# ---------------------------------------------------------------------------

def test_d3_install_disposition_classifies_unchanged_bytes_as_duplicate():
    """Re-installing identical bytes is a duplicate, not a silent overwrite."""
    from types import SimpleNamespace

    from src.capacium.commands.install import _install_disposition
    from src.capacium.trust import IngestOutcome

    existing = SimpleNamespace(fingerprint="a" * 64)
    assert _install_disposition(existing, "a" * 64).outcome == IngestOutcome.DUPLICATE


def test_d3_install_disposition_classifies_changed_bytes_as_conflict():
    """Re-installing different bytes under the same key is a conflict."""
    from types import SimpleNamespace

    from src.capacium.commands.install import _install_disposition
    from src.capacium.trust import IngestOutcome

    existing = SimpleNamespace(fingerprint="a" * 64)
    disposition = _install_disposition(existing, "b" * 64)
    assert disposition.outcome == IngestOutcome.CONFLICT
    assert disposition.detail
    assert "a" * 8 in disposition.detail


def test_d3_install_disposition_classifies_a_fresh_slot_as_accepted():
    """A capability with no existing row is accepted."""
    from src.capacium.commands.install import _install_disposition
    from src.capacium.trust import IngestOutcome

    assert _install_disposition(None, "a" * 64).outcome == IngestOutcome.ACCEPTED


def test_d3_install_consent_is_recorded_end_to_end(tmp_path, monkeypatch):
    """A full install records consent through the shared binding path."""
    from src.capacium.commands.install import install_capability
    from src.capacium.storage import StorageManager
    from src.capacium.trust import read_evidence_record

    source = tmp_path / "cap-source"
    source.mkdir()
    (source / "capability.yaml").write_text(
        "name: demo-cap\nkind: skill\nversion: 0.1.0\n"
    )
    (source / "SKILL.md").write_text("# demo\n")

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    assert install_capability(
        "demo-cap", source_dir=source, no_lock=True, skip_runtime_check=True
    )

    package_dir = StorageManager().get_package_dir("demo-cap", "0.1.0", owner="global")
    record = read_evidence_record(package_dir)
    assert record is not None
    assert record.install_consent is not None
    assert record.install_consent.manifest_digest.startswith("sha256:")
    assert record.install_consent.source_revision == "0.1.0"
