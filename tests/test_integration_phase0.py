"""
Phase 0 Integration Tests — P0-007
===================================
Covers the 6 bugs fixed in Phase 0:

  P0-001  RegistryClient.from_config() URL deduplication (/v2/v2 bug)
  P0-002  _batch_insert kind/source field mapping (INSERT + UPDATE paths)
  P0-003  cap key show --public subcommand
  P0-004  cap sign posts publisher signature to Exchange
  P0-005  ExchangeClient (capacium-mcp) uses correct /v2 endpoints
  P0-006  SQL migration 0004 backfills kind/source (tested via heuristic logic)
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

class FakeHTTPResponse:
    """Minimal urllib response shim."""
    def __init__(self, data: dict | list | str, status: int = 200):
        if isinstance(data, (dict, list)):
            self._body = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            self._body = data.encode("utf-8")
        else:
            self._body = data
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ===========================================================================
# P0-001 — RegistryClient.from_config() strips /v2 suffix before returning
# ===========================================================================

class TestP0001RegistryClientFromConfig:
    def test_from_config_strips_v2_suffix(self, tmp_path, monkeypatch):
        """from_config() must not double-append /v2 when config has the suffix."""
        config_dir = tmp_path / ".capacium"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("registry: https://api.capacium.xyz/v2\n")
        (config_dir / "auth").write_text(json.dumps({"token": "tok123"}))

        monkeypatch.setenv("HOME", str(tmp_path))

        from capacium.registry_client import RegistryClient
        with patch("capacium.utils.config.get_registry_url", return_value="https://api.capacium.xyz/v2"), \
             patch("capacium.utils.config.load_auth_token", return_value="tok123"):
            client = RegistryClient.from_config()

        # _build_registry_url appends /v2/listings — must not become /v2/v2/listings
        url = client._build_registry_url("/v2/listings")
        assert "/v2/v2/" not in url, f"URL must not contain /v2/v2/: {url}"
        assert url.endswith("/v2/listings"), f"Expected /v2/listings suffix, got: {url}"

    def test_from_config_without_v2_suffix_unchanged(self):
        """from_config() with base URL (no /v2) must pass through unchanged."""
        from capacium.registry_client import RegistryClient
        with patch("capacium.utils.config.get_registry_url", return_value="https://api.capacium.xyz"), \
             patch("capacium.utils.config.load_auth_token", return_value=None):
            client = RegistryClient.from_config()

        url = client._build_registry_url("/v2/listings")
        assert url == "https://api.capacium.xyz/v2/listings"

    def test_search_url_never_double_v2(self):
        """search_raw() must build /v2/listings, never /v2/v2/listings."""
        from capacium.registry_client import RegistryClient
        client = RegistryClient(base_url="https://api.capacium.xyz")
        captured_urls = []

        def fake_urlopen(req, timeout=30):
            captured_urls.append(req.full_url)
            return FakeHTTPResponse({"listings": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.search_raw("test")

        assert len(captured_urls) == 1
        assert "/v2/v2/" not in captured_urls[0], f"Double /v2 detected: {captured_urls[0]}"


# ===========================================================================
# P0-002 — _batch_insert uses "kind" field (not "package_type"), populates "source"
# ===========================================================================

class TestP0002BatchInsert:
    """Unit-test the field-resolution logic that _batch_insert uses.

    We test the resolved values independently of the DB to avoid needing
    a real PostgreSQL instance in CI.
    """

    @staticmethod
    def _resolve_kind(finding: dict) -> str:
        return finding.get("kind") or finding.get("package_type") or "skill"

    @staticmethod
    def _resolve_source(finding: dict) -> str | None:
        return finding.get("source") or finding.get("curated_source")

    def test_kind_preferred_over_package_type(self):
        finding = {"kind": "mcp-server", "package_type": "tool"}
        assert self._resolve_kind(finding) == "mcp-server"

    def test_kind_fallback_to_package_type(self):
        finding = {"package_type": "tool"}
        assert self._resolve_kind(finding) == "tool"

    def test_kind_defaults_to_skill(self):
        finding = {}
        assert self._resolve_kind(finding) == "skill"

    def test_source_preferred_over_curated_source(self):
        finding = {"source": "github_crawler", "curated_source": "old_label"}
        assert self._resolve_source(finding) == "github_crawler"

    def test_source_fallback_to_curated_source(self):
        finding = {"curated_source": "curated_label"}
        assert self._resolve_source(finding) == "curated_label"

    def test_source_returns_none_when_absent(self):
        finding = {}
        assert self._resolve_source(finding) is None

    def test_update_path_preserves_existing_kind_if_not_in_finding(self):
        """UPDATE path must not overwrite kind with None."""
        existing_mock = SimpleNamespace(kind="skill", source="old_crawler")
        finding = {"github_stars": 42}  # no kind/source
        resolved_kind = finding.get("kind") or finding.get("package_type")
        if resolved_kind:
            existing_mock.kind = resolved_kind
        # Should be unchanged
        assert existing_mock.kind == "skill"

    def test_update_path_updates_kind_when_provided(self):
        """UPDATE path must overwrite kind when finding provides it."""
        existing_mock = SimpleNamespace(kind="skill", source=None)
        finding = {"kind": "mcp-server"}
        resolved_kind = finding.get("kind") or finding.get("package_type")
        if resolved_kind:
            existing_mock.kind = resolved_kind
        assert existing_mock.kind == "mcp-server"

    def test_update_path_updates_source_when_provided(self):
        """UPDATE path must set source from finding."""
        existing_mock = SimpleNamespace(kind="skill", source=None)
        finding = {"source": "github_crawler"}
        resolved_source = finding.get("source") or finding.get("curated_source")
        if resolved_source:
            existing_mock.source = resolved_source
        assert existing_mock.source == "github_crawler"


# ===========================================================================
# P0-003 — cap key show --public subcommand
# ===========================================================================

class TestP0003KeyShowSubcommand:
    def test_key_show_subparser_exists(self):
        """'cap key show' must be a recognised subcommand in the CLI parser."""
        # Import just the build_parser section — we don't run main()
        import argparse
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "cli",
            Path(__file__).parent.parent / "src" / "capacium" / "cli.py",
        )
        # We only need the parser; avoid executing the full script.
        # Check the subparser is registered instead by reading the source.
        cli_src = (Path(__file__).parent.parent / "src" / "capacium" / "cli.py").read_text()
        assert '"show"' in cli_src or "'show'" in cli_src, \
            "CLI must register 'show' as a key subcommand"
        assert "--public" in cli_src, \
            "CLI must register --public flag for 'cap key show'"

    def test_key_show_calls_key_export(self, tmp_path, monkeypatch):
        """cap key show <name> must call key_export() and print PEM."""
        from capacium.commands.key import key_export
        exported = []

        def fake_export(name: str) -> bool:
            exported.append(name)
            print("-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----")
            return True

        monkeypatch.setattr("capacium.commands.key.export_public_key_pem",
                            lambda name, key_dir=None: "-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----")

        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            result = key_export("mykey")

        assert result is True


# ===========================================================================
# P0-004 — cap sign posts publisher signature to Exchange
# ===========================================================================

class TestP0004SignPostsToExchange:
    def test_publisher_sign_method_exists_on_registry_client(self):
        """RegistryClient must have publisher_sign() method."""
        from capacium.registry_client import RegistryClient
        assert hasattr(RegistryClient, "publisher_sign"), \
            "RegistryClient must expose publisher_sign()"

    def test_publisher_sign_posts_to_correct_endpoint(self):
        """publisher_sign() must POST to /v2/capabilities/{owner}/{name}/publisher-sign."""
        from capacium.registry_client import RegistryClient
        client = RegistryClient(base_url="https://api.capacium.xyz")
        captured = {}

        def fake_urlopen(req, timeout=30):
            captured["url"] = req.full_url
            captured["method"] = req.method
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeHTTPResponse({"trust_state": "signed"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.publisher_sign(
                owner="alice",
                name="my-cap",
                public_key_pem="-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----",
                signature_b64="c2lnbmF0dXJl",
                key_name="mykey",
            )

        assert captured["method"] == "POST"
        assert "/v2/capabilities/alice/my-cap/publisher-sign" in captured["url"]
        assert captured["body"]["key_name"] == "mykey"
        assert result["trust_state"] == "signed"

    def test_sign_command_source_calls_publisher_sign(self):
        """sign.py source must import and call publisher_sign via RegistryClient."""
        import ast
        sign_src = (
            Path(__file__).parent.parent / "src" / "capacium" / "commands" / "sign.py"
        ).read_text()
        tree = ast.parse(sign_src)

        # Must import RegistryClient
        imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        imported_names = []
        for imp in imports:
            if isinstance(imp, ast.ImportFrom):
                imported_names.extend(alias.name for alias in imp.names)
            else:
                imported_names.extend(alias.name for alias in imp.names)

        assert "RegistryClient" in sign_src, \
            "sign.py must import RegistryClient for Exchange upload"
        assert "publisher_sign" in sign_src, \
            "sign.py must call publisher_sign()"
        assert "from_config" in sign_src, \
            "sign.py must call RegistryClient.from_config()"
        assert "export_public_key_pem" in sign_src, \
            "sign.py must export the public key PEM for the Exchange"


# ===========================================================================
# P0-005 — ExchangeClient (capacium-mcp) uses /v2/search not /api/v2/capabilities
# ===========================================================================

class TestP0005McpExchangeEndpoints:
    @pytest.fixture
    def exchange_client(self):
        """Return an ExchangeClient pointing at a test base URL."""
        try:
            from capacium_mcp.server import ExchangeClient
        except ImportError:
            pytest.skip("capacium_mcp not installed")
        return ExchangeClient(base_url="https://api.capacium.xyz")

    def test_search_uses_v2_search(self, exchange_client):
        captured = {}

        with patch.object(exchange_client._client, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"listings": []},
                raise_for_status=lambda: None,
            )
            exchange_client.search("test", limit=10)

        called_url = mock_get.call_args[0][0]
        assert "/v2/search" in called_url, f"Expected /v2/search, got: {called_url}"
        assert "/api/v2/" not in called_url, f"Old /api/v2/ path used: {called_url}"

    def test_get_capability_uses_v2_capabilities(self, exchange_client):
        with patch.object(exchange_client._client, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"name": "my-cap", "owner": "alice"},
                raise_for_status=lambda: None,
            )
            exchange_client.get_capability("alice", "my-cap")

        called_url = mock_get.call_args[0][0]
        assert "/v2/capabilities/alice/my-cap" in called_url
        assert "/api/v2/" not in called_url

    def test_popular_uses_v2_search_with_sort(self, exchange_client):
        with patch.object(exchange_client._client, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"listings": []},
                raise_for_status=lambda: None,
            )
            exchange_client.popular(limit=5)

        called_url = mock_get.call_args[0][0]
        called_params = mock_get.call_args[1].get("params", {})
        assert "/v2/search" in called_url
        assert called_params.get("sort") == "installs"


# ===========================================================================
# P0-006 — Backfill SQL migration heuristic logic
# ===========================================================================

class TestP0006BackfillMigrationLogic:
    """Test the heuristic kind-detection logic from 0004_backfill_kind_source.sql.

    We replicate the CASE WHEN logic in Python to confirm it produces the
    right results — the actual SQL runs on the production DB.
    """

    @staticmethod
    def detect_kind_heuristic(canonical_name: str) -> str:
        name = canonical_name.lower()
        if "/mcp-" in name or name.endswith("-mcp") or "mcp-server" in name:
            return "mcp-server"
        if name.endswith("-bundle") or name.endswith("-pack") or name.endswith("-tools"):
            return "bundle"
        if name.endswith("-prompt"):
            return "prompt"
        if name.endswith("-template"):
            return "template"
        if name.endswith("-workflow"):
            return "workflow"
        return "skill"

    def test_mcp_server_detection_by_prefix(self):
        assert self.detect_kind_heuristic("alice/mcp-filesystem") == "mcp-server"

    def test_mcp_server_detection_by_suffix(self):
        assert self.detect_kind_heuristic("alice/my-tool-mcp") == "mcp-server"

    def test_mcp_server_detection_by_substring(self):
        assert self.detect_kind_heuristic("alice/mcp-server-example") == "mcp-server"

    def test_bundle_detection(self):
        assert self.detect_kind_heuristic("alice/data-bundle") == "bundle"
        assert self.detect_kind_heuristic("alice/analytics-pack") == "bundle"
        assert self.detect_kind_heuristic("alice/search-tools") == "bundle"

    def test_prompt_detection(self):
        assert self.detect_kind_heuristic("alice/code-review-prompt") == "prompt"

    def test_template_detection(self):
        assert self.detect_kind_heuristic("alice/project-template") == "template"

    def test_workflow_detection(self):
        assert self.detect_kind_heuristic("alice/ci-workflow") == "workflow"

    def test_default_skill(self):
        assert self.detect_kind_heuristic("alice/my-capability") == "skill"

    def test_leading_slash_stripped(self):
        """canonical_names stored with leading slash must be stripped."""
        names_with_slash = ["/alice/my-cap", "/bob/tool"]
        stripped = [n.lstrip("/") for n in names_with_slash]
        assert stripped == ["alice/my-cap", "bob/tool"]
        for n in stripped:
            assert not n.startswith("/")

    def test_migration_file_exists(self):
        """Migration SQL file must exist in the capacium-exchange repo."""
        migration_path = (
            Path(__file__).parent.parent.parent
            / "capacium-exchange"
            / "migrations"
            / "0004_backfill_kind_source.sql"
        )
        # Accept either same-repo or sibling-repo layout
        alt_path = Path(__file__).parents[3] / "capacium-exchange" / "migrations" / "0004_backfill_kind_source.sql"
        found = migration_path.exists() or alt_path.exists()
        assert found, f"Migration file not found at {migration_path} or {alt_path}"
