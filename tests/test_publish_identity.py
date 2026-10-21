"""CAP117-IDENTITY-007 — publisher identity preflight and safe claim reads.

Criteria 1-3 (dispatch 1) and 4-6 (dispatch 2):

1. Verified aliases and previous coordinates resolve to one stable listing ID
   and expose the canonical coordinate and transition evidence.
2. An untrusted ``replaces`` or previous-identity claim cannot redirect, merge
   or capture a listing.
3. Ordinary transitions require authenticated authority for both sides;
   administrative recovery is explicit, reasoned and auditable.
4. ``cap publish`` validates exact-case owner/repository identity and
   previous-identity claims before upload and returns stable JSON diagnostics.
5. The Publisher Action consumes the same JSON contract, and Exchange release
   work stays separate from CLI/publisher-action releases.
6. Valid move, fork, mirror, duplicate, malformed claim and hostile takeover
   fixtures pass.

The red proofs below are written against ``publish_capability`` and the
``listing_identity`` contract module.  They fail on the base because neither the
preflight nor the stable JSON diagnostics exist yet.
"""

import json
from unittest import mock

from capacium.commands.publish import publish_capability
from capacium.registry_client import RegistryClientError

try:  # base commit: the preflight contract module does not exist yet
    from capacium.listing_identity import (
        AUTH_VERIFIED,
        CLAIM_AUTHORITY_UNVERIFIED,
        CLAIM_CASE_MISMATCH,
        CLAIM_MALFORMED,
        CLAIM_SELF_REFERENCE,
        IDENTITY_SCHEMA_VERSION,
        OWNER_CASE_MISMATCH,
        REPOSITORY_IDENTITY_MISMATCH,
        REPOSITORY_MISSING,
    )
except ImportError:  # pragma: no cover - true only on the base commit
    # Keep collection alive so the red proofs below surface as *failing tests*
    # (exit 1) rather than as a collection error (exit 2).
    AUTH_VERIFIED = None
    CLAIM_AUTHORITY_UNVERIFIED = None
    CLAIM_CASE_MISMATCH = None
    CLAIM_MALFORMED = None
    CLAIM_SELF_REFERENCE = None
    IDENTITY_SCHEMA_VERSION = None
    OWNER_CASE_MISMATCH = None
    REPOSITORY_IDENTITY_MISMATCH = None
    REPOSITORY_MISSING = None

_MOVE_MANIFEST = """\
kind: bundle
name: skillweave
version: 1.0.2
description: SkillWeave bundle
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
replaces:
  - typelicious/skillweave
previous_identities:
  - owner: typelicious
    name: skillweave
    repository: https://github.com/typelicious/skillweave
"""


def _manifest(tmp_path, text: str, name: str = "capability.yaml"):
    path = tmp_path / name
    path.write_text(text)
    return path


def _json_result(capsys) -> dict:
    out = capsys.readouterr().out
    return json.loads(out.strip())


def _published_ok():
    return {
        "canonical_name": "LangeVC/skillweave",
        "kind": "bundle",
        "trust_state": "discovered",
        "created": True,
    }


# --- Criterion 2: a claim never grants authority on its own ------------------


def test_untrusted_replaces_claim_does_not_grant_authority(tmp_path, capsys):
    """A ``replaces`` coordinate pointing at a different repository is carried
    to the registry but never granted identity authority: the listing ID stays
    the authenticated owner's and the claim is reported as unverified."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert publish_capability(manifest, json_output=True) is True

    payload = instance.publish.call_args.args[0]
    assert payload["canonical_listing_id"] == "LangeVC/skillweave"
    assert payload["replaces"] == ["typelicious/skillweave"]

    report = _json_result(capsys)
    claims = report["claims"]
    assert len(claims) == 2
    for claim in claims:
        assert claim["status"] == "unverified"
        assert claim["authority_granted"] is False
        assert claim["authority"] is None
        assert CLAIM_AUTHORITY_UNVERIFIED in claim["codes"]
    assert report["transition_evidence"] == []


def test_hostile_replaces_claim_cannot_capture_another_listing(
    tmp_path, capsys
):
    """A claim that does not describe the publishing repository cannot be used
    to redirect or capture the coordinate it names."""
    text = """\
