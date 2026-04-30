from pathlib import Path
from capacium.adapters.claude_code import ClaudeCodeAdapter
from capacium.adapters.gemini_cli import GeminiCLIAdapter
from capacium.adapters.opencode import OpenCodeAdapter
from capacium.adapters.openclaw import OpenClawAdapter
from capacium.adapters.hermes import HermesAdapter
from capacium.adapters.copilot import CopilotAdapter
from capacium.adapters.cursor import CursorAdapter
from capacium.adapters import get_adapter, get_adapter_for_manifest, register_adapter
from capacium.adapters.base import FrameworkAdapter
from capacium.manifest import Manifest


class TestClaudeCodeAdapter:

    def test_install_capability(self, tmp_home, sample_capability_dir):
        adapter = ClaudeCodeAdapter()
        result = adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert result is True
        assert adapter.capability_exists("test-cap")

    def test_remove_capability(self, tmp_home, sample_capability_dir):
        adapter = ClaudeCodeAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert adapter.capability_exists("test-cap")

        result = adapter.remove_capability("test-cap")
        assert result is True
        assert not adapter.capability_exists("test-cap")

    def test_remove_nonexistent(self, tmp_home):
        adapter = ClaudeCodeAdapter()
        result = adapter.remove_capability("nonexistent")
        assert result is True

    def test_capability_exists_false_for_missing(self, tmp_home):
        adapter = ClaudeCodeAdapter()
        assert not adapter.capability_exists("nonexistent")

    def test_list_capabilities_empty(self, tmp_home):
        adapter = ClaudeCodeAdapter()
        assert adapter.list_capabilities() == []

    def test_list_capabilities(self, tmp_home, sample_capability_dir):
        adapter = ClaudeCodeAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        caps = adapter.list_capabilities()
        assert "test-cap" in caps

    def test_list_capabilities_multiple(self, tmp_home, tmp_path):
        adapter = ClaudeCodeAdapter()
        cap_a = tmp_path / "cap-a"
        cap_a.mkdir()
        (cap_a / "a.txt").write_text("a")
        cap_b = tmp_path / "cap-b"
        cap_b.mkdir()
        (cap_b / "b.txt").write_text("b")

        adapter.install_capability("cap-a", "1.0.0", cap_a)
        adapter.install_capability("cap-b", "1.0.0", cap_b)

        caps = adapter.list_capabilities()
        assert "cap-a" in caps
        assert "cap-b" in caps

    def test_get_capability_metadata(self, tmp_home, sample_capability_dir):
        adapter = ClaudeCodeAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        meta = adapter.get_capability_metadata("test-cap")
        assert meta is not None
        assert meta["name"] == "test-cap"
        assert meta["version"] == "1.0.0"

    def test_get_capability_metadata_nonexistent(self, tmp_home):
        adapter = ClaudeCodeAdapter()
        assert adapter.get_capability_metadata("nonexistent") is None

    def test_skills_dir_created(self, tmp_home, sample_capability_dir):
        skills_dir = Path.home() / ".claude" / "skills"
        assert not skills_dir.exists()

        adapter = ClaudeCodeAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        assert skills_dir.exists()
        assert skills_dir.is_dir()


