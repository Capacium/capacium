"""CAP117-SOURCE-009 dispatch 1: authenticated digest-bound external sources.

Red proofs for criteria 1-3 of the lane ``lane-cap117-source-009``:

1. An external source is bound to listing identity, exact version, artifact
   digest and required signature/provenance before download.
2. Credentials are ephemeral or opaque references and never appear in logs,
   JSON, lockfiles, local registry records or receipts.
3. Downloads enter quarantine, verify before mutation and use the same
   resolver, transaction and rollback path as registry-hosted artifacts.

Criterion 4 (distinct stable machine results), criterion 5 (receipt fields) and
criterion 6 (SkillWeave Pro-Pack fixture) are out of scope for this dispatch and
are intentionally not asserted here.

Every fixture is hermetic: no network is used, no real ``~/.capacium`` path is
touched, and Ed25519 verification is exercised through the module-level
``_verify_signature`` seam so the suite is independent of whether the host
interpreter has ``cryptography`` or ``PyNaCl`` available.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from capacium import registry_client
from capacium.registry_client import RegistryClient

# The red proof must surface as failing *tests* (pytest exit 1) on the base tip,
# not as a collection error (pytest exit 2). The external-source API does not
# exist on the base, so its names are bound lazily and their absence is reported
# by the autouse fixture below, once per test.
try:
    from capacium.registry_client import (
        CredentialRef,
        ExternalSourceError,
        ExternalSourceRequest,
        SourceSignature,
        VerifiedArtifact,
    )
except ImportError as exc:  # CAP117-SOURCE-009 red proof against the base tip
    _MISSING_EXTERNAL_SOURCE_API: Exception | None = exc
    CredentialRef = ExternalSourceError = ExternalSourceRequest = None  # type: ignore[assignment]
    SourceSignature = VerifiedArtifact = None  # type: ignore[assignment]
else:
    _MISSING_EXTERNAL_SOURCE_API = None

ARCHIVE = b"skillweave-pro-pack-1.2.3.tar.gz"
DIGEST = "sha256:" + hashlib.sha256(ARCHIVE).hexdigest()
SECRET = "swpk_live_deadbeefcafebabe"  # noqa: S105 - fixture value, never real


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self._body = data if isinstance(data, bytes) else data.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if any fixture reaches the network without opting in."""

    def boom(*args, **kwargs):
        raise AssertionError("network access attempted before it was stubbed")

    monkeypatch.setattr("urllib.request.urlopen", boom)


@pytest.fixture(autouse=True)
def _external_source_api_present():
    """Red proof against the base: every test fails while the API is missing."""
    if _MISSING_EXTERNAL_SOURCE_API is not None:
        pytest.fail(
            "capacium.registry_client does not yet expose the external source "
            f"API: {_MISSING_EXTERNAL_SOURCE_API}"
        )


@pytest.fixture(autouse=True)
def _clean_signing_backend(monkeypatch):
    """Make signature verification deterministic across interpreters.

    The default verifier delegates to ``capacium.signing``, whose backend is
    ``cryptography`` on some hosts and an OpenSSL subprocess on others. The
    proofs here care about *when* verification happens, not which backend runs
    it, so the seam is stubbed by default and overridden per test.
    """
    monkeypatch.setattr(registry_client, "_verify_signature", lambda *a, **k: True, raising=False)


def _signature() -> SourceSignature:
    return SourceSignature(
        public_key=b"\x01" * 32,
        signature=b"\x02" * 64,
        key_name="provenance-ed25519",
    )


def _request(**overrides) -> ExternalSourceRequest:
    fields = dict(
        listing_id="lst_skillweave_propack",
        owner="skillweave",
        name="pro-pack",
        version="1.2.3",
        digest=DIGEST,
        url="https://artifacts.example.test/skillweave/pro-pack-1.2.3.tar.gz",
        signature=_signature(),
        credential=CredentialRef("env:CAP_TEST_SOURCE_TOKEN"),
    )
    fields.update(overrides)
    return ExternalSourceRequest(**fields)


def _serve(monkeypatch, body: bytes = ARCHIVE, status: int = 200):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: FakeResponse(body, status)
    )


# --------------------------------------------------------------------------
# Criterion 1 - binding before download
# --------------------------------------------------------------------------


def test_request_binds_listing_identity_version_digest_and_signature():
    request = _request()
    assert request.listing_id == "lst_skillweave_propack"
    assert request.coordinate == "skillweave/pro-pack"
    assert request.version == "1.2.3"
    assert request.digest == DIGEST
    assert request.signature is not None
    assert request.protocol == registry_client.EXTERNAL_SOURCE_PROTOCOL


@pytest.mark.parametrize(
    "overrides",
    [
        {"listing_id": ""},
        {"owner": ""},
        {"name": ""},
    ],
    ids=["no-listing-id", "no-owner", "no-name"],
)
def test_listing_identity_is_required_before_download(overrides):
    with pytest.raises(ExternalSourceError):
        _request(**overrides).validate()


