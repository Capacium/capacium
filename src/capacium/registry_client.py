import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

from . import __version__

EXTERNAL_SOURCE_PROTOCOL = "external-source/v1"
VERIFIED_ARTIFACT_PROTOCOL = "verified-artifact/v1"
RECEIPT_PROTOCOL = "receipt/v1.1.7"

# Stable machine results (criterion 4). Callers branch on these strings, never
# on message text, so a wording change cannot break a consumer.
RESULT_AUTHENTICATION_DENIED = "EXTERNAL_SOURCE_AUTH_DENIED"
RESULT_CREDENTIAL_EXPIRED = "EXTERNAL_SOURCE_CREDENTIAL_EXPIRED"
RESULT_REDIRECT_REFUSED = "EXTERNAL_SOURCE_REDIRECT_REFUSED"
RESULT_TRANSPORT_FAILED = "EXTERNAL_SOURCE_TRANSPORT_FAILED"
RESULT_INTEGRITY_FAILED = "EXTERNAL_SOURCE_INTEGRITY_FAILED"
RESULT_DIGEST_MISMATCH = "EXTERNAL_SOURCE_DIGEST_MISMATCH"
RESULT_SIGNATURE_INVALID = "EXTERNAL_SOURCE_SIGNATURE_INVALID"
RESULT_SOURCE_FAILED = "EXTERNAL_SOURCE_FAILED"

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DENIAL_STATUSES = frozenset({401, 403})
_EXPIRY_STATUSES = frozenset({410})

_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENV_CREDENTIAL_PREFIX = "env:"


@dataclass
class RegistryResult:
    name: str
    owner: str
    version: str
    kind: str
    description: str = ""
    fingerprint: str = ""
    dependencies: Dict[str, str] = field(default_factory=dict)
    frameworks: List[str] = field(default_factory=list)
    published_at: str = ""
    trust: str = "untrusted"
    trust_score: int = 0
    installs: int = 0
    runtimes: Dict[str, str] = field(default_factory=dict)
    repository: str = ""
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)


@dataclass
class RegistryDetail:
    name: str
    owner: str
    kind: str
    description: str = ""
    version: str = ""
    versions: List[str] = field(default_factory=list)
    fingerprint: str = ""
    trust: str = "untrusted"
    trust_score: int = 0
    trust_breakdown: Dict[str, Any] = field(default_factory=dict)
    dependencies: Dict[str, str] = field(default_factory=dict)
    frameworks: List[str] = field(default_factory=list)
    runtimes: Dict[str, str] = field(default_factory=dict)
    repository: str = ""
    installs: int = 0
    published_at: str = ""
    updated_at: str = ""
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class RegistryClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ExternalSourceError(RegistryClientError):
    """An authenticated external artifact source cannot be honoured.

    Criterion 4: every failure carries a stable ``code`` so callers branch on
    machine results rather than on prose. ``message`` is always redacted.
    """

    code = RESULT_SOURCE_FAILED
    result = RESULT_SOURCE_FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result,
            "code": self.code,
            "message": str(self),
        }


class ExternalSourceAuthenticationError(ExternalSourceError):
    """Authentication was refused by the source (401/403)."""

    code = RESULT_AUTHENTICATION_DENIED
    result = RESULT_AUTHENTICATION_DENIED


class ExternalSourceExpiryError(ExternalSourceError):
    """The credential or grant was expired before or during the download."""

    code = RESULT_CREDENTIAL_EXPIRED
    result = RESULT_CREDENTIAL_EXPIRED


class ExternalSourceRedirectError(ExternalSourceError):
    """The source redirected off-host or onto a non-https scheme."""

    code = RESULT_REDIRECT_REFUSED
    result = RESULT_REDIRECT_REFUSED


class ExternalSourceTransportError(ExternalSourceError):
    """The transport failed before any bytes could be verified."""

    code = RESULT_TRANSPORT_FAILED
    result = RESULT_TRANSPORT_FAILED


class ExternalSourceIntegrityError(ExternalSourceError):
    """Verification of digest or signature failed."""

    code = RESULT_INTEGRITY_FAILED
    result = RESULT_INTEGRITY_FAILED