class TestGeminiCLIAdapter:

    def test_install_capability(self, tmp_home, sample_capability_dir):
        adapter = GeminiCLIAdapter()
        result = adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert result is True
        assert adapter.capability_exists("test-cap")

    def test_remove_capability(self, tmp_home, sample_capability_dir):
        adapter = GeminiCLIAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert adapter.capability_exists("test-cap")

        result = adapter.remove_capability("test-cap")
        assert result is True
        assert not adapter.capability_exists("test-cap")

    def test_remove_nonexistent(self, tmp_home):
        adapter = GeminiCLIAdapter()
        result = adapter.remove_capability("nonexistent")
        assert result is True

    def test_capability_exists_false_for_missing(self, tmp_home):
        adapter = GeminiCLIAdapter()
        assert not adapter.capability_exists("nonexistent")

    def test_list_capabilities_empty(self, tmp_home):
        adapter = GeminiCLIAdapter()
        assert adapter.list_capabilities() == []

    def test_list_capabilities(self, tmp_home, sample_capability_dir):
        adapter = GeminiCLIAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        caps = adapter.list_capabilities()
        assert "test-cap" in caps

    def test_list_capabilities_multiple(self, tmp_home, tmp_path):
        adapter = GeminiCLIAdapter()
        cap_a = tmp_path / "cap-a"
        cap_a.mkdir()
        (cap_a / "a.txt").write_text("a")
        cap_b = tmp_path / "cap-b"
        cap_b.mkdir()
        (cap_b / "b.txt").write_text("b")

        adapter.install_capability("cap-a", "1.0.0", cap_a)
        adapter.install_capability("cap-b", "1.0.0", cap_b)

        caps = adapter.list_capabilities()
        assert "cap-a" in caps
        assert "cap-b" in caps

    def test_get_capability_metadata(self, tmp_home, sample_capability_dir):
        adapter = GeminiCLIAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        meta = adapter.get_capability_metadata("test-cap")
        assert meta is not None
        assert meta["name"] == "test-cap"
        assert meta["version"] == "1.0.0"

    def test_get_capability_metadata_nonexistent(self, tmp_home):
        adapter = GeminiCLIAdapter()
        assert adapter.get_capability_metadata("nonexistent") is None

    def test_skills_dir_created(self, tmp_home, sample_capability_dir):
        skills_dir = Path.home() / ".gemini" / "skills"
        assert not skills_dir.exists()

        adapter = GeminiCLIAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        assert skills_dir.exists()
        assert skills_dir.is_dir()


class TestOpenClawAdapter:

    def test_install_capability(self, tmp_home, sample_capability_dir):
        adapter = OpenClawAdapter()
        result = adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert result is True
        assert adapter.capability_exists("test-cap")

    def test_remove_capability(self, tmp_home, sample_capability_dir):
        adapter = OpenClawAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert adapter.capability_exists("test-cap")

        result = adapter.remove_capability("test-cap")
        assert result is True
        assert not adapter.capability_exists("test-cap")

    def test_remove_nonexistent(self, tmp_home):
        adapter = OpenClawAdapter()
        result = adapter.remove_capability("nonexistent")
        assert result is True

    def test_capability_exists_false_for_missing(self, tmp_home):
        adapter = OpenClawAdapter()
        assert not adapter.capability_exists("nonexistent")

    def test_skills_dir_created(self, tmp_home, sample_capability_dir):
        skills_dir = Path.home() / ".openclaw" / "skills"
        assert not skills_dir.exists()

        adapter = OpenClawAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        assert skills_dir.exists()
        assert skills_dir.is_dir()


class TestHermesAdapter:

    def test_install_capability(self, tmp_home, sample_capability_dir):
        adapter = HermesAdapter()
        result = adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert result is True
        assert adapter.capability_exists("test-cap")

    def test_remove_capability(self, tmp_home, sample_capability_dir):
        adapter = HermesAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert adapter.capability_exists("test-cap")

        result = adapter.remove_capability("test-cap")
        assert result is True
        assert not adapter.capability_exists("test-cap")

    def test_remove_nonexistent(self, tmp_home):
        adapter = HermesAdapter()
        result = adapter.remove_capability("nonexistent")
        assert result is True

    def test_capability_exists_false_for_missing(self, tmp_home):
        adapter = HermesAdapter()
        assert not adapter.capability_exists("nonexistent")

    def test_skills_dir_created(self, tmp_home, sample_capability_dir):
        skills_dir = Path.home() / ".hermes" / "skills"
        assert not skills_dir.exists()

        adapter = HermesAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        assert skills_dir.exists()
        assert skills_dir.is_dir()


