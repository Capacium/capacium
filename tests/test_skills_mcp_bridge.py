"""BRIDGE-001: Claude Desktop skills bridge test suite.

Tests for the Capacium skills MCP bridge: discovery, tool list generation,
tool call handling, and cap executable resolution order.
"""

import json
from pathlib import Path


from capacium.skills_mcp_wrapper import (
    _build_tools_list,
    _discover_skills,
    _handle_call,
    _tool_name,
)


def _write_skill(path, *, name, version, kind="skill", description=None):
    """Create a minimal skill with capability.yaml and SKILL.md."""
    path.mkdir(parents=True)
    desc = description or f"{name} {version}"
    (path / "capability.yaml").write_text(
        f"kind: {kind}\nname: {name}\nversion: {version}\ndescription: {desc}\n"
    )
    (path / "SKILL.md").write_text(f"---\ndescription: {desc}\n---\n# {name}\n")


def _write_skill_no_skill_md(path, *, name, version, kind="skill"):
    """Create a minimal skill with capability.yaml only (no SKILL.md)."""
    path.mkdir(parents=True)
    (path / "capability.yaml").write_text(
        f"kind: {kind}\nname: {name}\nversion: {version}\ndescription: {name} desc\n"
    )


# =============================================================================
# TestSkillsMcpWrapper
# =============================================================================