kind: bundle
name: skillweave
version: 9.9.9
owner: attacker
repository: https://github.com/attacker/skillweave
replaces:
  - LangeVC/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = {
            "canonical_name": "attacker/skillweave",
            "kind": "bundle",
            "trust_state": "discovered",
            "created": True,
        }
        assert publish_capability(manifest, json_output=True) is True

    report = _json_result(capsys)
    claim = report["claims"][0]
    assert claim["from"] == "LangeVC/skillweave"
    assert claim["to"] == "attacker/skillweave"
    assert claim["authority_granted"] is False
    assert report["listing_id"] == "attacker/skillweave"
    assert report["canonical_coordinate"]["owner"] == "attacker"


def test_claim_without_repository_is_a_hard_reject(tmp_path, capsys):
    """A previous-identity claim that names no repository cannot be verified at
    all, so the preflight refuses the upload instead of shipping a guess."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
previous_identities:
  - owner: typelicious
    name: skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert report["exit_code"] == 1
    assert CLAIM_MALFORMED in report["codes"]


def test_self_referential_claim_is_refused(tmp_path, capsys):
    """A listing cannot claim to replace itself — that would be a silent
    identity rewrite dressed up as a transition."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
replaces:
  - LangeVC/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert CLAIM_SELF_REFERENCE in report["codes"]


def test_claim_exact_case_mismatch_is_refused(tmp_path, capsys):
    """A previous identity whose owner case does not match the repository it
    cites cannot be verified and is refused."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
previous_identities:
  - owner: typelicious
    name: skillweave
    repository: https://github.com/Typelicious/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert CLAIM_CASE_MISMATCH in report["codes"]


# --- Criterion 4: exact-case owner/repository identity ----------------------


def test_owner_case_mismatch_against_repository_is_rejected(tmp_path, capsys):
    """``owner`` and the repository owner path must match exactly; a
    case-only difference is a different namespace and is refused, not coerced."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: langevc
repository: https://github.com/LangeVC/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert OWNER_CASE_MISMATCH in report["codes"]


def test_repository_identity_mismatch_is_rejected(tmp_path, capsys):
    """A repository that belongs to another owner/name than the manifest
    claims is reported, not silently accepted as the listing's source."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/someone-else/other-repo
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert REPOSITORY_IDENTITY_MISMATCH in report["codes"]


def test_claim_requires_repository_when_manifest_has_no_repository(
    tmp_path, capsys
):
    """An identity claim with no repository to anchor it is refused."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
previous_identities:
  - owner: typelicious
    name: skillweave
    repository: https://github.com/typelicious/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert REPOSITORY_MISSING in report["codes"]


# --- Criterion 1 + 3: authorized transitions expose evidence ----------------


def test_verified_move_exposes_canonical_coordinate_and_evidence(
    tmp_path, capsys
):
    """When a verifying AuthorityEvent authenticates both sides of a move, the
    claim is granted, the canonical coordinate is exposed and the transition
    evidence records the signed event that authorized it."""
    from capacium.listing_identity import AuthorityEvent

    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    event = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "a" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[event]
            )
            is True
        )

    payload = instance.publish.call_args.args[0]
    assert payload["canonical_listing_id"] == "LangeVC/skillweave"

    report = _json_result(capsys)
    assert report["canonical_coordinate"] == {
        "owner": "LangeVC",
        "name": "skillweave",
        "version": "1.0.2",
        "listing_id": "LangeVC/skillweave",
    }
    granted = [
        c for c in report["claims"] if c["authority_granted"]
    ]
    assert granted, "the signed event must authorize both sides"
    evidence = report["transition_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["from_id"] == "typelicious/skillweave"
    assert evidence[0]["to_id"] == "LangeVC/skillweave"
    assert evidence[0]["evidence_digest"] == "sha256:" + "a" * 64
    assert evidence[0]["issuer"] == "exchange-review"


def test_one_sided_authority_does_not_authorize_a_transition(
    tmp_path, capsys
):
    """An ordinary transition needs authenticated authority on *both* sides: a
    signed event that only authenticates the destination leaves the move
    unauthorized."""
    from capacium.listing_identity import AuthorityEvent

    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    event = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority=None,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "b" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[event]
            )
            is True
        )

    report = _json_result(capsys)
    assert report["transition_evidence"] == []
    assert all(not c["authority_granted"] for c in report["claims"])


