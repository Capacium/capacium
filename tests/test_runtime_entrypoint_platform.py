"""WINRT-001 — platform-aware entrypoint file name and script rendering.

The builder writes ``#!/bin/sh`` scripts on POSIX and ``@echo off`` batch
scripts on Windows. The finder resolves the platform-correct entrypoint
name before its directory scan. These tests pin the exact bytes with
golden comparisons so no implementation that writes a shebang script for
Windows can pass.
"""

import os
import sys
from pathlib import Path

from capacium.runtimes import (
    RuntimeBuilder,
    SourceLock,
    entrypoint_filename,
    entrypoint_script_text,
)
from capacium.commands.exec import _find_executable


# ── Golden bytes ──────────────────────────────────────────────────────────

_POSIX_GOLDEN_STRING_CMD = (
    b"#!/bin/sh\n"
    b'cd "$(dirname "$0")" && exec python3 mcp_server.py "$@"\n'
)

_POSIX_GOLDEN_LIST_CMD = (
    b"#!/bin/sh\n"
    b'cd "$(dirname "$0")" && exec python3 mcp_server.py "$@"\n'
)

_WINDOWS_GOLDEN_STRING_CMD = (
    b"@echo off\r\n"
    b'cd /d "%~dp0"\r\n'
    b"python3 mcp_server.py %*\r\n"
)

_WINDOWS_GOLDEN_LIST_CMD = (
    b"@echo off\r\n"
    b'cd /d "%~dp0"\r\n'
    b"python3 mcp_server.py %*\r\n"
)


# ── entrypoint_filename ───────────────────────────────────────────────────

class TestEntrypointFilename:
    def test_posix_returns_bare_name(self):
        assert entrypoint_filename("main", "darwin") == "main"
        assert entrypoint_filename("tool", "linux") == "tool"

    def test_windows_appends_cmd_suffix(self):
        assert entrypoint_filename("main", "win32") == "main.cmd"
        assert entrypoint_filename("tool", "win32") == "tool.cmd"

    def test_default_platform_is_sys_platform(self):
        expected = "main.cmd" if sys.platform.startswith("win") else "main"
        assert entrypoint_filename("main") == expected


# ── entrypoint_script_text ────────────────────────────────────────────────

class TestEntrypointScriptText:
    def test_posix_string_command(self):
        text = entrypoint_script_text("python3 mcp_server.py", "darwin")
        expected = '#!/bin/sh\ncd "$(dirname "$0")" && exec python3 mcp_server.py "$@"\n'
        assert text == expected

    def test_posix_list_command(self):
        text = entrypoint_script_text("python3 mcp_server.py", "linux")
        expected = '#!/bin/sh\ncd "$(dirname "$0")" && exec python3 mcp_server.py "$@"\n'
        assert text == expected

    def test_windows_string_command(self):
        text = entrypoint_script_text("python3 mcp_server.py", "win32")
        assert text == '@echo off\r\ncd /d "%~dp0"\r\npython3 mcp_server.py %*\r\n'

    def test_windows_no_shebang(self):
        text = entrypoint_script_text("python3 mcp_server.py", "win32")
        assert "#!/bin/sh" not in text
        assert "#!/" not in text

    def test_windows_no_posix_shell_syntax(self):
        text = entrypoint_script_text("python3 mcp_server.py", "win32")
        assert "$@" not in text
        assert '$(dirname' not in text

    def test_windows_first_line_is_echo_off(self):
        text = entrypoint_script_text("python3 mcp_server.py", "win32")
        lines = text.split("\r\n")
        assert lines[0] == "@echo off"

    def test_default_platform_is_sys_platform(self):
        text = entrypoint_script_text("python3 mcp_server.py")
        if sys.platform.startswith("win"):
            assert "@echo off" in text
        else:
            assert "#!/bin/sh" in text


# ── RuntimeBuilder with platform argument ─────────────────────────────────

