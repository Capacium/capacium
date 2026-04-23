import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from pathlib import Path


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


class RegistryClientError(Exception):
    pass


class RegistryClient:

    DEFAULT_TIMEOUT = 30

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
            "User-Agent": "capacium/0.1.0",
        }
        token = os.environ.get("CAPACIUM_REGISTRY_TOKEN")
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
        base = (registry_url or os.environ.get("CAPACIUM_REGISTRY_URL", "https://registry.capacium.dev/v1")).rstrip("/")
        return f"{base}{path}"

    def search(
        self,
        query: str,
        kind: Optional[str] = None,
        registry_url: Optional[str] = None,
    ) -> List[RegistryResult]:
        url = self._build_registry_url("/capabilities", registry_url)
        params = []
        if query:
            params.append(f"query={urllib.parse.quote(query)}")
        if kind:
            params.append(f"kind={urllib.parse.quote(kind)}")
        if params:
            url += "?" + "&".join(params)
        data = self._request(url)
        raw = data.get("results", data) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = raw.get("results", [])
        return [RegistryResult(**r) for r in raw]

    def get_capability(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> Optional[RegistryResult]:
        url = self._build_registry_url(f"/capabilities/{urllib.parse.quote(name, safe='')}", registry_url)
        try:
            data = self._request(url)
            return RegistryResult(**data)
        except RegistryClientError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def list_versions(
        self,
        name: str,
        registry_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        url = self._build_registry_url(f"/capabilities/{urllib.parse.quote(name, safe='')}/versions", registry_url)
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
            f"/capabilities/{urllib.parse.quote(name, safe='')}/download?version={urllib.parse.quote(version)}",
            registry_url,
        )
        req_headers = {
            "Accept": "application/octet-stream",
            "User-Agent": "capacium/0.1.0",
        }
        token = os.environ.get("CAPACIUM_REGISTRY_TOKEN")
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
