"""Tests for the runtime resolver introduced in v0.7.0."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from capacium.manifest import Manifest
from capacium.runtimes import (
    RUNTIMES,
    RuntimeResolver,
    RuntimeStatus,
    format_failure_report,
    infer_required_runtimes,
    parse_version,
    runtime_for_command,
    satisfies,
)


# ──────────────────────────────────────────────────────────────────────────
# Manifest parsing
# ──────────────────────────────────────────────────────────────────────────

class TestManifestRuntimes:
    def test_runtimes_field_parses_from_yaml(self, tmp_path):
        path = tmp_path / "capability.yaml"
        path.write_text(
            "kind: mcp-server\n"
            "name: example\n"
            "version: 1.0.0\n"
            "runtimes:\n"
            "  uv: '>=0.4.0'\n"
            "  node: '>=20'\n"
        )
        m = Manifest.load(path)
        assert m.runtimes == {"uv": ">=0.4.0", "node": ">=20"}

    def test_runtimes_field_default_empty(self):
        m = Manifest(name="x", version="1.0.0")
        assert m.runtimes == {}

    def test_runtimes_field_non_dict_normalized(self):
        m = Manifest.from_dict({"name": "x", "version": "1.0.0", "runtimes": "garbage"})
        assert m.runtimes == {}

    def test_runtimes_field_none_value_becomes_star(self):
        m = Manifest.from_dict({"name": "x", "version": "1.0.0", "runtimes": {"docker": None}})
        assert m.runtimes == {"docker": "*"}


# ──────────────────────────────────────────────────────────────────────────
# Auto-inference
# ──────────────────────────────────────────────────────────────────────────

class TestRuntimeForCommand:
    @pytest.mark.parametrize(
        "command,expected",
        [
            ("uvx", "uv"),
            ("uv", "uv"),
            ("npx", "node"),
            ("npm", "node"),
            ("node", "node"),
            ("pipx", "pipx"),
            ("python3", "python"),
            ("python", "python"),
            ("docker", "docker"),
            ("go", "go"),
            ("bun", "bun"),
            ("bunx", "bun"),
            ("deno", "deno"),
            ("/usr/local/bin/uvx", "uv"),
            ("uvx some-mcp-package", "uv"),
            ("rustc", None),
            ("", None),
        ],
    )
    def test_known_and_unknown_commands(self, command, expected):
        assert runtime_for_command(command) == expected


class TestInferRequiredRuntimes:
    def test_infers_from_mcp_command_when_missing(self):
        m = Manifest(kind="mcp-server", mcp={"command": "uvx", "args": ["my-mcp"]})
        assert infer_required_runtimes(m) == {"uv": "*"}

    def test_explicit_runtimes_win_over_inference(self):
        m = Manifest(
            kind="mcp-server",
            mcp={"command": "uvx"},
            runtimes={"uv": ">=0.4.0"},
        )
        assert infer_required_runtimes(m) == {"uv": ">=0.4.0"}

    def test_npx_infers_node(self):
        m = Manifest(kind="mcp-server", mcp={"command": "npx"})
        assert infer_required_runtimes(m) == {"node": "*"}

    def test_docker_infers_docker(self):
        m = Manifest(kind="mcp-server", mcp={"command": "docker"})
        assert infer_required_runtimes(m) == {"docker": "*"}

    def test_no_command_no_runtimes(self):
        m = Manifest(kind="skill")
        assert infer_required_runtimes(m) == {}

    def test_unknown_command_no_inference(self):
        m = Manifest(kind="mcp-server", mcp={"command": "totally-made-up"})
        assert infer_required_runtimes(m) == {}


# ──────────────────────────────────────────────────────────────────────────
# Version comparison
# ──────────────────────────────────────────────────────────────────────────

class TestParseVersion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("v20.10.0", (20, 10, 0)),
            ("uv 0.4.5", (0, 4, 5)),
            ("Python 3.11.7", (3, 11, 7)),
            ("go version go1.22.0 linux/amd64", (1, 22, 0)),
            ("0.4", (0, 4, 0)),
            ("", (0,)),
            ("garbage", (0,)),
        ],
    )
    def test_parse(self, raw, expected):
        assert parse_version(raw) == expected


class TestSatisfies:
    @pytest.mark.parametrize(
        "version,requirement,expected",
        [
            ("1.0.0", "*", True),
            ("1.0.0", "", True),
            ("1.0.0", ">=1.0.0", True),
            ("1.0.0", ">=1.0.1", False),
            ("0.4.5", ">=0.4.0", True),
            ("0.3.9", ">=0.4.0", False),
            ("20.10.0", ">=20", True),
            ("19.0.0", ">=20", False),
            ("1.22.0", ">=1.22", True),
            ("3.10.0", "3.10.0", True),    # bare → loose >=
            ("3.11.0", "3.10.0", True),
            ("3.9.0", "3.10.0", False),
            ("1.0.0", "garbage spec", True),  # permissive fallback
        ],
    )
    def test_compare(self, version, requirement, expected):
        assert satisfies(version, requirement) is expected


# ──────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────

class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestRuntimeResolver:
    def test_detect_present(self):
        which = lambda cmd: "/usr/bin/uv"  # noqa: E731
        run = lambda *a, **kw: _FakeCompleted(stdout="uv 0.4.18\n")  # noqa: E731
        r = RuntimeResolver(which=which, run=run)
        found, version, err = r.detect("uv")
        assert found is True
        assert version == "0.4.18"
        assert err is None

    def test_detect_missing(self):
        which = lambda cmd: None  # noqa: E731
        r = RuntimeResolver(which=which, run=lambda *a, **kw: _FakeCompleted())
        found, version, err = r.detect("uv")
        assert found is False
        assert version is None
        assert err is None

    def test_detect_unknown_runtime(self):
        r = RuntimeResolver(which=lambda c: None, run=lambda *a, **kw: _FakeCompleted())
        found, version, err = r.detect("totally-fictitious")
        assert found is False
        assert err and "unknown runtime" in err

    def test_resolve_satisfied(self):
        which = lambda cmd: f"/usr/bin/{cmd}"  # noqa: E731
        run = lambda *a, **kw: _FakeCompleted(stdout="0.4.18\n")  # noqa: E731
        r = RuntimeResolver(which=which, run=run)
        statuses = r.resolve({"uv": ">=0.4.0"})
        assert len(statuses) == 1
        s = statuses[0]
        assert s.found is True
        assert s.satisfied is True
        assert s.ok is True

    def test_resolve_version_mismatch(self):
        which = lambda cmd: f"/usr/bin/{cmd}"  # noqa: E731
        run = lambda *a, **kw: _FakeCompleted(stdout="0.3.0\n")  # noqa: E731
        r = RuntimeResolver(which=which, run=run)
        statuses = r.resolve({"uv": ">=0.4.0"})
        assert statuses[0].found is True
        assert statuses[0].satisfied is False
        assert statuses[0].ok is False

    def test_resolve_missing_with_install_hint(self):
        which = lambda cmd: None  # noqa: E731
        r = RuntimeResolver(which=which, run=lambda *a, **kw: _FakeCompleted())
        statuses = r.resolve({"uv": ">=0.4.0"})
        s = statuses[0]
        assert s.ok is False
        # Install hint always populated when runtime is in registry.
        assert s.install_hint is not None

    def test_resolve_unknown_runtime_returns_status(self):
        r = RuntimeResolver(which=lambda c: None, run=lambda *a, **kw: _FakeCompleted())
        statuses = r.resolve({"made-up-runtime": "*"})
        assert len(statuses) == 1
        assert statuses[0].runtime is None
        assert statuses[0].ok is False


# ──────────────────────────────────────────────────────────────────────────
# Install hints
# ──────────────────────────────────────────────────────────────────────────

class TestInstallHints:
    def test_darwin_hint(self):
        rt = RUNTIMES["uv"]
        assert rt.install_hint_for("darwin") == "brew install uv"

    def test_linux_hint(self):
        rt = RUNTIMES["uv"]
        assert "astral.sh" in rt.install_hint_for("linux")

    def test_win32_hint(self):
        rt = RUNTIMES["uv"]
        assert "winget" in rt.install_hint_for("win32")

    def test_unknown_platform_returns_none(self):
        rt = RUNTIMES["uv"]
        assert rt.install_hint_for("plan9") is None


class TestFormatFailureReport:
    def test_empty_when_all_ok(self):
        ok = [RuntimeStatus(name="uv", requirement="*", runtime=RUNTIMES["uv"],
                            found=True, version="0.4.0", satisfied=True)]
        assert format_failure_report(ok) == ""

    def test_lists_failures_with_hints(self):
        bad = [RuntimeStatus(name="uv", requirement=">=0.4.0", runtime=RUNTIMES["uv"],
                             found=False, version=None, satisfied=False,
                             install_hint=RUNTIMES["uv"].install_hint_for("darwin"))]
        out = format_failure_report(bad, platform="darwin")
        assert "uv" in out
        assert "brew install uv" in out
        assert "--skip-runtime-check" in out


# ──────────────────────────────────────────────────────────────────────────
# Doctor command
# ──────────────────────────────────────────────────────────────────────────

class TestDoctor:
    def _install_capability(self, tmp_path, monkeypatch, manifest_yaml: str, name="cap-x"):
        # Create source
        src = tmp_path / name
        src.mkdir()
        (src / "capability.yaml").write_text(manifest_yaml)
        (src / "main.py").write_text("# x")
        # Point home to tmp_path so registry lives there
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        # Install with runtime check skipped (we want a registered cap regardless)
        from capacium.commands.install import install_capability
        ok = install_capability(name, source_dir=src, skip_runtime_check=True)
        assert ok is True
        return src

    def test_doctor_no_runtimes_passes(self, tmp_path, monkeypatch, capsys):
        manifest = (
            "kind: skill\n"
            "name: cap-noop\n"
            "version: 1.0.0\n"
        )
        self._install_capability(tmp_path, monkeypatch, manifest, name="cap-noop")

        from capacium.commands.doctor import doctor
        assert doctor() is True
        out = capsys.readouterr().out
        assert "no runtime requirements" in out

    def test_doctor_missing_runtime_fails(self, tmp_path, monkeypatch, capsys):
        manifest = (
            "kind: mcp-server\n"
            "name: cap-needs-uv\n"
            "version: 1.0.0\n"
            "runtimes:\n"
            "  uv: '>=0.4.0'\n"
            "mcp:\n"
            "  transport: stdio\n"
            "  supported_clients: [claude-code]\n"
            "  command: uvx\n"
            "  args: [my-mcp]\n"
        )
        self._install_capability(tmp_path, monkeypatch, manifest, name="cap-needs-uv")

        # Mock RuntimeResolver inside the doctor module so 'uv' is reported missing.
        with patch("capacium.commands.doctor.RuntimeResolver") as mock_resolver_cls:
            instance = mock_resolver_cls.return_value
            instance.resolve.return_value = [
                RuntimeStatus(
                    name="uv",
                    requirement=">=0.4.0",
                    runtime=RUNTIMES["uv"],
                    found=False,
                    version=None,
                    satisfied=False,
                    install_hint="brew install uv",
                )
            ]
            from capacium.commands.doctor import doctor
            assert doctor() is False

        out = capsys.readouterr().out
        assert "uv" in out
        assert "brew install uv" in out


# ──────────────────────────────────────────────────────────────────────────
# Pre-flight install gate
# ──────────────────────────────────────────────────────────────────────────

class TestInstallPreflight:
    def test_install_blocks_when_runtime_missing(self, tmp_path, monkeypatch, capsys):
        src = tmp_path / "needs-uv"
        src.mkdir()
        (src / "capability.yaml").write_text(
            "kind: mcp-server\n"
            "name: needs-uv\n"
            "version: 1.0.0\n"
            "runtimes:\n"
            "  uv: '>=0.4.0'\n"
            "mcp:\n"
            "  transport: stdio\n"
            "  supported_clients: [claude-code]\n"
            "  command: uvx\n"
            "  args: [pkg]\n"
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # Mock the resolver inside install to report uv missing
        with patch("capacium.commands.install.RuntimeResolver") as mock_resolver_cls:
            instance = mock_resolver_cls.return_value
            instance.resolve.return_value = [
                RuntimeStatus(
                    name="uv",
                    requirement=">=0.4.0",
                    runtime=RUNTIMES["uv"],
                    found=False,
                    version=None,
                    satisfied=False,
                    install_hint="brew install uv",
                )
            ]
            from capacium.commands.install import install_capability
            success = install_capability("needs-uv", source_dir=src)
        assert success is False
        out = capsys.readouterr().out
        assert "uv" in out
        assert "--skip-runtime-check" in out

    def test_install_skip_runtime_check_bypasses(self, tmp_path, monkeypatch):
        src = tmp_path / "needs-uv-bypass"
        src.mkdir()
        (src / "capability.yaml").write_text(
            "kind: skill\n"
            "name: needs-uv-bypass\n"
            "version: 1.0.0\n"
            "runtimes:\n"
            "  uv: '>=999.0.0'\n"
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        from capacium.commands.install import install_capability
        success = install_capability(
            "needs-uv-bypass", source_dir=src, skip_runtime_check=True
        )
        assert success is True


# ──────────────────────────────────────────────────────────────────────────
# `cap runtimes` command
# ──────────────────────────────────────────────────────────────────────────

class TestRuntimesCommand:
    def test_list_runtimes_runs(self, capsys):
        from capacium.commands.runtimes_cmd import list_runtimes
        # Use a resolver that always reports missing so we don't depend on host state.
        with patch("capacium.commands.runtimes_cmd.RuntimeResolver") as mock_resolver_cls:
            instance = mock_resolver_cls.return_value
            instance.detect.return_value = (False, None, None)
            assert list_runtimes() is True
        out = capsys.readouterr().out
        assert "uv" in out
        assert "node" in out

    def test_install_hint_known(self, capsys):
        from capacium.commands.runtimes_cmd import show_install_hint
        assert show_install_hint("uv", platform="darwin") is True
        out = capsys.readouterr().out
        assert "brew install uv" in out
        assert "does NOT run" in out or "DOES NOT" in out.upper() or "does NOT" in out

    def test_install_hint_unknown(self, capsys):
        from capacium.commands.runtimes_cmd import show_install_hint
        assert show_install_hint("totally-bogus") is False
        out = capsys.readouterr().out
        assert "Unknown runtime" in out
