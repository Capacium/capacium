import json
from unittest.mock import patch
from capacium.registry_client import RegistryClient, RegistryResult, RegistryClientError


class FakeResponse:
    def __init__(self, data, status=200):
        if isinstance(data, str):
            self._body = data.encode("utf-8")
        elif isinstance(data, bytes):
            self._body = data
        else:
            self._body = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_registry_result_from_kwargs():
    r = RegistryResult(name="test-cap", owner="alice", version="1.0.0", kind="skill")
    assert r.name == "test-cap"
    assert r.owner == "alice"
    assert r.kind == "skill"


def test_search_returns_results():
    client = RegistryClient()
    fake_data = {
        "listings": [
            {"name": "cap-a", "owner": "alice", "version": "1.0.0", "kind": "skill"},
            {"name": "cap-b", "owner": "bob", "version": "2.0.0", "kind": "tool"},
        ]
    }

    with patch("urllib.request.urlopen", return_value=FakeResponse(fake_data)):
        results = client.search(query="cap", registry_url="http://localhost:8000/v1")

    assert len(results) == 2
    assert results[0].name == "cap-a"
    assert results[1].kind == "tool"


def test_search_empty():
    client = RegistryClient()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"listings": []})):
        results = client.search(query="nonexistent", registry_url="http://localhost:8000/v1")
    assert results == []


def test_get_capability_found():
    client = RegistryClient()
    fake_data = {"name": "web-fetcher", "owner": "capacium", "version": "1.2.0", "kind": "skill"}

    with patch("urllib.request.urlopen", return_value=FakeResponse(fake_data)):
        result = client.get_capability(name="capacium/web-fetcher", registry_url="http://localhost:8000/v1")

    assert result is not None
    assert result.name == "web-fetcher"
    assert result.version == "1.2.0"


def test_get_capability_not_found():
    client = RegistryClient()

    def raise_404(*args, **kwargs):
        from urllib.error import HTTPError
        raise HTTPError(
            url="http://localhost:8000/v1/capabilities/nope",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=raise_404):
        result = client.get_capability(name="nope", registry_url="http://localhost:8000/v1")

    assert result is None


def test_list_versions():
    client = RegistryClient()
    fake_data = {
        "name": "test-cap",
        "versions": [
            {"version": "1.0.0", "published_at": "2025-01-01T00:00:00Z", "fingerprint": "abc"},
            {"version": "1.1.0", "published_at": "2025-02-01T00:00:00Z", "fingerprint": "def"},
        ],
    }

    with patch("urllib.request.urlopen", return_value=FakeResponse(fake_data)):
        versions = client.list_versions(name="test-cap", registry_url="http://localhost:8000/v1")

    assert len(versions) == 2
    assert versions[0]["version"] == "1.0.0"
    assert versions[1]["fingerprint"] == "def"


def test_download_returns_bytes():
    client = RegistryClient()
    archive_bytes = b"this-is-a-tar-gz-archive"

    with patch("urllib.request.urlopen", return_value=FakeResponse(archive_bytes)):
        data = client.download(name="test-cap", version="1.0.0", registry_url="http://localhost:8000/v1")

    assert data == archive_bytes


def test_download_writes_to_dest(tmp_path):
    client = RegistryClient()
    archive_bytes = b"fake-archive-content"
    dest = tmp_path / "downloads" / "test-cap-v1.cap"

    with patch("urllib.request.urlopen", return_value=FakeResponse(archive_bytes)):
        client.download(name="test-cap", version="1.0.0", registry_url="http://localhost:8000/v1", dest_path=dest)

    assert dest.read_bytes() == archive_bytes


def test_network_error():
    client = RegistryClient()

    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        try:
            client.search(query="x", registry_url="http://localhost:8000/v1")
            assert False, "Expected RegistryClientError"
        except RegistryClientError as e:
            assert "Network error" in str(e)


