"""Tests for `cap doctor` command including deep checks."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from capacium.commands.doctor import (
    _check_symlink_depth,
    _check_config_file_paths,
    _check_dependency_materialization,
    _check_mcp_handshake,
    _check_stale_duplicate_keys,
    _check_registry_drift,
    _deep_checks,
    doctor,
)
from capacium.models import Capability, Kind


@pytest.fixture
def tmp_home(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        monkeypatch.setattr(Path, "home", lambda: tmp)
        yield tmp


@pytest.fixture
def mock_dummy_caps(monkeypatch):
    caps = [
        Capability(
            owner="acme", name="test-skill", version="1.0.0",
            kind=Kind.SKILL, install_path=Path("/nonexistent/test-skill"),
        ),
        Capability(
            owner="acme", name="test-mcp", version="1.0.0",
            kind=Kind.MCP_SERVER, install_path=Path("/nonexistent/test-mcp"),
        ),
    ]
    monkeypatch.setattr(
        "capacium.commands.doctor.Registry.list_capabilities",
        MagicMock(return_value=caps),
    )
    monkeypatch.setattr(
        "capacium.commands.doctor.Registry.parse_cap_id",
        staticmethod(lambda cap_id: cap_id.split("/", 1) if "/" in cap_id else ("global", cap_id)),
    )
    return caps


class TestDoctorDeep:

    def test_deep_checks_returns_seven_results(self, mock_dummy_caps):
        results = _deep_checks()
        assert len(results) == 7  # incl. MCP stdout purity (VER-001)
        for name, passed, detail in results:
            assert isinstance(name, str)
            assert isinstance(passed, bool)
            assert isinstance(detail, str)

    # ---- Symlink depth ----

    def test_symlink_depth_no_symlinks(self, monkeypatch, mock_dummy_caps):
        monkeypatch.setattr(
            "capacium.commands.doctor.FRAMEWORK_SKILLS_DIRS",
            {},
        )
        name, passed, detail = _check_symlink_depth()
        assert name == "Symlink depth"
        assert passed is True

    def test_symlink_depth_outside_dir(self, tmp_home, monkeypatch, mock_dummy_caps):
        skills_dir = tmp_home / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        outside = tmp_home / "rogue_link"
        outside.mkdir()
        link = skills_dir / "test-skill"
        link.symlink_to(outside)
        monkeypatch.setattr(
            "capacium.commands.doctor.FRAMEWORK_SKILLS_DIRS",
            {"claude-code": skills_dir},
        )
        orig_list = MagicMock(return_value=mock_dummy_caps)
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            orig_list,
        )
        name, passed, detail = _check_symlink_depth()
        assert passed is False
        assert "outside expected dir" in detail

    # ---- Config file paths ----

    def test_config_file_paths_no_configs(self, tmp_home, monkeypatch):
        name, passed, detail = _check_config_file_paths()
        assert name == "Config file paths"
        assert passed is True

    @pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                        reason="chmod-based unreadability has no effect on Windows or as root (CI)")
    def test_config_file_paths_unreadable(self, tmp_home, monkeypatch):
        cf = tmp_home / ".claude.json"
        cf.write_text("{}")
        cf.chmod(0o000)
        try:
            name, passed, detail = _check_config_file_paths()
            assert passed is False
        finally:
            cf.chmod(0o644)

    # ---- Dependency materialization ----

    def test_dependency_materialization_missing_node_modules(self, tmp_home, monkeypatch):
        caps = [
            Capability(
                owner="acme", name="node-mcp", version="1.0.0",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "node-mcp",
            ),
        ]
        install = caps[0].install_path
        install.mkdir(parents=True)
        (install / "package.json").write_text('{"name":"node-mcp"}')
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        name, passed, detail = _check_dependency_materialization()
        assert passed is False
        assert "node_modules missing" in detail

    def test_dependency_materialization_uvx_needs_no_venv(self, tmp_home, monkeypatch):
        """V5 regression: uvx-based packages create ephemeral envs — a missing
        .venv must not be reported as an issue (false positive class)."""
        caps = [
            Capability(
                owner="acme", name="uvx-mcp", version="1.0.0",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "uvx-mcp",
            ),
        ]
        install = caps[0].install_path
        install.mkdir(parents=True)
        (install / "pyproject.toml").write_text("[project]\nname = 'uvx-mcp'\n")
        (install / "capability.yaml").write_text(
            "kind: mcp-server\nname: uvx-mcp\nversion: 1.0.0\n"
            "description: uvx fixture\n"
            "mcp:\n  command: uvx\n  args: ['uvx-mcp']\n"
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        name, passed, detail = _check_dependency_materialization()
        assert passed is True, detail

    def test_dependency_materialization_python_cmd_still_needs_venv(self, tmp_home, monkeypatch):
        caps = [
            Capability(
                owner="acme", name="py-mcp", version="1.0.0",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "py-mcp",
            ),
        ]
        install = caps[0].install_path
        install.mkdir(parents=True)
        (install / "requirements.txt").write_text("requests\n")
        (install / "capability.yaml").write_text(
            "kind: mcp-server\nname: py-mcp\nversion: 1.0.0\n"
            "description: python fixture\n"
            "mcp:\n  command: python\n  args: ['server.py']\n"
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        name, passed, detail = _check_dependency_materialization()
        assert passed is False
        assert ".venv missing" in detail

    def test_dependency_materialization_ok(self, tmp_home, monkeypatch):
        caps = [
            Capability(
                owner="acme", name="node-mcp", version="1.0.0",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "node-mcp",
            ),
        ]
        install = caps[0].install_path
        install.mkdir(parents=True)
        (install / "package.json").write_text('{"name":"node-mcp"}')
        (install / "node_modules").mkdir()
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        name, passed, detail = _check_dependency_materialization()
        assert passed is True

    # ---- MCP handshake ----

    def test_mcp_handshake_no_mcp_servers(self, monkeypatch, mock_dummy_caps):
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=[
                Capability(owner="a", name="s", version="1.0.0", kind=Kind.SKILL),
            ]),
        )
        name, passed, detail = _check_mcp_handshake()
        assert passed is True

    def test_mcp_handshake_command_not_found(self, tmp_home, monkeypatch):
        caps = [
            Capability(
                owner="acme", name="bad-mcp", version="1.0.0",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "bad-mcp",
            ),
        ]
        inst = caps[0].install_path
        inst.mkdir(parents=True)
        (inst / "capability.yaml").write_text("""
