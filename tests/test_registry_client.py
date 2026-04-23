import json
from pathlib import Path
from unittest.mock import patch, MagicMock
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
    r = RegistryResult(name="test-cap", owner="alice", version="1.0.0")
    assert r.name == "test-cap"
    assert r.owner == "alice"
    assert r.kind == "skill"


def test_search_returns_results():
    client = RegistryClient()
    fake_data = {
        "results": [
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
    with patch("urllib.request.urlopen", return_value=FakeResponse({"results": []})):
        results = client.search(query="nonexistent", registry_url="http://localhost:8000/v1")
    assert results == []


def test_get_capability_found():
    client = RegistryClient()
    fake_data = {"name": "web-fetcher", "owner": "typelicious", "version": "1.2.0", "kind": "skill"}

    with patch("urllib.request.urlopen", return_value=FakeResponse(fake_data)):
        result = client.get_capability(name="typelicious/web-fetcher", registry_url="http://localhost:8000/v1")

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


def test_search_with_kind_filter():
    client = RegistryClient()
    fake_data = {
        "results": [
            {"name": "tool-a", "owner": "alice", "version": "1.0.0", "kind": "tool"},
        ]
    }

    with patch("urllib.request.urlopen", return_value=FakeResponse(fake_data)) as mock:
        results = client.search(query="tool", kind="tool", registry_url="http://localhost:8000/v1")
        called_url = mock.call_args[0][0].full_url
        assert "kind=tool" in called_url

    assert len(results) == 1
    assert results[0].kind == "tool"