@pytest.mark.parametrize(
    "version", ["", "latest", "stable", "main", "^1.2.0", "1.x"]
)
def test_only_an_exact_version_is_accepted_before_download(version):
    with pytest.raises(ExternalSourceError):
        _request(version=version).validate()


@pytest.mark.parametrize("digest", ["", "sha256:", "sha256:zz", ARCHIVE.hex()])
def test_artifact_digest_is_mandatory_before_download(digest):
    with pytest.raises(ExternalSourceError):
        _request(digest=digest).validate()


def test_signature_or_provenance_is_required_before_download():
    with pytest.raises(ExternalSourceError):
        _request(signature=None).validate()


@pytest.mark.parametrize(
    "url",
    [
        "http://artifacts.example.test/a.tar.gz",
        "ftp://artifacts.example.test/a.tar.gz",
        "/local/path/a.tar.gz",
        "",
    ],
)
def test_only_https_sources_are_accepted_before_download(url):
    with pytest.raises(ExternalSourceError):
        _request(url=url).validate()


def test_invalid_request_never_reaches_the_network(tmp_path):
    client = RegistryClient()
    with pytest.raises(ExternalSourceError):
        client.fetch_external(
            _request(digest="sha256:nope"),
            dest_path=tmp_path / "cache" / "a.tar.gz",
            quarantine_dir=tmp_path / "quarantine",
        )


# --------------------------------------------------------------------------
# Criterion 2 - credentials are opaque and never persisted or logged
# --------------------------------------------------------------------------


def test_credential_reference_resolves_without_exposing_the_secret(monkeypatch):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    credential = CredentialRef("env:CAP_TEST_SOURCE_TOKEN")
    assert credential.resolve() == SECRET
    assert SECRET not in repr(credential)
    assert SECRET not in str(credential)
    assert SECRET not in json.dumps(credential.to_dict())


def test_literal_credentials_are_refused(monkeypatch):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    with pytest.raises(ExternalSourceError):
        CredentialRef(SECRET)


def test_fetch_never_logs_or_serialises_the_credential(monkeypatch, tmp_path):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    log_sink: list[str] = []
    client = RegistryClient(log_sink=log_sink)

    artifact = client.fetch_external(
        _request(),
        dest_path=tmp_path / "cache" / "pro-pack" / "1.2.3" / "artifact.tar.gz",
        quarantine_dir=tmp_path / "quarantine",
    )

    assert any(log_sink), "the external fetch must emit its redacted log lines"
    assert all(SECRET not in line for line in log_sink)
    assert SECRET not in json.dumps(artifact.to_dict())


def test_envelope_url_drops_query_string_and_userinfo(tmp_path, monkeypatch):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    request = _request(
        url=(
            "https://operator:swpk_live_signed@artifacts.example.test/pro-pack.tar.gz"
            "?X-Amz-Signature=swpk_live_signed&X-Amz-Credential=swpk_live_signed"
        )
    )
    client = RegistryClient()
    artifact = client.fetch_external(
        request,
        dest_path=tmp_path / "cache" / "pro-pack.tar.gz",
        quarantine_dir=tmp_path / "quarantine",
    )

    payload = json.dumps(artifact.to_dict())
    assert "swpk_live_signed" not in payload
    assert "operator:" not in payload
    assert artifact.url == (
        "https://artifacts.example.test/pro-pack.tar.gz"
    )


def test_http_failure_message_never_repeats_a_signed_query(monkeypatch, tmp_path):
    import urllib.error

    def raise_403(*args, **kwargs):
        raise urllib.error.HTTPError(
            url=(
                "https://artifacts.example.test/pro-pack.tar.gz"
                "?X-Amz-Signature=swpk_live_signed"
            ),
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_403)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    client = RegistryClient()
    with pytest.raises(ExternalSourceError) as excinfo:
        client.fetch_external(
            _request(
                url=(
                    "https://artifacts.example.test/pro-pack.tar.gz"
                    "?X-Amz-Signature=swpk_live_signed"
                )
            ),
            dest_path=tmp_path / "cache" / "pro-pack.tar.gz",
            quarantine_dir=tmp_path / "quarantine",
        )
    assert "swpk_live_signed" not in str(excinfo.value)


# --------------------------------------------------------------------------
# Criterion 3 - quarantine, verify before mutation, shared handoff path
# --------------------------------------------------------------------------


def test_artifact_is_quarantined_before_verification(monkeypatch, tmp_path):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    dest = tmp_path / "cache" / "pro-pack" / "1.2.3" / "artifact.tar.gz"
    quarantine = tmp_path / "quarantine"
    observed: dict[str, object] = {}

    def spy(pubkey, signature, data):
        observed["quarantine_files"] = sorted(
            p.name for p in quarantine.rglob("*") if p.is_file()
        )
        observed["quarantine_bytes"] = [
            p.read_bytes() for p in quarantine.rglob("*") if p.is_file()
        ]
        observed["dest_exists"] = dest.exists()
        return True

    monkeypatch.setattr(registry_client, "_verify_signature", spy)
    RegistryClient().fetch_external(
        _request(), dest_path=dest, quarantine_dir=quarantine
    )

    assert observed["quarantine_bytes"] == [ARCHIVE]
    assert observed["dest_exists"] is False


