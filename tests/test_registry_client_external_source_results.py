"""CAP117-SOURCE-009 dispatch 2: machine results, receipts and the install fixture.

Red proofs for criteria 4-6 of the lane ``lane-cap117-source-009``:

4. Authentication, expiry, redirect, transport and integrity failures have
   distinct stable machine results.
5. Receipts record source class and verification evidence without customer,
   price, licence or entitlement data.
6. The SkillWeave Pro-Pack reference fixture installs successfully; denial and
   digest mismatch fail before local mutation.

Criteria 1-3 are proven in ``test_registry_client_external_source.py`` and are
not re-asserted here.

Every fixture is hermetic: no network is used, no real ``~/.capacium`` path is
touched, and Ed25519 verification is exercised through the module-level
``_verify_signature`` seam so the suite is independent of whether the host
interpreter has ``cryptography`` or ``PyNaCl`` available.
"""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from capacium import registry_client

# The red proof must surface as failing *tests* (pytest exit 1) on the base tip,
# not as a collection error (pytest exit 2). The external-source API does not
# exist on the base, so its names are bound lazily and their absence is reported
# by the autouse fixture below, once per test.
try:
    from capacium.registry_client import (
        CredentialRef,
        ExternalSourceAuthenticationError,
        ExternalSourceError,
        ExternalSourceExpiryError,
        ExternalSourceIntegrityError,
        ExternalSourceReceipt,
        ExternalSourceRedirectError,
        ExternalSourceRequest,
        ExternalSourceTransportError,
        RegistryClient,
        SourceSignature,
    )
except ImportError as exc:  # CAP117-SOURCE-009 red proof against the base tip
    _MISSING_EXTERNAL_SOURCE_API: Exception | None = exc
    (
        CredentialRef,
        ExternalSourceAuthenticationError,
        ExternalSourceError,
        ExternalSourceExpiryError,
        ExternalSourceIntegrityError,
        ExternalSourceReceipt,
        ExternalSourceRedirectError,
        ExternalSourceRequest,
        ExternalSourceTransportError,
        RegistryClient,
        SourceSignature,
    ) = (None,) * 11
else:
    _MISSING_EXTERNAL_SOURCE_API = None

ARCHIVE = b"skillweave-pro-pack-1.2.3.tar.gz"
DIGEST = "sha256:" + hashlib.sha256(ARCHIVE).hexdigest()
SECRET = "swpk_live_deadbeefcafebabe"  # noqa: S105 - fixture value, never real

#: The five failure classes criterion 4 requires to be distinct and stable.
REQUIRED_RESULT_NAMES = (
    "RESULT_AUTHENTICATION_DENIED",
    "RESULT_CREDENTIAL_EXPIRED",
    "RESULT_REDIRECT_REFUSED",
    "RESULT_TRANSPORT_FAILED",
    "RESULT_INTEGRITY_FAILED",
)

#: Fields a receipt must never carry (criterion 5).
FORBIDDEN_RECEIPT_FIELDS = (
    "customer",
    "customer_id",
    "price",
    "licence",
    "license",
    "entitlement",
    "credential",
    "token",
    "secret",
)


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200, url: str | None = None):
        self._body = data if isinstance(data, bytes) else data.encode("utf-8")
        self.status = status
        self._url = url

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url or ""

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
    """Make signature verification deterministic across interpreters."""
    monkeypatch.setattr(
        registry_client, "_verify_signature", lambda *a, **k: True, raising=False
    )


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


def _serve(monkeypatch, body: bytes = ARCHIVE, status: int = 200, url: str | None = None):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: FakeResponse(body, status, url)
    )


def _raise_http(monkeypatch, code: int, location: str | None = None):
    headers = {"Location": location} if location else None

    def raise_http_error(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://artifacts.example.test/pro-pack.tar.gz",
            code=code,
            msg=f"HTTP {code}",
            hdrs=headers,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)