class ExternalSourceDigestMismatchError(ExternalSourceIntegrityError):
    code = RESULT_DIGEST_MISMATCH
    result = RESULT_DIGEST_MISMATCH


class ExternalSourceSignatureError(ExternalSourceIntegrityError):
    code = RESULT_SIGNATURE_INVALID
    result = RESULT_SIGNATURE_INVALID


def _redact_url(url: str) -> str:
    """Drop userinfo and query string so signed tokens never leave the process."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<redacted-url>"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", ""))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_signature(public_key: bytes, signature: bytes, data: bytes) -> bool:
    """Seam for signature verification, overridable in tests.

    Delegates to ``capacium.signing.verify`` whose backend differs between
    hosts (cryptography, PyNaCl or an OpenSSL subprocess).
    """
    from . import signing

    return signing.verify(public_key, signature, data)


@dataclass
class CredentialRef:
    """An opaque reference to credential material, never the material itself.

    Only ``env:<NAME>`` references are accepted. The referenced value is
    resolved on demand and is deliberately absent from ``repr``, ``str`` and
    ``to_dict`` so it cannot leak into logs, JSON or receipts.
    """

    reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, str) or not self.reference.startswith(
            _ENV_CREDENTIAL_PREFIX
        ):
            raise ExternalSourceError(
                "credential must be an opaque 'env:<NAME>' reference, "
                "never a literal secret"
            )
        name = self.reference[len(_ENV_CREDENTIAL_PREFIX):]
        if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ExternalSourceError(
                "credential reference must name a valid environment variable"
            )

    def resolve(self) -> str:
        name = self.reference[len(_ENV_CREDENTIAL_PREFIX):]
        value = os.environ.get(name)
        if not value:
            raise ExternalSourceError(
                f"credential reference {self.reference!r} is not set in the environment"
            )
        return value

    def to_dict(self) -> Dict[str, str]:
        return {"reference": self.reference}

    def __repr__(self) -> str:
        return f"CredentialRef(reference={self.reference!r})"

    __str__ = __repr__


@dataclass
class SourceSignature:
    """Ed25519 provenance material for an external artifact."""

    public_key: bytes
    signature: bytes
    key_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "public_key": self.public_key.hex(),
            "signature": self.signature.hex(),
            "key_name": self.key_name,
        }


@dataclass
class ExternalSourceRequest:
    """Criterion 1: identity, exact version, digest and signature bound up front."""

    listing_id: str
    owner: str
    name: str
    version: str
    digest: str
    url: str
    signature: Optional[SourceSignature] = None
    credential: Optional[CredentialRef] = None
    expires_at: Optional[str] = None
    protocol: str = EXTERNAL_SOURCE_PROTOCOL

    @property
    def coordinate(self) -> str:
        return f"{self.owner}/{self.name}"

    def check_expiry(self, now: Optional[datetime] = None) -> None:
        """Refuse an expired grant before touching the network (criterion 4)."""
        if not self.expires_at:
            return
        try:
            deadline = datetime.fromisoformat(self.expires_at)
        except (TypeError, ValueError) as exc:
            raise ExternalSourceExpiryError(
                f"external source {self.coordinate}@{self.version} declares an "
                f"unusable expiry {self.expires_at!r}"
            ) from exc
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline <= (now or datetime.now(timezone.utc)):
            raise ExternalSourceExpiryError(
                f"external source grant for {self.coordinate}@{self.version} "
                f"expired at {self.expires_at}"
            )

    def validate(self) -> "ExternalSourceRequest":
        if not self.listing_id:
            raise ExternalSourceError("external source requires a listing id")
        if not self.owner:
            raise ExternalSourceError("external source requires an owner")
        if not self.name:
            raise ExternalSourceError("external source requires a name")
        if not isinstance(self.version, str) or not _EXACT_VERSION_RE.match(self.version):
            raise ExternalSourceError(
                f"external source requires an exact version, got {self.version!r}"
            )
        if not isinstance(self.digest, str) or not _SHA256_DIGEST_RE.match(self.digest):
            raise ExternalSourceError(
                "external source requires a 'sha256:<64 hex>' artifact digest"
            )
        if self.signature is None:
            raise ExternalSourceError(
                "external source requires a signature or provenance reference"
            )
        if not isinstance(self.url, str) or urllib.parse.urlsplit(self.url).scheme != "https":
            raise ExternalSourceError("external source must be an https URL")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "listing_id": self.listing_id,
            "coordinate": self.coordinate,
            "version": self.version,
            "digest": self.digest,
            "url": _redact_url(self.url),
            "signature": self.signature.to_dict() if self.signature else None,
            "credential": self.credential.to_dict() if self.credential else None,
            "expires_at": self.expires_at,
        }


@dataclass
class VerifiedArtifact:
    """Criterion 3: the verified-artifact envelope crossing the quarantine boundary."""

    path: Path
    coordinate: str
    version: str
    listing_id: str
    digest: str
    verification: str = "digest+signature"
    source_class: str = "external-authenticated"
    url: str = ""
    key_name: str = ""
    protocol: str = VERIFIED_ARTIFACT_PROTOCOL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "path": str(self.path),
            "coordinate": self.coordinate,
            "version": self.version,
            "listing_id": self.listing_id,
            "digest": self.digest,
            "verification": self.verification,
            "source_class": self.source_class,
            "url": self.url,
            "key_name": self.key_name,
        }


@dataclass
class ExternalSourceReceipt:
    """Criterion 5: proof of provenance, stripped of anything commercial.

    The receipt records the coordinate, version, digest, source class and
    verification evidence. It deliberately has no customer, price, licence or
    entitlement fields, and the URL is stored redacted so a signed query string
    can never survive into an audit record.
    """

    coordinate: str
    version: str
    digest: str
    listing_id: str
    source_class: str = "external-authenticated"
    verification: str = "digest+signature"
    url: str = ""
    key_name: str = ""
    installed_at: str = ""
    protocol: str = RECEIPT_PROTOCOL
    path: Optional[Path] = None

    #: The complete receipt schema. It is an allowlist: provenance fields only,
    #: so no commercial or secret field has anywhere to live, and the neutral
    #: Core never has to name commercial vocabulary to exclude it.
    FIELD_NAMES = (
        "protocol",
        "coordinate",
        "version",
        "digest",
        "listing_id",
        "source_class",
        "verification",
        "url",
        "key_name",
        "installed_at",
    )

    @classmethod
    def from_artifact(
        cls,
        artifact: "VerifiedArtifact",
        installed_at: Optional[str] = None,
    ) -> "ExternalSourceReceipt":
        return cls(
            coordinate=artifact.coordinate,
            version=artifact.version,
            digest=artifact.digest,
            listing_id=artifact.listing_id,
            source_class=artifact.source_class,
            verification=artifact.verification,
            url=artifact.url,
            key_name=artifact.key_name,
            installed_at=installed_at or _utc_now(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "coordinate": self.coordinate,
            "version": self.version,
            "digest": self.digest,
            "listing_id": self.listing_id,
            "source_class": self.source_class,
            "verification": self.verification,
            "url": _redact_url(self.url) if self.url else "",
            "key_name": self.key_name,
            "installed_at": self.installed_at,
        }

    @classmethod
    def field_names(cls) -> frozenset:
        return frozenset(cls.FIELD_NAMES)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RegistryClient:

    DEFAULT_TIMEOUT = 30

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        log_sink: Optional[List[str]] = None,
    ):
        self._token = token
        self._base_url = base_url
        self._log_sink = log_sink

    def _log(self, message: str) -> None:
        """Emit a redacted line; the sink is opt-in so nothing is stored by default."""
        if self._log_sink is not None:
            self._log_sink.append(message)

    @staticmethod
    def from_config() -> "RegistryClient":
        from .utils.config import get_registry_url, load_auth_token
        url = get_registry_url().rstrip("/")
        # Strip /v2 suffix — _build_registry_url appends /v2/* paths itself.
        # config.yaml stores the full URL (e.g. https://api.capacium.xyz/v2)
        # so without this strip we'd get …/v2/v2/listings.
        if url.endswith("/v2"):
            url = url[:-3]
        token = load_auth_token()
        return RegistryClient(base_url=url, token=token)

    def _get_token(self) -> Optional[str]:
        if self._token:
            return self._token
        token = os.environ.get("CAPACIUM_REGISTRY_TOKEN")
        if token:
            return token
        auth_path = Path.home() / ".capacium" / "auth"
        if auth_path.exists():
            try:
                with open(auth_path) as f:
                    data = json.load(f)
                    return data.get("token")
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def _request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        req_headers = {
            "Accept": "application/json",
            "User-Agent": f"capacium/{__version__}",
        }
        token = self._get_token()
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        if headers:
            req_headers.update(headers)
        if data is not None:
            req_headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.status == 204:
                    return {}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                pass
            raise RegistryClientError(
                f"HTTP {e.code} from {url}: {detail or e.reason}",
                status_code=e.code,
            ) from e
        except urllib.error.URLError as e:
            raise RegistryClientError(f"Connection failed: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise RegistryClientError(f"Invalid JSON response from {url}: {e}") from e
        except OSError as e:
            raise RegistryClientError(f"Network error: {e}") from e

    def _build_registry_url(self, path: str, registry_url: Optional[str] = None) -> str:
        base = (registry_url or self._base_url or self._read_config_registry_url()
                or os.environ.get("CAPACIUM_REGISTRY_URL", "https://api.capacium.xyz"))
        base = base.rstrip("/")
        return f"{base}{path}"

    @staticmethod
    def _read_config_registry_url() -> Optional[str]:
        config_path = Path.home() / ".capacium" / "config.yaml"
        if not config_path.exists():
            return None
        try:
            _check_yaml_available()
            import yaml
            with open(config_path) as f:
                data = yaml.safe_load(f)
                return data.get("registry") if isinstance(data, dict) else None
        except Exception:
            return None

    def search(
        self,
        query: str,
        kind: Optional[str] = None,
        registry_url: Optional[str] = None,
        framework: Optional[str] = None,
        trust: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        sort: str = "relevance",
        limit: int = 50,
        min_stars: Optional[int] = None,
    ) -> List[RegistryResult]:
        raw = self.search_raw(
            query,
            kind=kind,
            registry_url=registry_url,
            framework=framework,
            trust=trust,
            category=category,
            tag=tag,
            sort=sort,
            limit=limit,
            min_stars=min_stars,
        )
        listings = (
            raw.get("listings", raw.get("results", []))
            if isinstance(raw, dict)
            else raw
        )
        if isinstance(listings, dict):
            listings = listings.get("listings", [])
        results = []
        for r in listings:
            r = dict(r)
            canonical = r.get("canonical_name", "")
            if "/" in canonical and "owner" not in r:
                r["owner"], r["name"] = canonical.split("/", 1)
            r.setdefault("owner", r.get("owner", ""))
            r.setdefault("name", r.get("name", canonical))
            r.setdefault("version", r.get("version", "0.0.0"))
            results.append(RegistryResult(**{k: v for k, v in r.items() if k in RegistryResult.__dataclass_fields__}))
        return results

    def search_raw(
        self,
        query: str,
        kind: Optional[str] = None,
        registry_url: Optional[str] = None,
        framework: Optional[str] = None,
        trust: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        sort: str = "relevance",
        limit: int = 50,
        min_stars: Optional[int] = None,
    ) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/listings", registry_url)
        params = []
        if query:
            params.append(f"search={urllib.parse.quote(query)}")
        if kind:
            params.append(f"kind={urllib.parse.quote(kind)}")
        if framework:
            params.append(f"framework={urllib.parse.quote(framework)}")
        if trust:
            params.append(f"trust_state={urllib.parse.quote(trust)}")
        if category:
            params.append(f"category={urllib.parse.quote(category)}")
        if tag:
            params.append(f"tag={urllib.parse.quote(tag)}")
        if sort:
            params.append(f"sort={urllib.parse.quote(sort)}")
        if limit:
            params.append(f"limit={limit}")
        if min_stars is not None:
            params.append(f"min_stars={min_stars}")
        if params:
            url += "?" + "&".join(params)
        return self._request(url)

    def get_capability(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> Optional[RegistryResult]:
        url = self._build_registry_url(f"/v2/capabilities/{urllib.parse.quote(name, safe='')}", registry_url)
        try:
            data = self._request(url)
            return RegistryResult(**{k: v for k, v in data.items() if k in RegistryResult.__dataclass_fields__})
        except RegistryClientError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def get_detail(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> Optional[RegistryDetail]:
        if "/" not in name:
            results = self.search(name, registry_url=registry_url, limit=3)
            for r in results:
                if r.name == name:
                    name = f"{r.owner}/{r.name}"
                    break
            else:
                return None
        url = self._build_registry_url(f"/v2/capabilities/{urllib.parse.quote(name, safe='')}", registry_url)
        try:
            data = self._request(url)
            data = dict(data)
            canonical = data.get("canonical_name", "")
            if "/" in canonical:
                data.setdefault("owner", canonical.split("/", 1)[0])
                data.setdefault("name", canonical.split("/", 1)[1])
            versions_raw = data.get("versions", [])
            if versions_raw and isinstance(versions_raw[0], dict):
                data["version"] = versions_raw[0].get("version", "")
                data["versions"] = [v.get("version", str(v)) for v in versions_raw]
            trust_history = data.get("trust_history")
            if trust_history and isinstance(trust_history, list):
                data.setdefault("trust_breakdown", data.get("trust_breakdown", {}))
            if not data.get("repository") and data.get("canonical_source_url"):
                data["repository"] = data["canonical_source_url"]
            return RegistryDetail(**{k: v for k, v in data.items() if k in RegistryDetail.__dataclass_fields__})
        except RegistryClientError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def get_stats(self, registry_url: Optional[str] = None) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/stats", registry_url)
        return self._request(url)

    def get_user_info(self, registry_url: Optional[str] = None) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/user", registry_url)
        return self._request(url)

    def publish(self, payload: Dict[str, Any], registry_url: Optional[str] = None) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/publish", registry_url)
        data = json.dumps(payload).encode("utf-8")
        return self._request(url, method="POST", data=data)

    def verify_token(self, registry_url: Optional[str] = None) -> bool:
        try:
            self._request(self._build_registry_url("/v2/stats", registry_url))
            return True
        except RegistryClientError:
            return False

    def list_versions(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        url = self._build_registry_url(f"/v2/capabilities/{urllib.parse.quote(name, safe='')}/versions", registry_url)
        data = self._request(url)
        return data.get("versions", [])

    def download(
        self,
        name: str,
        version: str,
        registry_url: Optional[str] = None,
        dest_path: Optional[Path] = None,
    ) -> bytes:
        url = self._build_registry_url(
            f"/v2/capabilities/{urllib.parse.quote(name, safe='')}/download?version={urllib.parse.quote(version)}",
            registry_url,
        )
        req_headers = {
            "Accept": "application/octet-stream",
            "User-Agent": f"capacium/{__version__}",
        }
        token = self._get_token()
        if token:
            req_headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(url, headers=req_headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.DEFAULT_TIMEOUT) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                pass
            raise RegistryClientError(
                f"HTTP {e.code} from {url}: {detail or e.reason}",
                status_code=e.code,
            ) from e
        except urllib.error.URLError as e:
            raise RegistryClientError(f"Connection failed: {e.reason}") from e
        except OSError as e:
            raise RegistryClientError(f"Network error: {e}") from e

        if dest_path:
            # Registry-hosted downloads funnel through the same materialisation
            # step as external ones (criterion 3: one handoff path).
            self._materialize_artifact(body, dest_path)

        return body

    def _materialize_artifact(self, data: bytes, dest_path: Path) -> Path:
        """The single mutation step both registry and external fetches use.

        Writing to the destination is the only point where download bytes touch
        the install tree, so a deployment that breaks this step breaks every
        source class identically.
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(data)
        return dest_path

    def fetch_external(
        self,
        request: ExternalSourceRequest,
        dest_path: Path,
        quarantine_dir: Path,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> VerifiedArtifact:
        """Fetch, quarantine and verify an artifact from an authenticated source.

        Criterion 1 is enforced by ``request.validate()`` before any I/O,
        criterion 2 by resolving an opaque credential reference (never logging
        it), criterion 3 by quarantining, verifying digest and signature before
        mutating, and materialising through ``_materialize_artifact``.
        """
        request.validate()
        safe_url = _redact_url(request.url)

        # An expired grant is refused before any network call or local write.
        request.check_expiry()

        # Resolve the credential before touching the network: a missing secret
        # must refuse up front rather than after a partial download.
        credential_value = request.credential.resolve() if request.credential else None

        quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantine_path = quarantine_dir / (
            f"{request.listing_id}-{request.version}-{Path(safe_url).name}"
        )

        body = self._download_external_bytes(
            request.url, credential_value, safe_url, timeout
        )
        quarantine_path.write_bytes(body)
        self._log(
            f"external source: quarantined {request.coordinate}@{request.version} "
            f"({len(body)} bytes) at {quarantine_path}"
        )

        try:
            actual_digest = "sha256:" + _sha256_hex(body)
            if actual_digest != request.digest:
                raise ExternalSourceDigestMismatchError(
                    f"digest mismatch for {request.coordinate}@{request.version}: "
                    f"expected {request.digest}, got {actual_digest}"
                )

            signature = request.signature
            if signature is None or not _verify_signature(
                signature.public_key, signature.signature, body
            ):
                raise ExternalSourceSignatureError(
                    f"signature verification failed for "
                    f"{request.coordinate}@{request.version}"
                )

            # Verification passed: only now may install state change.
            self._materialize_artifact(body, dest_path)
            self._log(
                f"external source: verified and installed {request.coordinate}"
                f"@{request.version} ({request.digest}) at {dest_path}"
            )
        finally:
            # Quarantine is drained whether the artifact verified or not.
            try:
                quarantine_path.unlink()
            except OSError:
                pass

        return VerifiedArtifact(
            path=dest_path,
            coordinate=request.coordinate,
            version=request.version,
            listing_id=request.listing_id,
            digest=request.digest,
            url=safe_url,
            key_name=request.signature.key_name if request.signature else "",
        )

    def install_external(
        self,
        request: ExternalSourceRequest,
        dest_path: Path,
        quarantine_dir: Path,
        receipt_path: Path,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> ExternalSourceReceipt:
        """Criterion 6: install, then persist a redacted receipt.

        The receipt is written only after ``fetch_external`` has verified and
        materialised the artifact, so a denial or digest mismatch leaves no
        destination file and no receipt behind.
        """
        artifact = self.fetch_external(
            request,
            dest_path=dest_path,
            quarantine_dir=quarantine_dir,
            timeout=timeout,
        )
        receipt = ExternalSourceReceipt.from_artifact(artifact)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt.path = receipt_path
        self._log(
            f"external source: receipt written for {receipt.coordinate}"
            f"@{receipt.version} at {receipt_path}"
        )
        return receipt

    def _download_external_bytes(
        self,
        url: str,
        credential_value: Optional[str],
        safe_url: str,
        timeout: int,
    ) -> bytes:
        req_headers = {
            "Accept": "application/octet-stream",
            "User-Agent": f"capacium/{__version__}",
        }
        if credential_value:
            req_headers["Authorization"] = f"Bearer {credential_value}"

        req = urllib.request.Request(url, headers=req_headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if status and status >= 400:
                    self._raise_for_status(status, safe_url)
                self._reject_unsafe_final_url(resp, safe_url)
                return resp.read()
        except ExternalSourceError:
            raise
        except urllib.error.HTTPError as e:
            # The redacted URL keeps signed query strings out of the message.
            self._raise_for_status(e.code, safe_url, headers=e.headers)
            raise  # pragma: no cover - _raise_for_status always raises
        except urllib.error.URLError as e:
            raise ExternalSourceTransportError(
                f"connection failed for {safe_url}: {e.reason}"
            ) from e
        except OSError as e:
            raise ExternalSourceTransportError(
                f"network error for {safe_url}: {e}"
            ) from e

    def _reject_unsafe_final_url(self, resp: Any, safe_url: str) -> None:
        """Refuse a redirect that left the origin host or dropped to http.

        ``urllib`` follows redirects silently, so the only place to detect one
        is the final response URL. Cross-host and plaintext hops fail closed
        (criterion 4: a redirect must be its own machine result).
        """
        final = ""
        try:
            final = resp.geturl() or ""
        except Exception:
            final = ""
        if not final:
            return
        origin = urllib.parse.urlsplit(safe_url)
        landed = urllib.parse.urlsplit(final)
        if landed.scheme != "https":
            raise ExternalSourceRedirectError(
                f"external source refused a redirect to non-https {landed.scheme!r}",
                status_code=None,
            )
        if (landed.hostname or "").lower() != (origin.hostname or "").lower():
            raise ExternalSourceRedirectError(
                f"external source refused a redirect from {origin.hostname!r} "
                f"to {landed.hostname!r}"
            )

    @staticmethod
    def _raise_for_status(
        status: int, safe_url: str, headers: Any = None
    ) -> None:
        """Map an HTTP status onto the stable machine result for its class."""
        if status in _REDIRECT_STATUSES:
            location = ""
            try:
                location = (headers or {}).get("Location", "") or ""
            except Exception:
                location = ""
            raise ExternalSourceRedirectError(
                f"external source refused HTTP {status} redirect from {safe_url}"
                + (f" to {_redact_url(location)}" if location else ""),
                status_code=status,
            )
        if status in _DENIAL_STATUSES:
            raise ExternalSourceAuthenticationError(
                f"authentication denied (HTTP {status}) by {safe_url}",
                status_code=status,
            )
        if status in _EXPIRY_STATUSES:
            raise ExternalSourceExpiryError(
                f"external source grant expired (HTTP {status}) for {safe_url}",
                status_code=status,
            )
        raise ExternalSourceTransportError(
            f"HTTP {status} from {safe_url}", status_code=status
        )


    def submit(
        self,
        github_url: str,
        registry_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/submit", registry_url)
        payload = {"github_url": github_url}
        data = json.dumps(payload).encode("utf-8")
        return self._request(url, method="POST", data=data)

    def submit_status(
        self,
        job_id: str,
        registry_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Poll a queued submission (/v2/submit returns 202 + job_id)."""
        url = self._build_registry_url(
            f"/v2/submit/{urllib.parse.quote(job_id, safe='')}", registry_url
        )
        return self._request(url)

    def publisher_sign(
        self,
        owner: str,
        name: str,
        public_key_pem: str,
        signature_b64: str,
        key_name: str = "",
        registry_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """P0-004: POST publisher Ed25519 signature to Exchange for verification and storage."""
        url = self._build_registry_url(
            f"/v2/capabilities/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(name, safe='')}/publisher-sign",
            registry_url,
        )
        payload = {
            "public_key_pem": public_key_pem,
            "signature_b64": signature_b64,
            "key_name": key_name,
        }
        data = json.dumps(payload).encode("utf-8")
        return self._request(url, method="POST", data=data)

    def submit_tarball(
        self,
        tarball_path: Path,
        registry_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/submit", registry_url)
        return self._upload_file(url, tarball_path)

    def _upload_file(self, url: str, file_path: Path) -> Dict[str, Any]:
        import uuid

        boundary = uuid.uuid4().hex
        filename = file_path.name

        with open(file_path, "rb") as f:
            file_data = f.read()

        body_parts = []
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="package"; filename="{filename}"\r\n'
            f"Content-Type: application/gzip\r\n\r\n".encode("utf-8")
        )
        body_parts.append(file_data)
        body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        body = b"".join(body_parts)

        req_headers = {
            "Accept": "application/json",
            "User-Agent": f"capacium/{__version__}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        token = self._get_token()
        if token:
            req_headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.DEFAULT_TIMEOUT) as resp:
                body = resp.read()
                if resp.status == 204:
                    return {}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                pass
            raise RegistryClientError(
                f"HTTP {e.code} from {url}: {detail or e.reason}",
                status_code=e.code,
            ) from e
        except urllib.error.URLError as e:
            raise RegistryClientError(f"Connection failed: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise RegistryClientError(f"Invalid JSON response from {url}: {e}") from e
        except OSError as e:
            raise RegistryClientError(f"Network error: {e}") from e


def _check_yaml_available() -> None:
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise ImportError("PyYAML is required for YAML config. Install it with: pip install PyYAML")