def test_digest_mismatch_fails_before_any_mutation(monkeypatch, tmp_path):
    _serve(monkeypatch, body=ARCHIVE + b"tampered")
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    dest = tmp_path / "cache" / "pro-pack" / "1.2.3" / "artifact.tar.gz"

    with pytest.raises(ExternalSourceError):
        RegistryClient().fetch_external(
            _request(),
            dest_path=dest,
            quarantine_dir=tmp_path / "quarantine",
        )

    assert dest.exists() is False
    assert list((tmp_path / "cache").rglob("*")) == []


def test_signature_failure_fails_before_any_mutation(monkeypatch, tmp_path):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    monkeypatch.setattr(registry_client, "_verify_signature", lambda *a, **k: False)
    dest = tmp_path / "cache" / "pro-pack" / "1.2.3" / "artifact.tar.gz"

    with pytest.raises(ExternalSourceError):
        RegistryClient().fetch_external(
            _request(),
            dest_path=dest,
            quarantine_dir=tmp_path / "quarantine",
        )

    assert dest.exists() is False


def test_verified_artifact_is_materialised_and_returns_an_envelope(
    monkeypatch, tmp_path
):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    dest = tmp_path / "cache" / "pro-pack" / "1.2.3" / "artifact.tar.gz"

    artifact = RegistryClient().fetch_external(
        _request(), dest_path=dest, quarantine_dir=tmp_path / "quarantine"
    )

    assert isinstance(artifact, VerifiedArtifact)
    assert dest.read_bytes() == ARCHIVE
    assert artifact.path == dest
    assert artifact.digest == DIGEST
    assert artifact.coordinate == "skillweave/pro-pack"
    assert artifact.version == "1.2.3"
    assert artifact.listing_id == "lst_skillweave_propack"
    assert artifact.source_class == "external-authenticated"
    assert artifact.verification == "digest+signature"
    assert artifact.protocol == registry_client.VERIFIED_ARTIFACT_PROTOCOL


def test_quarantine_is_drained_on_success(monkeypatch, tmp_path):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    quarantine = tmp_path / "quarantine"
    RegistryClient().fetch_external(
        _request(),
        dest_path=tmp_path / "cache" / "artifact.tar.gz",
        quarantine_dir=quarantine,
    )
    assert [p for p in quarantine.rglob("*") if p.is_file()] == []


def test_registry_hosted_and_external_downloads_share_one_handoff(
    monkeypatch, tmp_path
):
    """Criterion 3: same resolver/transaction path as registry-hosted artifacts.

    Both ``download`` (registry-hosted) and ``fetch_external`` must funnel the
    verified bytes through the one materialisation step, so a deployment that
    breaks that step breaks both identically.
    """
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    sentinel = RuntimeError("materialisation sentinel")
    monkeypatch.setattr(
        RegistryClient, "_materialize_artifact", lambda *a, **k: (_ for _ in ()).throw(sentinel)
    )

    with pytest.raises(RuntimeError, match="materialisation sentinel"):
        RegistryClient().download(
            name="pro-pack",
            version="1.2.3",
            registry_url="https://registry.example.test",
            dest_path=tmp_path / "hosted" / "artifact.tar.gz",
        )

    with pytest.raises(RuntimeError, match="materialisation sentinel"):
        RegistryClient().fetch_external(
            _request(),
            dest_path=tmp_path / "external" / "artifact.tar.gz",
            quarantine_dir=tmp_path / "quarantine",
        )


def test_missing_credential_environment_refuses_before_download(monkeypatch, tmp_path):
    monkeypatch.delenv("CAP_TEST_SOURCE_TOKEN", raising=False)
    with pytest.raises(ExternalSourceError):
        RegistryClient().fetch_external(
            _request(),
            dest_path=tmp_path / "cache" / "artifact.tar.gz",
            quarantine_dir=tmp_path / "quarantine",
        )


def test_artifact_source_envelope_round_trips_as_json(monkeypatch, tmp_path):
    _serve(monkeypatch)
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    artifact = RegistryClient().fetch_external(
        _request(),
        dest_path=tmp_path / "cache" / "artifact.tar.gz",
        quarantine_dir=tmp_path / "quarantine",
    )
    payload = artifact.to_dict()
    assert payload["protocol"] == registry_client.VERIFIED_ARTIFACT_PROTOCOL
    assert payload["digest"] == DIGEST
    assert Path(payload["path"]) == tmp_path / "cache" / "artifact.tar.gz"
    assert SECRET not in json.dumps(payload)