def _raise_transport(monkeypatch, reason: Exception | None = None):
    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError(reason or socket.timeout("timed out"))

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)


def _fetch(client, tmp_path, request=None, **kwargs):
    return client.fetch_external(
        request if request is not None else _request(),
        dest_path=kwargs.pop("dest_path", tmp_path / "cache" / "pro-pack.tar.gz"),
        quarantine_dir=kwargs.pop("quarantine_dir", tmp_path / "quarantine"),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Criterion 4 - distinct stable machine results
# --------------------------------------------------------------------------


def test_required_result_codes_exist_and_are_distinct():
    codes = []
    for name in REQUIRED_RESULT_NAMES:
        assert hasattr(registry_client, name), f"missing stable result {name}"
        codes.append(getattr(registry_client, name))
    assert all(isinstance(code, str) and code for code in codes)
    assert len(set(codes)) == len(codes), f"result codes collide: {codes}"


def test_failure_classes_map_to_their_own_code():
    assert ExternalSourceAuthenticationError.code == registry_client.RESULT_AUTHENTICATION_DENIED
    assert ExternalSourceExpiryError.code == registry_client.RESULT_CREDENTIAL_EXPIRED
    assert ExternalSourceRedirectError.code == registry_client.RESULT_REDIRECT_REFUSED
    assert ExternalSourceTransportError.code == registry_client.RESULT_TRANSPORT_FAILED
    assert ExternalSourceIntegrityError.code == registry_client.RESULT_INTEGRITY_FAILED


def test_specialised_failures_stay_inside_their_family():
    for cls in (
        ExternalSourceAuthenticationError,
        ExternalSourceExpiryError,
        ExternalSourceRedirectError,
        ExternalSourceTransportError,
        ExternalSourceIntegrityError,
    ):
        assert issubclass(cls, ExternalSourceError)


def test_authentication_denial_has_a_stable_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    for status in (401, 403):
        _raise_http(monkeypatch, status)
        with pytest.raises(ExternalSourceError) as excinfo:
            _fetch(RegistryClient(), tmp_path)
        assert isinstance(excinfo.value, ExternalSourceAuthenticationError)
        assert excinfo.value.code == registry_client.RESULT_AUTHENTICATION_DENIED


def test_expired_grant_is_refused_before_download(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path, request=_request(expires_at=expired))
    assert isinstance(excinfo.value, ExternalSourceExpiryError)
    assert excinfo.value.code == registry_client.RESULT_CREDENTIAL_EXPIRED


def test_expired_grant_result_is_reachable_over_http(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _raise_http(monkeypatch, 410)
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceExpiryError)
    assert excinfo.value.code == registry_client.RESULT_CREDENTIAL_EXPIRED


def test_redirect_to_another_host_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch, url="https://evil.example.test/pro-pack.tar.gz")
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceRedirectError)
    assert excinfo.value.code == registry_client.RESULT_REDIRECT_REFUSED


def test_redirect_to_plaintext_http_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch, url="http://artifacts.example.test/pro-pack.tar.gz")
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceRedirectError)
    assert excinfo.value.code == registry_client.RESULT_REDIRECT_REFUSED


def test_redirect_http_status_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _raise_http(monkeypatch, 302, location="https://evil.example.test/a.tar.gz")
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceRedirectError)
    assert excinfo.value.code == registry_client.RESULT_REDIRECT_REFUSED


def test_transport_failure_has_a_stable_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _raise_transport(monkeypatch)
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceTransportError)
    assert excinfo.value.code == registry_client.RESULT_TRANSPORT_FAILED


def test_digest_mismatch_has_a_stable_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch, body=ARCHIVE + b"tampered")
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceIntegrityError)
    assert excinfo.value.code == registry_client.RESULT_DIGEST_MISMATCH


def test_signature_failure_has_a_stable_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    monkeypatch.setattr(registry_client, "_verify_signature", lambda *a, **k: False)
    _serve(monkeypatch)
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    assert isinstance(excinfo.value, ExternalSourceIntegrityError)
    assert excinfo.value.code == registry_client.RESULT_SIGNATURE_INVALID


