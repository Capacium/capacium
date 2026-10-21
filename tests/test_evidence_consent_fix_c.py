"""CAP117-EVIDENCE-005 Fix round C — criterion 7: ingest → resolver handoff.

Criterion 7 (verbatim):

    No ingest path executes package hooks; an approved install enters the normal
    resolver and transaction path only with an exact digest.

Fix round B shipped the verified :class:`IngestPipeline` but stopped at the
:class:`IngestHandoff` value; nothing bound that handoff to the resolver that
``install.py`` actually runs, so D2 stayed open. RESOLVE-003 (``Resolver`` in
``src/capacium/commands/_resolve.py``) is now integrated in this tip, so the
handoff can be handed a real catalog and resolve through the normal path.

The transaction half of criterion 7 (the mutation journal in ``install.py``)
belongs to TRANSACT-004 and is deliberately not touched here. These proofs
therefore pin the two things this lane owns: the typed handoff, and the name of
the contact point the transaction enters.

All proofs are red at the Fix-B tip: ``bind_handoff_to_resolver`` and
``ResolverHandoff`` do not exist there.
"""

import hashlib
from pathlib import Path

import pytest

from src.capacium.commands._resolve import Resolver


def _artifact_bytes(tmp_path: Path) -> None:
    (tmp_path / "capability.yaml").write_text(
        "name: demo\nkind: skill\nversion: 0.1.0\n"
    )
    (tmp_path / "SKILL.md").write_text("# demo\n\nSome prose.\n")


def _handoff(tmp_path: Path):
    """Produce a real IngestHandoff by digesting bytes on disk."""
    from src.capacium.trust import (
        IngestPipeline,
        ORIGIN_UNKNOWN_INSTALL,
        build_evidence_record,
        sha256_digest,
    )

    _artifact_bytes(tmp_path)
    from src.capacium.fingerprint import compute_fingerprint, evidence_exclude_patterns

    digest = sha256_digest(
        compute_fingerprint(
            tmp_path, exclude_patterns=evidence_exclude_patterns()
        ).encode("ascii")
    )
    return IngestPipeline(artifact_dir=tmp_path).ingest(
        evidence=build_evidence_record(ORIGIN_UNKNOWN_INSTALL),
        manifest_digest=digest,
        source_revision="rev-c7",
    )


def _catalog(digest: str, version: str = "0.1.0") -> dict:
    return {
        "acme/demo": {
            version: {
                "kind": "skill",
                "artifact_digest": digest,
                "source_revision": "rev-c7",
                "deps": {},
            }
        }
    }


# ---------------------------------------------------------------------------
# The handoff binds an exact digest into the plan the resolver produces
# ---------------------------------------------------------------------------

def test_c7_resolver_handoff_binds_the_exact_digest_into_the_plan(tmp_path):
    """An approved ingest resolves through the normal Resolver with its digest."""
    from src.capacium.trust import bind_handoff_to_resolver

    handoff = _handoff(tmp_path)
    bound = bind_handoff_to_resolver(
        handoff, _catalog(handoff.exact_digest), "acme/demo"
    )

    plan = Resolver(bound.catalog).resolve(bound.root, bound.root_version)

    assert plan.nodes["acme/demo"].artifact_digest == handoff.exact_digest
    assert bound.exact_digest == handoff.exact_digest
    # The resolver output is the value the transaction commits from.
    assert plan.to_lock()["nodes"]["acme/demo"]["artifact_digest"] == (
        handoff.exact_digest
    )


def test_c7_src_entry_resolves_the_handoff_through_the_normal_resolver(tmp_path):
    """The src-side entry runs the normal Resolver, not a private planner."""
    from src.capacium.trust import resolve_ingest_handoff

    handoff = _handoff(tmp_path)
    plan = resolve_ingest_handoff(
        handoff, _catalog(handoff.exact_digest), "acme/demo"
    )

    assert plan.nodes["acme/demo"].artifact_digest == handoff.exact_digest
    assert plan.root_coordinate == "acme/demo"
    assert plan.root_version == "0.1.0"
    # Same output as driving the Resolver directly: one planner, one path.
    direct = Resolver(_catalog(handoff.exact_digest)).resolve("acme/demo", "0.1.0")
    assert plan.to_lock() == direct.to_lock()


