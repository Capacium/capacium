"""STAB-004 (V10): Go build-from-local-package pipeline.

Install builds runtimes.go MCP servers from the local package (go build,
entrypoint by cmd/ convention) and client configs reference the binary —
never a network-fetching 'go run ...@latest' (korotovsky parity).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from capacium.adapters.mcp_config_patcher import McpConfigPatcher
from capacium.commands.install import _build_go_binary, _go_build_target


def _go_package(root: Path, name: str = "slack-mcp", layout: str = "cmd") -> Path:
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / "go.mod").write_text(f"module example.com/{name}\n\ngo 1.21\n")
    main_go = "package main\n\nfunc main() {}\n"
    if layout == "cmd":
        d = pkg / "cmd" / name
        d.mkdir(parents=True)
        (d / "main.go").write_text(main_go)
    elif layout == "cmd-other":
        d = pkg / "cmd" / "server"
        d.mkdir(parents=True)
        (d / "main.go").write_text(main_go)
    elif layout == "root":
        (pkg / "main.go").write_text(main_go)
    (pkg / "capability.yaml").write_text(
        f"kind: mcp-server\nname: {name}\nversion: 1.0.0\ndescription: t\n"
        "runtimes:\n  go: '>=1.21'\nmcp:\n  transport: stdio\n"
    )
    return pkg


class TestBuildTarget:
    def test_cmd_name_convention(self, tmp_path):
        pkg = _go_package(tmp_path, layout="cmd")
        assert _go_build_target(pkg, "slack-mcp") == "./cmd/slack-mcp"

    def test_first_cmd_dir_fallback(self, tmp_path):
        pkg = _go_package(tmp_path, layout="cmd-other")
        assert _go_build_target(pkg, "slack-mcp") == "./cmd/server"

    def test_root_main_go(self, tmp_path):
        pkg = _go_package(tmp_path, layout="root")
        assert _go_build_target(pkg, "slack-mcp") == "."

    def test_no_target(self, tmp_path):
        pkg = _go_package(tmp_path, layout="none")
        assert _go_build_target(pkg, "slack-mcp") is None


class TestBuildStep:
    def test_build_invokes_go_build_into_bin(self, tmp_path, monkeypatch):
        pkg = _go_package(tmp_path, layout="cmd")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("cwd")))
            Path(cmd[cmd.index("-o") + 1]).write_text("binary")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("capacium.commands.install.shutil.which",
                            lambda n: "/usr/local/bin/go")
        monkeypatch.setattr("capacium.commands.install.subprocess.run", fake_run)

        assert _build_go_binary(pkg, "slack-mcp") == "built"
        assert (pkg / "bin" / "slack-mcp").exists()
        cmd, cwd = calls[0]
        assert cmd[:3] == ["go", "build", "-o"]
        assert cmd[-1] == "./cmd/slack-mcp"
        assert cwd == pkg

    def test_build_failure_reported(self, tmp_path, monkeypatch):
        pkg = _go_package(tmp_path, layout="cmd")
        monkeypatch.setattr("capacium.commands.install.shutil.which",
                            lambda n: "/usr/local/bin/go")
        monkeypatch.setattr(
            "capacium.commands.install.subprocess.run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"),
        )
        assert _build_go_binary(pkg, "slack-mcp") == "failed"

    def test_missing_toolchain_is_soft(self, tmp_path, monkeypatch):
        pkg = _go_package(tmp_path, layout="cmd")
        monkeypatch.setattr("capacium.commands.install.shutil.which", lambda n: None)
        assert _build_go_binary(pkg, "slack-mcp") == "no-toolchain"


class TestEntryUsesBinary:
    def test_entry_references_built_binary(self, tmp_path):
        pkg = _go_package(tmp_path, layout="cmd")
        binary = pkg / "bin" / "slack-mcp"
        binary.parent.mkdir()
        binary.write_text("bin")
        binary.chmod(0o755)

        entry = McpConfigPatcher.build_mcp_entry("slack-mcp", pkg, None)
        assert entry["command"] == str(binary.resolve())
        assert "args" not in entry or entry["args"] == []

    def test_go_run_latest_rewritten_to_binary(self, tmp_path):
        pkg = _go_package(tmp_path, layout="cmd")
        binary = pkg / "bin" / "slack-mcp"
        binary.parent.mkdir()
        binary.write_text("bin")
        binary.chmod(0o755)

        meta = {"command": "go",
                "args": ["run", "github.com/korotovsky/slack-mcp-server@latest"]}
        entry = McpConfigPatcher.build_mcp_entry("slack-mcp", pkg, meta)
        assert entry["command"] == str(binary.resolve())
        assert all("@latest" not in str(a) for a in entry.get("args", []))

    def test_go_run_latest_without_binary_runs_local_package(self, tmp_path):
        pkg = _go_package(tmp_path, layout="cmd")
        meta = {"command": "go",
                "args": ["run", "github.com/korotovsky/slack-mcp-server@latest"]}
        entry = McpConfigPatcher.build_mcp_entry("slack-mcp", pkg, meta)
        assert entry["command"] == "go"
        assert all("@latest" not in str(a) for a in entry.get("args", []))


@pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not on host")
class TestRealGoBuild:
    def test_end_to_end_build_and_entry(self, tmp_path):
        pkg = _go_package(tmp_path, layout="cmd")
        assert _build_go_binary(pkg, "slack-mcp") == "built"
        binary = pkg / "bin" / "slack-mcp"
        assert binary.exists()
        entry = McpConfigPatcher.build_mcp_entry("slack-mcp", pkg, None)
        assert entry["command"] == str(binary.resolve())