def test_digest_and_signature_codes_are_distinct():
    assert (
        registry_client.RESULT_DIGEST_MISMATCH
        != registry_client.RESULT_SIGNATURE_INVALID
    )


def test_failure_result_is_machine_readable_and_redacted(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _raise_http(monkeypatch, 401)
    with pytest.raises(ExternalSourceError) as excinfo:
        _fetch(RegistryClient(), tmp_path)
    payload = excinfo.value.to_dict()
    assert payload["code"] == registry_client.RESULT_AUTHENTICATION_DENIED
    assert payload["result"] == registry_client.RESULT_AUTHENTICATION_DENIED
    assert isinstance(payload["message"], str) and payload["message"]
    assert SECRET not in json.dumps(payload)


def test_the_same_failure_always_reports_the_same_code(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    codes = []
    for _ in range(2):
        _raise_http(monkeypatch, 401)
        with pytest.raises(ExternalSourceError) as excinfo:
            _fetch(RegistryClient(), tmp_path)
        codes.append(excinfo.value.code)
    assert codes[0] == codes[1] == registry_client.RESULT_AUTHENTICATION_DENIED


# --------------------------------------------------------------------------
# Criterion 5 - receipts carry evidence, never commercial or secret data
# --------------------------------------------------------------------------


def _receipt(monkeypatch, tmp_path) -> ExternalSourceReceipt:
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch)
    return RegistryClient().install_external(
        _request(),
        dest_path=tmp_path / "cache" / "pro-pack" / "1.2.3" / "artifact.tar.gz",
        quarantine_dir=tmp_path / "quarantine",
        receipt_path=tmp_path / "receipts" / "pro-pack.json",
    )


def test_receipt_records_source_class_and_verification_evidence(monkeypatch, tmp_path):
    receipt = _receipt(monkeypatch, tmp_path)
    payload = receipt.to_dict()
    assert payload["coordinate"] == "skillweave/pro-pack"
    assert payload["version"] == "1.2.3"
    assert payload["digest"] == DIGEST
    assert payload["source_class"] == "external-authenticated"
    assert payload["verification"] == "digest+signature"
    assert payload["listing_id"] == "lst_skillweave_propack"
    assert payload["installed_at"]


def test_receipt_declares_its_schema_version(monkeypatch, tmp_path):
    receipt = _receipt(monkeypatch, tmp_path)
    assert receipt.to_dict()["protocol"] == registry_client.RECEIPT_PROTOCOL


def test_receipt_carries_no_customer_price_licence_or_entitlement_data(
    monkeypatch, tmp_path
):
    payload = _receipt(monkeypatch, tmp_path).to_dict()
    assert set(payload).isdisjoint(FORBIDDEN_RECEIPT_FIELDS)


def test_receipt_schema_is_a_closed_provenance_allowlist(monkeypatch, tmp_path):
    """A closed schema cannot grow a commercial field by accident."""
    payload = _receipt(monkeypatch, tmp_path).to_dict()
    assert set(payload) == set(ExternalSourceReceipt.FIELD_NAMES)
    assert set(ExternalSourceReceipt.field_names()) == set(payload)
    assert set(payload).isdisjoint(FORBIDDEN_RECEIPT_FIELDS)


def test_receipt_never_contains_credentials(monkeypatch, tmp_path):
    receipt = _receipt(monkeypatch, tmp_path)
    payload = json.dumps(receipt.to_dict())
    assert SECRET not in payload
    assert "env:CAP_TEST_SOURCE_TOKEN" not in payload
    assert "Authorization" not in payload


def test_written_receipt_is_redacted_json_on_disk(monkeypatch, tmp_path):
    receipt_path = tmp_path / "receipts" / "pro-pack.json"
    receipt = _receipt(monkeypatch, tmp_path)
    raw = receipt_path.read_text()
    assert SECRET not in raw
    on_disk = json.loads(raw)
    assert on_disk["digest"] == DIGEST
    assert on_disk["source_class"] == "external-authenticated"
    assert set(on_disk).isdisjoint(FORBIDDEN_RECEIPT_FIELDS)
    assert receipt.path == receipt_path


def test_receipt_is_derivable_from_a_verified_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch)
    artifact = _fetch(RegistryClient(), tmp_path)
    receipt = ExternalSourceReceipt.from_artifact(artifact)
    assert receipt.digest == artifact.digest
    assert receipt.coordinate == artifact.coordinate
    assert receipt.source_class == artifact.source_class
    assert receipt.verification == artifact.verification