def test_administrative_recovery_requires_reason_and_signed_event(
    tmp_path, capsys
):
    """Administrative recovery is explicit: without a signed event it is
    refused; with one it is granted and the reason is recorded auditable."""
    from capacium.listing_identity import AuthorityEvent

    hostile = """\
kind: bundle
name: skillweave
version: 2.0.0
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
replaces:
  - typelicious/skillweave
"""
    manifest = _manifest(tmp_path, hostile)

    unsigned = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest=None,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
        administrative=True,
        reason="publisher merged repositories",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[unsigned]
            )
            is True
        )
    report = _json_result(capsys)
    assert report["transition_evidence"] == []

    signed = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "c" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
        administrative=True,
        reason="publisher merged repositories",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[signed]
            )
            is True
        )
    report = _json_result(capsys)
    assert len(report["transition_evidence"]) == 1
    assert report["transition_evidence"][0]["administrative"] is True
    assert (
        report["transition_evidence"][0]["reason"]
        == "publisher merged repositories"
    )


def test_administrative_event_without_reason_is_not_authority(tmp_path, capsys):
    """An administrative event that is signed but carries no reason is not
    authority: the recovery has to say what it is recovering from."""
    from capacium.listing_identity import AuthorityEvent

    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    event = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "d" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
        administrative=True,
        reason="   ",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[event]
            )
            is True
        )

    report = _json_result(capsys)
    assert report["transition_evidence"] == []
    assert all(not c["authority_granted"] for c in report["claims"])


def test_event_about_another_subject_is_not_authority(tmp_path, capsys):
    """A signed event that authenticates both ends but is *about* a different
    listing cannot lend authority to the listing being published."""
    from capacium.listing_identity import AuthorityEvent

    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    event = AuthorityEvent(
        subject_id="someone-else/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "e" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[event]
            )
            is True
        )

    report = _json_result(capsys)
    assert report["transition_evidence"] == []
    assert all(not c["authority_granted"] for c in report["claims"])


def test_event_with_mismatched_endpoints_is_not_authority(tmp_path, capsys):
    """A signed event authorizes *one* transition: an event whose endpoints do
    not name the claim's from/to coordinates cannot lend authority to it."""
    from capacium.listing_identity import AuthorityEvent

    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    event = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="attacker/other",
        to_id="LangeVC/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "f" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[event]
            )
            is True
        )

    report = _json_result(capsys)
    assert report["transition_evidence"] == []
    assert all(not c["authority_granted"] for c in report["claims"])
    assert all(
        CLAIM_AUTHORITY_UNVERIFIED in c["codes"] for c in report["claims"]
    )


