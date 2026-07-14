"""STAB-003 (V5): runtime validation before MCP config writes.

The config builder must validate manifest runtimes against the
RuntimeResolver BEFORE any client config write. An unmet runtime aborts the
install with an install hint and writes no entry. Go projects must never be
auto-detected as npx (2026-06-10 regression: korotovsky/karldane class).
"""
import json

import pytest

from capacium.adapters.mcp_config_patcher import (
    McpConfigPatcher,
    RuntimeUnavailableError,
)
from capacium.runtimes import RUNTIMES, RuntimeStatus


class FakeResolver:
    """Host-independent resolver: `available` maps runtime name -> version."""

    def __init__(self, available=None):
        self.available = available or {}

    def resolve(self, requirements):
        statuses = []
        for name, req in requirements.items():
            rt = RUNTIMES.get(name)
            version = self.available.get(name)
            found = version is not None
            statuses.append(
                RuntimeStatus(
                    name=name,
                    requirement=req or "*",
                    runtime=rt,
                    found=found,
                    version=version,
                    satisfied=found,
                    install_hint=rt.install_hint_for("darwin") if rt else None,
                )
            )
        return statuses


@pytest.fixture(autouse=True)
def _enforce_gate(monkeypatch):
    """The suite-wide conftest disables the gate; these tests need it live."""
    monkeypatch.delenv("CAPACIUM_SKIP_RUNTIME_CHECK", raising=False)
    McpConfigPatcher.clear_runtime_status_cache()


def _go_project(tmp_path, with_package_json=False, declare_runtime=True):
    pkg = tmp_path / "go-server"
    pkg.mkdir()
    (pkg / "go.mod").write_text("module example.com/go-server\n\ngo 1.22\n")
    (pkg / "main.go").write_text("package main\nfunc main() {}\n")
    if with_package_json:
        # Some Go repos ship a package.json for docs tooling — it must not win.
        (pkg / "package.json").write_text('{"name": "docs-tooling"}')
    runtimes = "runtimes:\n  go: '>=1.21'\n" if declare_runtime else ""
    (pkg / "capability.yaml").write_text(
        "kind: mcp-server\nname: go-server\nversion: 1.0.0\n"
        "description: go fixture\n" + runtimes
    )
    return pkg


class TestGoNeverNpx:
    def test_autodetect_prefers_go_over_package_json(self, tmp_path):
        pkg = _go_project(tmp_path, with_package_json=True)
        entry = McpConfigPatcher.build_mcp_entry(
            "go-server", pkg, None, resolver=FakeResolver({"go": "1.22.1"})
        )
        assert entry["command"] == "go"
        assert entry["command"] not in ("npx", "node")

    def test_declared_go_runtime_never_npx(self, tmp_path):
        pkg = _go_project(tmp_path, with_package_json=True)
        entry = McpConfigPatcher.build_mcp_entry(
            "go-server", pkg, None, resolver=FakeResolver({"go": "1.22.1"})
        )
        assert entry["command"] == "go"


class TestRuntimeGateBlocksWrites:
    def test_missing_go_runtime_aborts_before_config_write(self, tmp_path):
        pkg = _go_project(tmp_path)
        config_path = tmp_path / "client" / "config.json"
        with pytest.raises(RuntimeUnavailableError) as exc_info:
            McpConfigPatcher.inject_json_mcp_server(
                config_path=config_path,
                server_key="go-server",
                mcp_section_key="mcpServers",
                cap_name="go-server",
                source_dir=pkg,
                mcp_meta=None,
                resolver=FakeResolver({}),  # go missing
            )
        # Zero bytes written outside: no config file, no backup
        assert not config_path.exists()
        assert not config_path.parent.exists()
        # The error carries the platform install hint (brew on darwin)
        assert "go" in str(exc_info.value)
        assert "brew install go" in str(exc_info.value)

    def test_missing_runtime_leaves_existing_config_untouched(self, tmp_path):
        pkg = _go_project(tmp_path)
        config_path = tmp_path / "config.json"
        before = json.dumps({"mcpServers": {"other": {"command": "x"}}})
        config_path.write_text(before)
        with pytest.raises(RuntimeUnavailableError):
            McpConfigPatcher.inject_json_mcp_server(
                config_path=config_path,
                server_key="go-server",
                mcp_section_key="mcpServers",
                cap_name="go-server",
                source_dir=pkg,
                mcp_meta=None,
                resolver=FakeResolver({}),
            )
        assert config_path.read_text() == before
        # no backup files created either
        assert list(config_path.parent.glob("*.bak")) == []

    def test_satisfied_runtime_writes_entry(self, tmp_path):
        pkg = _go_project(tmp_path)
        config_path = tmp_path / "config.json"
        ok = McpConfigPatcher.inject_json_mcp_server(
            config_path=config_path,
            server_key="go-server",
            mcp_section_key="mcpServers",
            cap_name="go-server",
            source_dir=pkg,
            mcp_meta=None,
            resolver=FakeResolver({"go": "1.22.1"}),
        )
        assert ok is True
        config = json.loads(config_path.read_text())
        assert "go-server" in config["mcpServers"]
        assert config["mcpServers"]["go-server"]["command"] == "go"

    def test_mcp_meta_command_runtime_is_validated(self, tmp_path):
        pkg = tmp_path / "py-server"
        pkg.mkdir()
        with pytest.raises(RuntimeUnavailableError):
            McpConfigPatcher.build_mcp_entry(
                "py-server",
                pkg,
                {"command": "uvx", "args": ["py-server"]},
                resolver=FakeResolver({}),  # uv missing
            )

    def test_url_transport_skips_runtime_gate(self, tmp_path):
        pkg = tmp_path / "remote"
        pkg.mkdir()
        entry = McpConfigPatcher.build_mcp_entry(
            "remote",
            pkg,
            {"transport": "sse", "url": "http://localhost:9999/x"},
            resolver=FakeResolver({}),
        )
        assert entry["url"] == "http://localhost:9999/x"

    def test_env_var_skips_gate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CAPACIUM_SKIP_RUNTIME_CHECK", "1")
        pkg = _go_project(tmp_path)
        entry = McpConfigPatcher.build_mcp_entry(
            "go-server", pkg, None, resolver=FakeResolver({})
        )
        assert entry["command"] == "go"

    def test_opencode_entry_is_gated(self, tmp_path):
        pkg = _go_project(tmp_path)
        with pytest.raises(RuntimeUnavailableError):
            McpConfigPatcher.build_opencode_mcp_entry(
                "go-server", pkg, None, resolver=FakeResolver({})
            )