def test_http_error():
    client = RegistryClient()

    def raise_500(*args, **kwargs):
        from urllib.error import HTTPError
        raise HTTPError(
            url="http://localhost:8000/v1/capabilities",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=raise_500):
        try:
            client.search(query="x", registry_url="http://localhost:8000/v1")
            assert False, "Expected RegistryClientError"
        except RegistryClientError as e:
            assert "HTTP 500" in str(e)


_Q = "https://api.capacium.xyz"


def test_submit_url_not_doubled_when_config_ends_in_v2(tmp_path):
    """RED (criterion 1): the submit path builds a bare RegistryClient() (as
    submit.py does) whose base falls through to the config file; when that
    config URL carries the /v2 suffix the submit URL must not double to /v2/v2.
    """
    from pathlib import Path as _P
    cdir = _P.home() / ".capacium"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "config.yaml").write_text(f"registry: {_Q}/v2\n")

    client = RegistryClient()          # registry_url AND base_url AND env all unset
    assert client._base_url is None
    url = client._build_registry_url("/v2/submit")
    assert url == f"{_Q}/v2/submit", f"submit URL doubled: {url}"


def test_base_from_explicit_registry_arg_strips_trailing_v2():
    """Criterion 2 — source 1: explicit registry_url argument ending /v2."""
    client = RegistryClient()
    url = client._build_registry_url("/v2/submit", registry_url=f"{_Q}/v2")
    assert url == f"{_Q}/v2/submit"


def test_base_from_constructor_strips_trailing_v2():
    """Criterion 2 — source 2: constructor base_url ending /v2."""
    client = RegistryClient(base_url=f"{_Q}/v2")
    url = client._build_registry_url("/v2/submit")
    assert url == f"{_Q}/v2/submit"


def test_base_from_environment_strips_trailing_v2(monkeypatch):
    """Criterion 2 — source 4: CAPACIUM_REGISTRY_URL ending /v2 (bare-host
    default is source-4's empty-string fallback, already without /v2)."""
    monkeypatch.setenv("CAPACIUM_REGISTRY_URL", f"{_Q}/v2")
    client = RegistryClient()
    url = client._build_registry_url("/v2/submit")
    assert url == f"{_Q}/v2/submit"


def test_trailing_slash_and_trailing_v2_and_both_resolve_identically():
    """Criterion 2 — a trailing '/v2', a trailing slash, and both together all
    resolve to the same single-/v2 submit URL."""
    cases = {
        f"{_Q}/v2": f"{_Q}/v2/submit",
        f"{_Q}/": f"{_Q}/v2/submit",
        f"{_Q}/v2/": f"{_Q}/v2/submit",
        _Q: f"{_Q}/v2/submit",
    }
    for base, expected in cases.items():
        client = RegistryClient(base_url=base)
        assert client._build_registry_url("/v2/submit") == expected


def test_v2_appearing_elsewhere_is_not_stripped():
    """Criterion 3 — normalisation strips only an exact trailing /v2 segment.
    A base whose earlier path merely contains 'v2' (v2-staging, v20) is kept."""
    cases = {
        "https://self.host/api/v2-staging": "https://self.host/api/v2-staging/v2/submit",
        "https://self.host/api/v20": "https://self.host/api/v20/v2/submit",
        "https://self.host/v2-staging": "https://self.host/v2-staging/v2/submit",
    }
    for base, expected in cases.items():
        client = RegistryClient(base_url=base)
        assert client._build_registry_url("/v2/submit") == expected


def test_search_with_kind_filter():
    client = RegistryClient()
    fake_data = {
        "listings": [
            {"name": "tool-a", "owner": "alice", "version": "1.0.0", "kind": "tool"},
        ]
    }

    with patch("urllib.request.urlopen", return_value=FakeResponse(fake_data)) as mock:
        results = client.search(query="tool", kind="tool", registry_url="http://localhost:8000/v1")
        called_url = mock.call_args[0][0].full_url
        assert "kind=tool" in called_url

    assert len(results) == 1
    assert results[0].kind == "tool"
