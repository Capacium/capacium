import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

from . import __version__


@dataclass
class RegistryResult:
    name: str
    owner: str
    version: str
    kind: str = "skill"
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
    kind: str = "skill"
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
    pass


class RegistryClient:

    DEFAULT_TIMEOUT = 30

    def __init__(self, token: Optional[str] = None):
        self._token = token

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
                f"HTTP {e.code} from {url}: {detail or e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise RegistryClientError(f"Connection failed: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise RegistryClientError(f"Invalid JSON response from {url}: {e}") from e
        except OSError as e:
            raise RegistryClientError(f"Network error: {e}") from e

    def _build_registry_url(self, path: str, registry_url: Optional[str] = None) -> str:
        config_url = self._read_config_registry_url()
        default = registry_url or config_url or os.environ.get("CAPACIUM_REGISTRY_URL", "https://api.capacium.xyz")
        base = default.rstrip("/")
        base = base.replace("/v2", "").replace("/v1", "")
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
    ) -> List[RegistryResult]:
        url = self._build_registry_url("/v1/capabilities", registry_url)
        params = []
        if query:
            params.append(f"q={urllib.parse.quote(query)}")
        if kind:
            params.append(f"kind={urllib.parse.quote(kind)}")
        if framework:
            params.append(f"framework={urllib.parse.quote(framework)}")
        if trust:
            params.append(f"trust={urllib.parse.quote(trust)}")
        if category:
            params.append(f"category={urllib.parse.quote(category)}")
        if tag:
            params.append(f"tag={urllib.parse.quote(tag)}")
        if sort:
            params.append(f"sort={urllib.parse.quote(sort)}")
        if limit:
            params.append(f"limit={limit}")
        if params:
            url += "?" + "&".join(params)

        data = self._request(url)
        raw = data.get("results", []) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = raw.get("results", [])
        results = []
        for r in raw:
            r = dict(r)
            r.setdefault("owner", r.get("owner", ""))
            r.setdefault("name", r.get("name", "unknown"))
            r.setdefault("version", r.get("version", "0.0.0"))
            results.append(RegistryResult(**{k: v for k, v in r.items() if k in RegistryResult.__dataclass_fields__}))
        return results

    def get_capability(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> Optional[RegistryResult]:
        url = self._build_registry_url(f"/v1/capabilities/{urllib.parse.quote(name, safe='')}", registry_url)
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
        url = self._build_registry_url(f"/v1/capabilities/{urllib.parse.quote(name, safe='')}", registry_url)
        try:
            data = self._request(url)
            return RegistryDetail(**{k: v for k, v in data.items() if k in RegistryDetail.__dataclasses_fields__})
        except RegistryClientError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def get_stats(self, registry_url: Optional[str] = None) -> Dict[str, Any]:
        url = self._build_registry_url("/v1/stats", registry_url)
        return self._request(url)

    def get_user_info(self, registry_url: Optional[str] = None) -> Dict[str, Any]:
        url = self._build_registry_url("/v1/user", registry_url)
        return self._request(url)

    def publish(self, payload: Dict[str, Any], registry_url: Optional[str] = None) -> Dict[str, Any]:
        url = self._build_registry_url("/v1/capabilities/publish", registry_url)
        data = json.dumps(payload).encode("utf-8")
        return self._request(url, method="POST", data=data)

    def verify_token(self, registry_url: Optional[str] = None) -> bool:
        try:
            self._request(self._build_registry_url("/v1/stats", registry_url))
            return True
        except RegistryClientError:
            return False

    def list_versions(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        url = self._build_registry_url(f"/v1/capabilities/{urllib.parse.quote(name, safe='')}/versions", registry_url)
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
            f"/v1/capabilities/{urllib.parse.quote(name, safe='')}/download?version={urllib.parse.quote(version)}",
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
                f"HTTP {e.code} from {url}: {detail or e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise RegistryClientError(f"Connection failed: {e.reason}") from e
        except OSError as e:
            raise RegistryClientError(f"Network error: {e}") from e

        if dest_path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(body)

        return body


    def submit(
        self,
        github_url: str,
        registry_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = self._build_registry_url("/v2/submit", registry_url)
        payload = {"github_url": github_url}
        data = json.dumps(payload).encode("utf-8")
        return self._request(url, method="POST", data=data)


def _check_yaml_available() -> None:
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise ImportError("PyYAML is required for YAML config. Install it with: pip install PyYAML")