def test_receipt_does_not_depend_on_the_install_path(monkeypatch, tmp_path):
    """The receipt is provenance, not a cache location: no absolute path leaks."""
    payload = json.dumps(_receipt(monkeypatch, tmp_path).to_dict())
    assert str(tmp_path) not in payload


# --------------------------------------------------------------------------
# Criterion 6 - the SkillWeave Pro-Pack fixture
# --------------------------------------------------------------------------


def test_skillweave_pro_pack_reference_fixture_installs(monkeypatch, tmp_path):
    dest = tmp_path / "cache" / "skillweave" / "pro-pack" / "1.2.3" / "artifact.tar.gz"
    receipt_path = tmp_path / "receipts" / "skillweave-pro-pack.json"
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch)

    receipt = RegistryClient().install_external(
        _request(),
        dest_path=dest,
        quarantine_dir=tmp_path / "quarantine",
        receipt_path=receipt_path,
    )

    assert dest.read_bytes() == ARCHIVE
    assert receipt_path.exists()
    assert receipt.verification == "digest+signature"
    assert receipt.digest == DIGEST


def test_denial_fails_before_any_local_mutation(monkeypatch, tmp_path):
    dest = tmp_path / "cache" / "skillweave" / "pro-pack" / "1.2.3" / "artifact.tar.gz"
    receipt_path = tmp_path / "receipts" / "skillweave-pro-pack.json"
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _raise_http(monkeypatch, 403)

    with pytest.raises(ExternalSourceAuthenticationError):
        RegistryClient().install_external(
            _request(),
            dest_path=dest,
            quarantine_dir=tmp_path / "quarantine",
            receipt_path=receipt_path,
        )

    assert dest.exists() is False
    assert receipt_path.exists() is False
    assert not (tmp_path / "cache").exists()


def test_digest_mismatch_fails_before_any_local_mutation(monkeypatch, tmp_path):
    dest = tmp_path / "cache" / "skillweave" / "pro-pack" / "1.2.3" / "artifact.tar.gz"
    receipt_path = tmp_path / "receipts" / "skillweave-pro-pack.json"
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch, body=ARCHIVE + b"tampered")

    with pytest.raises(ExternalSourceIntegrityError):
        RegistryClient().install_external(
            _request(),
            dest_path=dest,
            quarantine_dir=tmp_path / "quarantine",
            receipt_path=receipt_path,
        )

    assert dest.exists() is False
    assert receipt_path.exists() is False
    assert Path(dest).parent.exists() is False


def test_quarantine_is_drained_after_a_failed_install(monkeypatch, tmp_path):
    quarantine = tmp_path / "quarantine"
    monkeypatch.setenv("CAP_TEST_SOURCE_TOKEN", SECRET)
    _serve(monkeypatch, body=ARCHIVE + b"tampered")

    with pytest.raises(ExternalSourceIntegrityError):
        RegistryClient().install_external(
            _request(),
            dest_path=tmp_path / "cache" / "artifact.tar.gz",
            quarantine_dir=quarantine,
            receipt_path=tmp_path / "receipts" / "pro-pack.json",
        )

    assert [p for p in quarantine.rglob("*") if p.is_file()] == []