class TestSkillsMcpWrapper:

    def test_discovers_versioned_layout(self, tmp_path, monkeypatch):
        """Bridge discovers skills in versioned layout (owner/name/version/)."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "LangeVC" / "skillweave-blueprint" / "1.1.0",
            name="skillweave-blueprint",
            version="1.1.0",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 1
        assert skills[0]["name"] == "skillweave-blueprint"
        assert skills[0]["version"] == "1.1.0"
        assert skills[0]["owner"] == "LangeVC"
        assert "skillweave-blueprint" in skills[0]["path"]

    def test_discovers_legacy_layout(self, tmp_path, monkeypatch):
        """Bridge discovers skills in legacy layout (owner/name/)."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "legacy-owner" / "legacy-skill",
            name="legacy-skill",
            version="0.5.0",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 1
        assert skills[0]["name"] == "legacy-skill"
        assert skills[0]["version"] == "0.5.0"
        assert skills[0]["owner"] == "legacy-owner"

    def test_skill_filter_filters_by_kind(self, tmp_path, monkeypatch):
        """Only kind:skill capabilities are exposed; mcp-server excluded."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "Owner" / "my-skill" / "1.0.0",
            name="my-skill",
            version="1.0.0",
            kind="skill",
        )
        _write_skill(
            cap_home / "Owner" / "my-server" / "2.0.0",
            name="my-server",
            version="2.0.0",
            kind="mcp-server",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 1
        assert skills[0]["name"] == "my-skill"
        assert skills[0]["kind"] == "skill"

    def test_latest_semver_selection(self, tmp_path):
        """When multiple versions exist, latest semver is selected."""
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "Owner" / "example" / "1.9.0",
            name="example",
            version="1.9.0",
        )
        _write_skill(
            cap_home / "Owner" / "example" / "1.10.0",
            name="example",
            version="1.10.0",
        )
        _write_skill(
            cap_home / "Owner" / "example" / "0.1.0",
            name="example",
            version="0.1.0",
        )
        _write_skill(
            cap_home / "Owner" / "example" / "1.10.0-alpha",
            name="example",
            version="1.10.0-alpha",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 1
        # SemVer: the 1.10.0 release outranks its alpha prerelease
        assert skills[0]["version"] == "1.10.0"

    def test_refresh_on_install(self, tmp_path, monkeypatch):
        """Bridge refreshes skill list after install."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "Owner" / "skill-a" / "1.0.0",
            name="skill-a",
            version="1.0.0",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 1
        assert skills[0]["name"] == "skill-a"

        _write_skill(
            cap_home / "Owner" / "skill-b" / "2.0.0",
            name="skill-b",
            version="2.0.0",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert names == {"skill-a", "skill-b"}

    def test_stale_tools_removed_on_update(self, tmp_path, monkeypatch):
        """Removed skills don't leave stale tools in bridge."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "Owner" / "skill-a" / "1.0.0",
            name="skill-a",
            version="1.0.0",
        )
        _write_skill(
            cap_home / "Owner" / "skill-b" / "1.0.0",
            name="skill-b",
            version="1.0.0",
        )
        skills = _discover_skills(cap_home)
        assert len(skills) == 2

        import shutil

        shutil.rmtree(cap_home / "Owner" / "skill-b")
        skills = _discover_skills(cap_home)
        assert len(skills) == 1
        assert skills[0]["name"] == "skill-a"


# =============================================================================
# TestBridgeToolList
# =============================================================================


class TestBridgeToolList:

    def test_returns_expected_tool_count(self, tmp_path, monkeypatch):
        """tools/list returns correct count for installed skills."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "Owner" / "skill-a" / "1.0.0",
            name="skill-a",
            version="1.0.0",
        )
        _write_skill(
            cap_home / "Owner" / "skill-b" / "1.0.0",
            name="skill-b",
            version="1.0.0",
        )
        skills = _discover_skills(cap_home)
        tools = _build_tools_list(skills)
        assert len(tools) == 3  # list_skills + 2 skill tools

    def test_tool_names_match_skill_names(self, tmp_path, monkeypatch):
        """Each tool name matches its skill name (kebab-case)."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "Owner" / "my-test-skill" / "1.0.0",
            name="my-test-skill",
            version="1.0.0",
        )
        skills = _discover_skills(cap_home)
        tools = _build_tools_list(skills)
        tool_names = [t["name"] for t in tools]
        assert "list_skills" in tool_names
        assert "skill_my_test_skill" in tool_names

    def test_tool_descriptions_include_skill_metadata(self, tmp_path):
        """Tool descriptions include version and owner info."""
        cap_home = tmp_path / "packages"
        _write_skill(
            cap_home / "LangeVC" / "test-skill" / "2.3.1",
            name="test-skill",
            version="2.3.1",
            description="A test capability",
        )
        skills = _discover_skills(cap_home)
        tools = _build_tools_list(skills)
        skill_tool = [t for t in tools if t["name"] == "skill_test_skill"][0]
        assert skill_tool["description"] == "A test capability"

    def test_empty_tools_when_no_skills(self, tmp_path, monkeypatch):
        """tools/list returns array with only list_skills when no skills installed."""
        monkeypatch.setattr("capacium.skills_mcp_wrapper.Path.home", lambda: Path("/fake/home"))
        cap_home = tmp_path / "packages"
        cap_home.mkdir(parents=True)
        skills = _discover_skills(cap_home)
        tools = _build_tools_list(skills)
        assert len(tools) == 1
        assert tools[0]["name"] == "list_skills"


# =============================================================================
# TestBridgeResolutionOrder
# =============================================================================


class TestBridgeResolutionOrder:

    def test_uses_adjacent_interpreter_first(self, tmp_path, monkeypatch):
        """Bridge prefers cap adjacent to current Python interpreter."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        adapter = ClaudeDesktopAdapter()
        adapter.config_path = tmp_path / "claude_desktop_config.json"
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text("{}")

        monkeypatch.setattr(
            "capacium.adapters.claude_desktop.shutil.which",
            lambda _: None,
        )

        fake_python = tmp_path / "bin" / "python3"
        fake_python.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            "capacium.adapters.claude_desktop.sys.executable",
            str(fake_python),
        )

        fake_cap = fake_python.with_name("cap")
        fake_cap.touch(mode=0o755)

        monkeypatch.setattr(
            "capacium.adapters.claude_desktop._path_in_sandbox_denied",
            lambda _: False,
        )

        adapter._ensure_skills_mcp_registered()

        entry = json.loads(adapter.config_path.read_text())["mcpServers"]["capacium-skills"]
        assert entry["command"] == str(fake_cap)
        assert entry["args"][:2] == ["skills-mcp", "start"]

    def test_falls_back_to_path_cap(self, tmp_path, monkeypatch):
        """When adjacent cap not found, falls back to PATH cap."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        adapter = ClaudeDesktopAdapter()
        adapter.config_path = tmp_path / "claude_desktop_config.json"
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text("{}")

        path_cap = tmp_path / "bin" / "cap"
        path_cap.parent.mkdir(parents=True, exist_ok=True)
        path_cap.touch(mode=0o755)

        monkeypatch.setattr(
            "capacium.adapters.claude_desktop.shutil.which",
            lambda _: str(path_cap),
        )

        adapter._ensure_skills_mcp_registered()

        entry = json.loads(adapter.config_path.read_text())["mcpServers"]["capacium-skills"]
        assert entry["command"] == str(path_cap)
        assert entry["args"][:2] == ["skills-mcp", "start"]

    def test_never_uses_documents_cap(self, tmp_path, monkeypatch):
        """Bridge rejects cap executables under ~/Documents."""
        from capacium.adapters.claude_desktop import ClaudeDesktopAdapter

        adapter = ClaudeDesktopAdapter()
        adapter.config_path = tmp_path / "claude_desktop_config.json"
        adapter.config_path.parent.mkdir(parents=True, exist_ok=True)
        adapter.config_path.write_text("{}")

        documents_cap = tmp_path / "Documents" / "cap"
        documents_cap.parent.mkdir(parents=True, exist_ok=True)
        documents_cap.touch(mode=0o755)

        monkeypatch.setattr(
            "capacium.adapters.claude_desktop.shutil.which",
            lambda _: None,
        )
        monkeypatch.setattr(
            "capacium.adapters.claude_desktop.sys.executable",
            str(documents_cap.with_name("python3")),
        )
        monkeypatch.setattr(
            "capacium.adapters.claude_desktop._path_in_sandbox_denied",
            lambda p: str(p).startswith(str(tmp_path / "Documents")),
        )

        adapter._ensure_skills_mcp_registered()

        entry = json.loads(adapter.config_path.read_text())["mcpServers"]["capacium-skills"]
        assert entry["command"] != str(documents_cap)


# =============================================================================
# TestHandleCall
# =============================================================================


class TestHandleCall:

    def test_list_skills_returns_summary(self):
        skill_map = {
            "skill_test": {
                "name": "test",
                "owner": "owner",
                "version": "1.0.0",
                "description": "A test skill",
            },
        }
        result = _handle_call(skill_map, "list_skills", {})
        assert "owner/test v1.0.0" in result
        assert "A test skill" in result

    def test_list_skills_returns_empty_message(self):
        result = _handle_call({}, "list_skills", {})
        assert "No skills" in result

    def test_unknown_tool_returns_helpful_error(self):
        result = _handle_call({}, "skill_nonexistent", {})
        assert "Unknown skill tool" in result
        assert "list_skills" in result

    def test_tool_call_returns_skill_md_content(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# Hello World\n\nSkill content here.")
        skill_map = {
            "skill_test": {
                "name": "test",
                "owner": "owner",
                "version": "1.0.0",
                "description": "Test skill",
                "skill_md": str(skill_md),
            },
        }
        result = _handle_call(skill_map, "skill_test", {"query": "usage"})
        assert "Hello World" in result

    def test_tool_call_falls_back_to_description_when_no_skill_md(self):
        skill_map = {
            "skill_test": {
                "name": "test",
                "owner": "owner",
                "version": "1.0.0",
                "description": "Fallback description",
                "skill_md": None,
            },
        }
        result = _handle_call(skill_map, "skill_test", {})
        assert "owner/test v1.0.0" in result
        assert "Fallback description" in result


# =============================================================================
# TestToolName
# =============================================================================


class TestToolName:

    def test_kebab_case_skill_name(self):
        result = _tool_name({"name": "my-skill-name"})
        assert result == "skill_my_skill_name"

    def test_camel_case_skill_name(self):
        result = _tool_name({"name": "mySkillName"})
        assert result == "skill_mySkillName"

    def test_skill_with_dots(self):
        result = _tool_name({"name": "v1.2.3"})
        assert result == "skill_v1_2_3"

    def test_skill_with_special_chars(self):
        result = _tool_name({"name": "skill@weird#name"})
        assert result == "skill_skill_weird_name"


class TestSkillsMcpStartNoExecLoop:
    """V1 regression (2026-06-11): `cap skills-mcp start` must never re-exec.

    The previous implementation resolved `shutil.which("cap")` and exec'd
    `cap skills-mcp start` again, restarting itself forever on installations
    without a `capacium-skills-mcp` binary. The server must run in-process.
    """

    def test_start_runs_wrapper_in_process(self, tmp_path, monkeypatch):
        import os
        import sys
        from capacium.commands import skills_mcp

        calls = []
        monkeypatch.setattr(
            "capacium.skills_mcp_wrapper.main", lambda: calls.append(sys.argv[:])
        )

        def _forbidden(*args, **kwargs):
            raise AssertionError("process re-exec/spawn is the V1 loop regression")

        monkeypatch.setattr(os, "execv", _forbidden)
        monkeypatch.setattr("subprocess.Popen", _forbidden)

        skills_mcp.skills_mcp_start(cap_home=tmp_path)

        assert len(calls) == 1
        assert calls[0][1:] == ["--cap-home", str(tmp_path)]

    def test_start_prints_banner_exactly_once(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("capacium.skills_mcp_wrapper.main", lambda: None)
        from capacium.commands import skills_mcp

        skills_mcp.skills_mcp_start(cap_home=tmp_path)

        err = capsys.readouterr().err
        assert err.count("Starting") == 1