def test_event_needs_authenticated_authority_not_merely_truthy(
    tmp_path, capsys
):
    """Both ends must carry the authenticated ``verified`` marker: a truthy
    but unauthenticated marker (e.g. ``pending``) is not authority."""
    from capacium.listing_identity import AuthorityEvent

    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    event = AuthorityEvent(
        subject_id="LangeVC/skillweave",
        from_id="typelicious/skillweave",
        to_id="LangeVC/skillweave",
        from_authority="pending",
        to_authority="pending",
        evidence_digest="sha256:" + "1" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert (
            publish_capability(
                manifest, json_output=True, authority_events=[event]
            )
            is True
        )

    report = _json_result(capsys)
    assert report["transition_evidence"] == []
    assert all(not c["authority_granted"] for c in report["claims"])


def test_scalar_replaces_is_one_malformed_claim_not_a_crash(tmp_path, capsys):
    """A manifest that carries a scalar where the schema wants a list must
    still produce the machine contract: one malformed entry, a hard reject,
    and never a traceback or an empty stdout."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
replaces: 12345
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        assert publish_capability(manifest, json_output=True) is False
        instance.publish.assert_not_called()

    report = _json_result(capsys)
    assert report["valid"] is False
    assert report["exit_code"] == 1
    assert CLAIM_MALFORMED in report["codes"]
    assert report["claims"] == []


def test_scalar_string_replaces_is_not_split_per_character(tmp_path, capsys):
    """A scalar string claim is a single coordinate, not one claim per
    character: the listing ID must never be derived from a mangled read."""
    text = """\
kind: bundle
name: skillweave
version: 1.0.2
owner: LangeVC
repository: https://github.com/LangeVC/skillweave
replaces: typelicious/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert publish_capability(manifest, json_output=True) is True

    report = _json_result(capsys)
    assert [c["from"] for c in report["claims"]] == ["typelicious/skillweave"]
    assert report["listing_id"] == "LangeVC/skillweave"


# --- The machine-readable mode owns stdout ----------------------------------


def test_json_output_is_the_only_stdout_document(tmp_path, capsys):
    """Diagnostics must not be interleaved with prose on stdout when the
    machine-readable mode is requested."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        publish_capability(manifest, json_output=True)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["command"] == "publish"
    assert isinstance(parsed["valid"], bool)


# --- Criterion 5: the JSON contract the Publisher Action consumes -----------


def test_json_diagnostics_contract_is_stable(tmp_path, capsys):
    """A single JSON document with a pinned schema version and stable, sorted,
    deduplicated diagnostic codes — the publisher Action consumes exactly this
    and cannot be released independently of the contract it depends on."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        publish_capability(manifest, json_output=True)

    report = _json_result(capsys)
    assert report["schema_version"] == IDENTITY_SCHEMA_VERSION
    assert report["command"] == "publish"
    assert isinstance(report["valid"], bool)
    assert isinstance(report["exit_code"], int)
    assert report["codes"] == sorted(report["codes"])
    assert len(report["codes"]) == len(set(report["codes"]))
    assert report["codes"] == [CLAIM_AUTHORITY_UNVERIFIED]
    for diagnostic in report["diagnostics"]:
        assert set(diagnostic) >= {"code", "severity", "field", "message"}
        assert diagnostic["severity"] in ("error", "warning", "info")


# --- Criterion 6: the full fixture matrix -----------------------------------
#
# One fixture per identity shape the preflight must survive.  ``move``,
# ``malformed`` and ``hostile`` already have dedicated proofs above (the
# verified move, the scalar/missing-repository claims and the capture attempt);
# the fixtures below cover the shapes those proofs do not: a legitimate fork, a
# mirror that is not a takeover, and a duplicate publish that stays a plain 409.


def test_fork_under_a_new_owner_publishes_without_granting_the_upstream(
    tmp_path, capsys,
):
    """A fork publishes under its own authenticated owner.  The upstream
    coordinate is carried as an unverified assertion — a fork is not a move and
    must not capture the listing it was forked from."""
    text = """\
kind: bundle
name: skillweave
version: 0.1.0
owner: forker
repository: https://github.com/forker/skillweave
replaces:
  - LangeVC/skillweave
"""
    manifest = _manifest(tmp_path, text)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = {
            "canonical_name": "forker/skillweave",
            "kind": "bundle",
            "trust_state": "discovered",
            "created": True,
        }
        assert publish_capability(manifest, json_output=True) is True
        payload = instance.publish.call_args.args[0]

    assert payload["canonical_listing_id"] == "forker/skillweave"
    report = _json_result(capsys)
    claim = report["claims"][0]
    assert claim["from"] == "LangeVC/skillweave"
    assert claim["to"] == "forker/skillweave"
    assert claim["status"] == "unverified"
    assert claim["authority_granted"] is False
    assert report["transition_evidence"] == []


def test_mirror_of_a_signed_move_is_carried_not_obeyed(tmp_path, capsys):
    """A mirror re-publishes a listing whose move was already authorized by a
    signed event naming a different subject: the evidence does not transfer, so
    the mirror's own claim stays unverified and nothing is captured."""
    from capacium.listing_identity import AuthorityEvent

    text = """\
kind: bundle
name: skillweave
version: 3.1.0
owner: mirrorco
repository: https://github.com/mirrorco/skillweave
replaces:
  - LangeVC/skillweave
"""
    manifest = _manifest(tmp_path, text)
    event = AuthorityEvent(
        subject_id="somebody-else/skillweave",
        from_id="LangeVC/skillweave",
        to_id="somebody-else/skillweave",
        from_authority=AUTH_VERIFIED,
        to_authority=AUTH_VERIFIED,
        evidence_digest="sha256:" + "d" * 64,
        issued_at="2026-10-21T00:00:00Z",
        issuer="exchange-review",
    )
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = {
            "canonical_name": "mirrorco/skillweave",
            "kind": "bundle",
            "trust_state": "discovered",
            "created": True,
        }
        assert (
            publish_capability(manifest, json_output=True, authority_events=[event])
            is True
        )

    report = _json_result(capsys)
    assert all(not c["authority_granted"] for c in report["claims"])
    assert report["transition_evidence"] == []
    assert report["canonical_coordinate"]["owner"] == "mirrorco"


def test_duplicate_publish_is_a_plain_conflict_without_losing_claims(
    tmp_path, capsys,
):
    """A duplicate publish is rejected by the registry (409) and the identity
    claims still reach the machine contract — a rejection must not swallow the
    record of what was claimed."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.side_effect = RegistryClientError(
            "HTTP 409 from http://example.com/v2/publish: Capability already exists",
            status_code=409,
        )
        assert publish_capability(manifest, json_output=True) is False

    report = _json_result(capsys)
    assert report["valid"] is False
    assert report["exit_code"] == 1
    assert "publish.registry.conflict" in report["codes"]
    assert [c["from"] for c in report["claims"]] == [
        "typelicious/skillweave",
        "typelicious/skillweave",
    ]
    assert report["listing_id"] == "LangeVC/skillweave"


# --- Existing publish behaviour is preserved --------------------------------


def test_soft_unverified_claim_still_publishes(tmp_path, capsys):
    """A structurally valid but unauthorized claim is a warning, not a wall:
    the publisher still uploads and keeps the claim on the record."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.return_value = _published_ok()
        assert publish_capability(manifest) is True
        instance.publish.assert_called_once()

    output = capsys.readouterr().out
    # Assert on the diagnostic *message*, not the bare word "unverified": the
    # tmp_path derives from this test's own name, so a bare substring match
    # would pass against the base for the wrong reason.
    assert "no signed authority event authenticates both sides" in output


def test_registry_error_still_reports_json(tmp_path, capsys):
    """A registry failure is reported through the same stable contract."""
    manifest = _manifest(tmp_path, _MOVE_MANIFEST)
    with mock.patch("capacium.commands.publish.RegistryClient") as mock_client:
        instance = mock_client.return_value
        instance.publish.side_effect = RegistryClientError(
            "HTTP 409 from http://example.com/v2/publish: Capability already exists",
            status_code=409,
        )
        assert publish_capability(manifest, json_output=True) is False

    report = _json_result(capsys)
    assert report["valid"] is False
    assert report["exit_code"] == 1
    assert "publish.registry.conflict" in report["codes"]