def test_c7_src_entry_refuses_bytes_that_do_not_match_the_handoff(tmp_path):
    """The src-side entry fails closed on foreign bytes before resolving."""
    from src.capacium.trust import resolve_ingest_handoff

    handoff = _handoff(tmp_path)
    foreign = hashlib.sha256(b"foreign-entry").hexdigest()
    with pytest.raises(ValueError, match="exact_digest|digest"):
        resolve_ingest_handoff(handoff, _catalog(foreign), "acme/demo")


def test_c7_handoff_pins_to_the_digest_matching_version(tmp_path):
    """Only the version whose bytes match the handoff is resolved."""
    from src.capacium.trust import bind_handoff_to_resolver

    handoff = _handoff(tmp_path)
    other = hashlib.sha256(b"other").hexdigest()
    catalog = {
        "acme/demo": {
            "0.1.0": {"kind": "skill", "artifact_digest": other, "deps": {}},
            "0.2.0": {
                "kind": "skill",
                "artifact_digest": handoff.exact_digest,
                "deps": {},
            },
        }
    }

    bound = bind_handoff_to_resolver(handoff, catalog, "acme/demo")
    assert bound.root_version == "0.2.0"

    plan = Resolver(bound.catalog).resolve(bound.root, bound.root_version)
    assert plan.nodes["acme/demo"].artifact_digest == handoff.exact_digest


# ---------------------------------------------------------------------------
# Fail closed: no digest match means no resolver path
# ---------------------------------------------------------------------------

def test_c7_handoff_refuses_a_catalog_with_foreign_bytes(tmp_path):
    """A catalog whose digest differs from the handoff never reaches the resolver."""
    from src.capacium.trust import bind_handoff_to_resolver

    handoff = _handoff(tmp_path)
    foreign = hashlib.sha256(b"foreign").hexdigest()

    with pytest.raises(ValueError, match="exact_digest|digest"):
        bind_handoff_to_resolver(handoff, _catalog(foreign), "acme/demo")


def test_c7_handoff_refuses_a_missing_root(tmp_path):
    """A handoff for a coordinate absent from the catalog fails closed."""
    from src.capacium.trust import bind_handoff_to_resolver

    handoff = _handoff(tmp_path)
    with pytest.raises(ValueError, match="acme/demo|not in catalog|missing"):
        bind_handoff_to_resolver(handoff, {}, "acme/demo")


def test_c7_handoff_requires_an_ingest_value_not_a_bare_digest(tmp_path):
    """A raw digest string cannot enter the resolver path — only an IngestHandoff."""
    from src.capacium.trust import bind_handoff_to_resolver

    handoff = _handoff(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        bind_handoff_to_resolver(
            handoff.exact_digest, _catalog(handoff.exact_digest), "acme/demo"
        )


# ---------------------------------------------------------------------------
# No ingest path executes package hooks
# ---------------------------------------------------------------------------

def test_c7_hook_declaring_artifact_never_produces_a_handoff(tmp_path):
    """A hook-declaring manifest is refused before any handoff exists."""
    from src.capacium.trust import (
        IngestPipeline,
        ORIGIN_UNKNOWN_INSTALL,
        build_evidence_record,
        build_install_consent,
    )

    (tmp_path / "capability.yaml").write_text(
        "name: demo\nkind: skill\nhooks:\n  post_install: ./evil.sh\n"
    )
    (tmp_path / "SKILL.md").write_text("# demo\n")
    evidence = build_evidence_record(ORIGIN_UNKNOWN_INSTALL)
    digest = build_install_consent(evidence, tmp_path, "rev-c7").manifest_digest

    with pytest.raises(ValueError, match="hooks are forbidden"):
        IngestPipeline(artifact_dir=tmp_path).ingest(
            evidence=evidence, manifest_digest=digest, source_revision="rev-c7"
        )


# ---------------------------------------------------------------------------
# The contact point the transaction enters is named
# ---------------------------------------------------------------------------

def test_c7_the_transaction_contact_point_is_named():
    """The handoff names the install-transaction contact point it feeds."""
    from src.capacium import trust

    assert isinstance(trust.RESOLVER_CONTACT_POINT, str)
    assert trust.RESOLVER_CONTACT_POINT == "install.install_capability:resolve"


def test_c7_resolver_handoff_is_typed_and_carries_the_binding():
    """ResolverHandoff exposes exactly what the transaction needs to resolve."""
    import dataclasses

    from src.capacium.trust import ResolverHandoff

    fields = {f.name for f in dataclasses.fields(ResolverHandoff)}
    assert {"exact_digest", "source_revision", "catalog", "root", "root_version"} <= fields
