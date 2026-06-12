"""STAB-007 (V11+): manifest env materialization + secret indirection.

- declared mcp.env blocks land in client configs (clients like Gemini do
  not pass the shell env through — regression: PERPLEXITY_COOKIES)
- secret-looking keys never carry literal values in written configs
  (static guard: ${VAR} indirection via launchd/envctl)
- declared env vars unknown to the server source produce a warning
  (korotovsky: SLACK_BOT_TOKEN vs SLACK_MCP_XOXP_TOKEN)
"""
import json

from capacium.adapters.mcp_config_patcher import McpConfigPatcher
from capacium.commands.install import _warn_unknown_env_vars
from capacium.manifest import Manifest


class TestSanitizeEnvBlock:
    def test_reference_passes_through(self):
        env = McpConfigPatcher.sanitize_env_block(
            {"PERPLEXITY_COOKIES": "${PERPLEXITY_COOKIES}"}
        )
        assert env == {"PERPLEXITY_COOKIES": "${PERPLEXITY_COOKIES}"}

    def test_empty_value_becomes_reference(self):
        env = McpConfigPatcher.sanitize_env_block({"SLACK_MCP_XOXP_TOKEN": ""})
        assert env == {"SLACK_MCP_XOXP_TOKEN": "${SLACK_MCP_XOXP_TOKEN}"}

    def test_literal_secret_is_redacted(self, capsys):
        env = McpConfigPatcher.sanitize_env_block(
            {"SLACK_MCP_XOXP_TOKEN": "xoxp-1234-real-secret"}, "slack-mcp"
        )
        assert env == {"SLACK_MCP_XOXP_TOKEN": "${SLACK_MCP_XOXP_TOKEN}"}
        out = capsys.readouterr().out
        assert "redacted" in out
        assert "xoxp-1234-real-secret" not in out

    def test_harmless_literal_kept(self):
        env = McpConfigPatcher.sanitize_env_block(
            {"SLACK_MCP_LOG_LEVEL": "debug", "PORT": "3001"}
        )
        assert env == {"SLACK_MCP_LOG_LEVEL": "debug", "PORT": "3001"}


class TestEnvLandsInConfigs:
    def _pkg(self, tmp_path):
        pkg = tmp_path / "envful"
        pkg.mkdir()
        (pkg / "capability.yaml").write_text(
            "kind: mcp-server\nname: envful\nversion: 1.0.0\ndescription: t\n"
            "mcp:\n  transport: stdio\n  command: python3\n  args: ['srv.py']\n"
            "  env:\n    PERPLEXITY_COOKIES: '${PERPLEXITY_COOKIES}'\n"
        )
        (pkg / "srv.py").write_text("import os; os.environ['PERPLEXITY_COOKIES']\n")
        return pkg

    def test_json_config_contains_env_block(self, tmp_path):
        pkg = self._pkg(tmp_path)
        manifest = Manifest.detect_from_directory(pkg)
        config_path = tmp_path / "client.json"
        McpConfigPatcher.inject_json_mcp_server(
            config_path=config_path,
            server_key="envful",
            mcp_section_key="mcpServers",
            cap_name="envful",
            source_dir=pkg,
            mcp_meta=manifest.get_mcp_metadata(),
        )
        entry = json.loads(config_path.read_text())["mcpServers"]["envful"]
        assert entry["env"] == {"PERPLEXITY_COOKIES": "${PERPLEXITY_COOKIES}"}

    def test_opencode_entry_contains_env_block(self, tmp_path):
        pkg = self._pkg(tmp_path)
        manifest = Manifest.detect_from_directory(pkg)
        entry = McpConfigPatcher.build_opencode_mcp_entry(
            "envful", pkg, manifest.get_mcp_metadata()
        )
        assert entry["env"] == {"PERPLEXITY_COOKIES": "${PERPLEXITY_COOKIES}"}

    def test_no_plaintext_secret_in_written_config(self, tmp_path):
        pkg = tmp_path / "leaky"
        pkg.mkdir()
        (pkg / "capability.yaml").write_text(
            "kind: mcp-server\nname: leaky\nversion: 1.0.0\ndescription: t\n"
            "mcp:\n  transport: stdio\n  command: python3\n  args: ['s.py']\n"
            "  env:\n    MY_API_KEY: 'sk-live-supersecret'\n"
        )
        manifest = Manifest.detect_from_directory(pkg)
        config_path = tmp_path / "client.json"
        McpConfigPatcher.inject_json_mcp_server(
            config_path=config_path,
            server_key="leaky",
            mcp_section_key="mcpServers",
            cap_name="leaky",
            source_dir=pkg,
            mcp_meta=manifest.get_mcp_metadata(),
        )
        raw = config_path.read_text()
        assert "sk-live-supersecret" not in raw
        entry = json.loads(raw)["mcpServers"]["leaky"]
        assert entry["env"]["MY_API_KEY"] == "${MY_API_KEY}"


class TestUnknownEnvVarWarning:
    def _manifest(self, env_keys):
        env_yaml = "".join(f"    {k}: '${{{k}}}'\n" for k in env_keys)
        return (
            "kind: mcp-server\nname: slack-mcp\nversion: 1.0.0\ndescription: t\n"
            "mcp:\n  transport: stdio\n  command: go\n  args: ['run', '.']\n"
            f"  env:\n{env_yaml}"
        )

    def test_korotovsky_class_mismatch_warns(self, tmp_path, capsys):
        pkg = tmp_path / "slack-mcp"
        pkg.mkdir()
        (pkg / "capability.yaml").write_text(self._manifest(["SLACK_BOT_TOKEN"]))
        (pkg / "main.go").write_text(
            'package main\nimport "os"\n'
            'func main() { os.Getenv("SLACK_MCP_XOXP_TOKEN") }\n'
        )
        manifest = Manifest.detect_from_directory(pkg)
        _warn_unknown_env_vars(pkg, manifest)
        out = capsys.readouterr().out
        assert "SLACK_BOT_TOKEN" in out
        assert "does not appear" in out

    def test_known_env_var_no_warning(self, tmp_path, capsys):
        pkg = tmp_path / "slack-mcp"
        pkg.mkdir()
        (pkg / "capability.yaml").write_text(self._manifest(["SLACK_MCP_XOXP_TOKEN"]))
        (pkg / "main.go").write_text(
            'package main\nimport "os"\n'
            'func main() { os.Getenv("SLACK_MCP_XOXP_TOKEN") }\n'
        )
        manifest = Manifest.detect_from_directory(pkg)
        _warn_unknown_env_vars(pkg, manifest)
        assert "does not appear" not in capsys.readouterr().out