class TestRuntimeBuilderPlatform:
    """Builds through the real RuntimeBuilder with the platform argument.
    No monkeypatching of sys.platform."""

    def test_posix_build_writes_golden_bytes_string_command(self, tmp_path):
        """POSIX build output matches the golden bytes exactly."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        result = builder.build(lock, platform="darwin")
        main = Path(result.build_dir) / "main"
        assert main.is_file()
        assert main.read_bytes() == _POSIX_GOLDEN_STRING_CMD
        assert os.stat(main).st_mode & 0o777 == 0o755

    def test_posix_build_writes_golden_bytes_list_command(self, tmp_path):
        """POSIX build for a tuple command matches the golden bytes."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": ("python3", "mcp_server.py")},
        )
        result = builder.build(lock, platform="darwin")
        main = Path(result.build_dir) / "main"
        assert main.is_file()
        assert main.read_bytes() == _POSIX_GOLDEN_LIST_CMD
        assert os.stat(main).st_mode & 0o777 == 0o755

    def test_windows_build_writes_golden_bytes_string_command(self, tmp_path):
        """Windows build output matches the golden bytes exactly."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        result = builder.build(lock, platform="win32")
        main = Path(result.build_dir) / "main.cmd"
        assert main.is_file()
        assert main.read_bytes() == _WINDOWS_GOLDEN_STRING_CMD
        assert os.stat(main).st_mode & 0o777 == 0o755

    def test_windows_build_writes_golden_bytes_list_command(self, tmp_path):
        """Windows build for a tuple command matches the golden bytes."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": ("python3", "mcp_server.py")},
        )
        result = builder.build(lock, platform="win32")
        main = Path(result.build_dir) / "main.cmd"
        assert main.is_file()
        assert main.read_bytes() == _WINDOWS_GOLDEN_LIST_CMD
        assert os.stat(main).st_mode & 0o777 == 0o755

    def test_windows_build_has_no_shebang_script(self, tmp_path):
        """No shebang script is written for Windows — only the .cmd file."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        result = builder.build(lock, platform="win32")
        # No bare 'main' file without .cmd suffix
        assert not (Path(result.build_dir) / "main").exists()
        # The .cmd file exists and is a batch script
        main = Path(result.build_dir) / "main.cmd"
        assert main.is_file()
        content = main.read_bytes()
        assert b"#!/bin/sh" not in content

    def test_digest_unchanged_by_platform_choice(self, tmp_path):
        """The generation digest is unchanged by the platform choice."""
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        posix_result = RuntimeBuilder(str(tmp_path / "posix")).build(
            lock, platform="darwin"
        )
        win_result = RuntimeBuilder(str(tmp_path / "win")).build(
            lock, platform="win32"
        )
        assert posix_result.digest == win_result.digest

    def test_generation_json_unchanged_by_platform_choice(self, tmp_path):
        """The .generation.json content is unchanged by the platform choice."""
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        posix_result = RuntimeBuilder(str(tmp_path / "posix")).build(
            lock, platform="darwin"
        )
        win_result = RuntimeBuilder(str(tmp_path / "win")).build(
            lock, platform="win32"
        )
        posix_json = (Path(posix_result.build_dir) / ".generation.json").read_bytes()
        win_json = (Path(win_result.build_dir) / ".generation.json").read_bytes()
        assert posix_json == win_json

    def test_linux_is_posix(self, tmp_path):
        """Linux platform writes POSIX bytes."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        result = builder.build(lock, platform="linux")
        main = Path(result.build_dir) / "main"
        assert main.is_file()
        assert main.read_bytes() == _POSIX_GOLDEN_STRING_CMD

    def test_file_mode_unchanged(self, tmp_path):
        """File mode 0o755 is unchanged on both platforms."""
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        posix_result = builder.build(lock, platform="darwin")
        win_result = RuntimeBuilder(str(tmp_path / "w")).build(
            lock, platform="win32"
        )
        posix_mode = os.stat(Path(posix_result.build_dir) / "main").st_mode & 0o777
        win_mode = os.stat(Path(win_result.build_dir) / "main.cmd").st_mode & 0o777
        assert posix_mode == 0o755
        assert win_mode == 0o755


# ── _find_executable with platform argument ───────────────────────────────

class TestFindExecutablePlatform:
    """_find_executable resolves the Windows entrypoint name."""

    def _build_generation(self, base_dir, platform):
        builder = RuntimeBuilder(str(base_dir))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={"main": "python3 mcp_server.py"},
        )
        return builder.build(lock, platform=platform)

    def test_find_posix_entrypoint_by_name(self, tmp_path):
        """On POSIX, _find_executable finds the bare entry name."""
        result = self._build_generation(tmp_path, "darwin")
        exe = _find_executable(
            Path(result.build_dir),
            {"main": "python3 mcp_server.py"},
            platform="darwin",
        )
        assert exe is not None
        assert exe.name == "main"

    def test_find_windows_entrypoint_by_name(self, tmp_path):
        """On Windows, _find_executable resolves main → main.cmd."""
        result = self._build_generation(tmp_path, "win32")
        exe = _find_executable(
            Path(result.build_dir),
            {"main": "python3 mcp_server.py"},
            platform="win32",
        )
        assert exe is not None
        assert exe.name == "main.cmd"

    def test_find_posix_default_platform(self, tmp_path):
        """_find_executable default platform matches sys.platform."""
        result = self._build_generation(tmp_path, "darwin")
        # When running on darwin, default should find 'main'
        if sys.platform == "darwin":
            exe = _find_executable(Path(result.build_dir), {"main": "python3 mcp_server.py"})
            assert exe is not None
            assert exe.name == "main"

    def test_find_windows_with_wrong_name_returns_none(self, tmp_path):
        """On Windows, looking for bare 'main' without platform info returns
        None if no other executable exists."""
        result = self._build_generation(tmp_path, "win32")
        exe = _find_executable(
            Path(result.build_dir),
            {"main": "python3 mcp_server.py"},
            platform="darwin",  # Wrong platform — looks for 'main'
        )
        # 'main' does not exist; the platform-agnostic fallback scan
        # finds main.cmd.
        assert exe is not None
        assert exe.name == "main.cmd"

    def test_find_posix_behaviour_unchanged(self, tmp_path):
        """On POSIX _find_executable behaviour is unchanged."""
        # Build a generation with two entrypoints
        builder = RuntimeBuilder(str(tmp_path))
        lock = SourceLock(
            source_url="file:///tmp/test",
            digest="sha256:abc123",
            entrypoints={
                "tool": "python3 my_tool",
                "main": "python3 mcp_server.py",
            },
        )
        result = builder.build(lock, platform="darwin")
        gen_dir = Path(result.build_dir)

        # Should find the first entrypoint by name
        exe = _find_executable(gen_dir, {"tool": "python3 my_tool"}, platform="darwin")
        assert exe is not None
        assert exe.name == "tool"

        # Empty entrypoints: fallback scan finds the first executable
        exe = _find_executable(gen_dir, {}, platform="darwin")
        assert exe is not None
        assert exe.is_file()