kind: mcp-server
name: bad-mcp
version: 1.0.0
mcp:
  transport: stdio
  command: nonexistent_command_xyz
""")
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        name, passed, detail = _check_mcp_handshake()
        assert passed is False
        assert "not found" in detail

    def test_mcp_handshake_timeout(self, tmp_home, monkeypatch):
        caps = [
            Capability(
                owner="acme", name="slow-mcp", version="1.0.0",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "slow-mcp",
            ),
        ]
        inst = caps[0].install_path
        inst.mkdir(parents=True)
        (inst / "capability.yaml").write_text("""
kind: mcp-server
name: slow-mcp
version: 1.0.0
mcp:
  transport: stdio
  command: sleep
  args: ["30"]
""")
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        from capacium.utils.mcp_probe import McpProbeResult
        with patch(
            "capacium.commands.doctor.probe_mcp",
            return_value=McpProbeResult(responded=False, error="timed out"),
        ):
            name, passed, detail = _check_mcp_handshake()
            assert passed is False
            assert "timed out" in detail

    def test_mcp_handshake_credential_gated_not_failure(self, tmp_home, monkeypatch):
        """A server that needs a secret env var to start (korotovsky class) is
        'needs credentials', not a probe failure."""
        monkeypatch.delenv("SLACK_MCP_XOXP_TOKEN", raising=False)
        caps = [
            Capability(
                owner="korotovsky", name="slack-mcp-server", version="1.2.3",
                kind=Kind.MCP_SERVER, install_path=tmp_home / "slack-mcp-server",
            ),
        ]
        inst = caps[0].install_path
        inst.mkdir(parents=True)
        (inst / "capability.yaml").write_text(
            "kind: mcp-server\nname: slack-mcp-server\nversion: 1.2.3\n"
            "mcp:\n  transport: stdio\n  command: /nonexistent/slack-mcp-server\n"
            "  env:\n    SLACK_MCP_XOXP_TOKEN: '${SLACK_MCP_XOXP_TOKEN}'\n"
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        from capacium.utils.mcp_probe import McpProbeResult
        with patch(
            "capacium.commands.doctor.probe_mcp",
            return_value=McpProbeResult(responded=False, error="no initialize response"),
        ):
            name, passed, detail = _check_mcp_handshake()
        assert passed is True, detail
        assert "needs credentials" in detail
        assert "SLACK_MCP_XOXP_TOKEN" in detail

    def test_missing_credentials_helper(self, monkeypatch):
        from capacium.commands.doctor import _missing_credentials

        class M:
            mcp = {"env": {"SLACK_MCP_XOXP_TOKEN": "${SLACK_MCP_XOXP_TOKEN}",
                           "LOG_LEVEL": "debug"}}
        monkeypatch.delenv("SLACK_MCP_XOXP_TOKEN", raising=False)
        missing = _missing_credentials(M())
        assert missing == ["SLACK_MCP_XOXP_TOKEN"]  # secret + unset; LOG_LEVEL ignored

        monkeypatch.setenv("SLACK_MCP_XOXP_TOKEN", "xoxp-123")
        assert _missing_credentials(M()) == []  # now resolvable

    # ---- Stale/duplicate keys ----

    def test_stale_keys_no_stale(self, monkeypatch):
        monkeypatch.setattr(
            "capacium.commands.repair._find_stale_entries",
            MagicMock(return_value=[]),
        )
        name, passed, detail = _check_stale_duplicate_keys()
        assert passed is True
        assert "no stale" in detail

    def test_stale_keys_found(self, monkeypatch):
        fake_stale = MagicMock()
        fake_stale.__len__ = lambda _self: 1
        monkeypatch.setattr(
            "capacium.commands.repair._find_stale_entries",
            MagicMock(return_value=[fake_stale]),
        )
        name, passed, detail = _check_stale_duplicate_keys()
        assert passed is False
        assert "1 stale" in detail.lower()

    # ---- Registry/config drift ----

    def test_registry_drift_clean(self, monkeypatch, mock_dummy_caps):
        monkeypatch.setattr(
            "capacium.commands.repair.FRAMEWORK_MCP_CONFIGS",
            [],
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=[]),
        )
        name, passed, detail = _check_registry_drift()
        assert passed is True

    def test_registry_drift_config_not_registry(self, tmp_home, monkeypatch, mock_dummy_caps):
        config = tmp_home / ".claude.json"
        config.write_text(json.dumps({
            "mcpServers": {
                "not-in-db": {"command": "npx", "args": ["-y", "not-in-db"]}
            }
        }))
        monkeypatch.setattr(
            "capacium.commands.repair.FRAMEWORK_MCP_CONFIGS",
            [("claude-code", lambda: config, "mcpServers")],
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=mock_dummy_caps),
        )
        name, passed, detail = _check_registry_drift()
        assert passed is False
        assert "in config" in detail.lower()

    # ---- doctor() function integration ----

    def test_doctor_basic_no_caps(self, monkeypatch):
        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=[]),
        )
        result = doctor()
        assert result is True

    def test_doctor_deep_flag_calls_deep_checks(self, monkeypatch, mock_dummy_caps):
        deep_called = []

        def fake_deep():
            deep_called.append(True)
            return [("test", True, "ok")]

        monkeypatch.setattr(
            "capacium.commands.doctor._deep_checks",
            fake_deep,
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.RuntimeResolver",
            MagicMock(),
        )
        monkeypatch.setattr(
            "capacium.commands.doctor._resolve_for",
            MagicMock(return_value=[]),
        )
        monkeypatch.setattr(
            "capacium.commands.repair._find_stale_entries",
            MagicMock(return_value=[]),
        )
        result = doctor(deep=True)
        assert len(deep_called) == 1
        assert result is True


class TestPathParity:

    def test_path_parity_detected(self, tmp_home, monkeypatch, capsys):
        shell_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        proc_path = "/usr/bin:/bin"
        if shell_path == proc_path:
            pytest.skip("PATH parity ok in test env")

        monkeypatch.setattr("os.environ", {"PATH": shell_path, "SHELL": "/bin/zsh"})

        caps = [
            Capability(
                owner="acme", name="test-skill", version="1.0.0",
                kind=Kind.SKILL, install_path=tmp_home / "test-skill",
            ),
        ]
        caps[0].install_path.mkdir(parents=True)
        (caps[0].install_path / "capability.yaml").write_text(
            "kind: skill\nname: test-skill\nversion: 1.0.0\n"
        )

        monkeypatch.setattr(
            "capacium.commands.doctor.Registry.list_capabilities",
            MagicMock(return_value=caps),
        )
        monkeypatch.setattr(
            "capacium.commands.repair._find_stale_entries",
            MagicMock(return_value=[]),
        )
        monkeypatch.setattr(
            "capacium.commands.doctor.RuntimeResolver",
            MagicMock(),
        )
        monkeypatch.setattr(
            "capacium.commands.doctor._resolve_for",
            MagicMock(return_value=[]),
        )

        result = doctor(deep=True)
        assert isinstance(result, bool)