class TestCopilotAdapter:

    def test_install_capability(self, tmp_home, sample_capability_dir):
        adapter = CopilotAdapter()
        result = adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert result is True
        assert adapter.capability_exists("test-cap")

    def test_remove_capability(self, tmp_home, sample_capability_dir):
        adapter = CopilotAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert adapter.capability_exists("test-cap")

        result = adapter.remove_capability("test-cap")
        assert result is True
        assert not adapter.capability_exists("test-cap")

    def test_remove_nonexistent(self, tmp_home):
        adapter = CopilotAdapter()
        result = adapter.remove_capability("nonexistent")
        assert result is True

    def test_capability_exists_false_for_missing(self, tmp_home):
        adapter = CopilotAdapter()
        assert not adapter.capability_exists("nonexistent")

    def test_skills_dir_created(self, tmp_home, sample_capability_dir):
        skills_dir = Path.home() / ".config" / "github-copilot" / "skills"
        assert not skills_dir.exists()

        adapter = CopilotAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)

        assert skills_dir.exists()
        assert skills_dir.is_dir()


class TestCursorAdapterSkills:

    def test_install_capability(self, tmp_home, sample_capability_dir):
        adapter = CursorAdapter()
        result = adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert result is True
        assert adapter.capability_exists("test-cap")

    def test_remove_capability(self, tmp_home, sample_capability_dir):
        adapter = CursorAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert adapter.capability_exists("test-cap")

        result = adapter.remove_capability("test-cap")
        assert result is True
        assert not adapter.capability_exists("test-cap")

    def test_remove_nonexistent(self, tmp_home):
        adapter = CursorAdapter()
        result = adapter.remove_capability("nonexistent")
        assert result is True

    def test_capability_exists_false_for_missing(self, tmp_home):
        adapter = CursorAdapter()
        assert not adapter.capability_exists("nonexistent")

    def test_skills_dir_created(self, tmp_home, sample_capability_dir):
        skills_dir = Path.cwd() / ".cursor" / "skills"
        adapter = CursorAdapter()
        adapter.install_capability("test-cap", "1.0.0", sample_capability_dir)
        assert skills_dir.exists()
        assert skills_dir.is_dir()


class TestAdapterAutoSelection:

    def test_default_to_opencode_when_no_frameworks(self):
        manifest = Manifest(name="test", frameworks=[])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, OpenCodeAdapter)

    def test_default_to_opencode_when_none_frameworks(self):
        manifest = Manifest(name="test")
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, OpenCodeAdapter)

    def test_select_claude_code(self):
        manifest = Manifest(name="test", frameworks=["claude-code"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_select_gemini_cli(self):
        manifest = Manifest(name="test", frameworks=["gemini-cli"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, GeminiCLIAdapter)

    def test_select_openclaw(self):
        manifest = Manifest(name="test", frameworks=["openclaw"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, OpenClawAdapter)

    def test_select_hermes(self):
        manifest = Manifest(name="test", frameworks=["hermes"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, HermesAdapter)

    def test_select_copilot(self):
        manifest = Manifest(name="test", frameworks=["copilot"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, CopilotAdapter)

    def test_select_first_supported_framework(self):
        manifest = Manifest(name="test", frameworks=["claude-code", "opencode"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_fallback_to_opencode_for_unknown_framework(self):
        manifest = Manifest(name="test", frameworks=["unknown-framework"])
        adapter = get_adapter_for_manifest(manifest)
        assert isinstance(adapter, OpenCodeAdapter)

    def test_register_custom_adapter(self):
        class CustomAdapter(FrameworkAdapter):
            def install_skill(self, cap_name, version, source_dir, owner="global"):
                return True
            def remove_skill(self, cap_name, owner="global"):
                return True
            def install_mcp_server(self, cap_name, version, source_dir, owner="global"):
                return False
            def remove_mcp_server(self, cap_name, owner="global"):
                return False
            def capability_exists(self, cap_name):
                return False

        register_adapter("custom", CustomAdapter)
        adapter = get_adapter("custom")
        assert isinstance(adapter, CustomAdapter)

    def test_get_unknown_adapter_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown framework adapter: nonexistent"):
            get_adapter("nonexistent")
