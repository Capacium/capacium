import json
import subprocess
from pathlib import Path


def test_update_reconciles_unique_unqualified_mcp_name(tmp_home, tmp_path):
    source = tmp_path / "mempalace"
    source.mkdir()
    (source / "capability.yaml").write_text(
        "kind: mcp-server\n"
        "name: mempalace\n"
        "version: 1.0.0\n"
        "frameworks: [opencode]\n"
        "mcp:\n"
        "  transport: stdio\n"
        "  command: uvx\n"
        "  args: [mempalace-mcp]\n"
    )

    from capacium.commands.install import install_capability
    assert install_capability(
        "MemPalace/mempalace",
        source_dir=source,
        no_lock=True,
        skip_runtime_check=True,
    ) is True

    config_path = tmp_home / ".config" / "opencode" / "opencode.json"
    config_path.write_text(json.dumps({}))

    from capacium.commands.update import update_capability
    assert update_capability("mempalace", skip_runtime_check=True) is True

    data = json.loads(config_path.read_text())
    assert data["mcp"]["mempalace"] == {
        "type": "local",
        "command": ["uvx", "mempalace-mcp"],
        "enabled": True,
    }


def test_update_reports_ambiguous_unqualified_name(tmp_home, tmp_path, capsys):
    from capacium.registry import Registry
    from capacium.models import Capability, Kind
    from datetime import datetime

    registry = Registry()
    for owner in ("alice", "bob"):
        registry.add_capability(Capability(
            owner=owner,
            name="shared",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="fp",
            install_path=tmp_path,
            installed_at=datetime.now(),
            framework="opencode",
        ))

    from capacium.commands.update import update_capability
    assert update_capability("shared", skip_runtime_check=True) is False

    out = capsys.readouterr().out
    assert "ambiguous" in out
    assert "alice/shared" in out
    assert "bob/shared" in out


def test_parse_version_orders_correctly():
    from capacium.commands.update import _parse_version
    assert _parse_version("1.0.0") < _parse_version("2.0.0")
    assert _parse_version("0.5.1") < _parse_version("0.5.6")
    assert _parse_version("0.9.9") < _parse_version("1.0.0")
    assert _parse_version("0.5.6") > _parse_version("0.5.1")
    assert _parse_version("1.0.0") == _parse_version("1.0.0")


def test_fetch_git_tags_finds_newer_tags(tmp_path):
    source = tmp_path / "test-cap"
    source.mkdir()
    (source / "capability.yaml").write_text("kind: skill\nname: test-cap\nversion: 1.0.0\n")
    subprocess.run(["git", "init"], cwd=source, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=source, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=source, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=source, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=source, capture_output=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=source, capture_output=True)
    subprocess.run(["git", "tag", "v2.0.0"], cwd=source, capture_output=True)

    from capacium.commands.update import _fetch_git_tags
    tags = _fetch_git_tags(source)
    assert "1.0.0" in tags
    assert "2.0.0" in tags


def test_fetch_git_tags_no_git_dir(tmp_path):
    source = tmp_path / "no-git"
    source.mkdir()
    from capacium.commands.update import _fetch_git_tags
    assert _fetch_git_tags(source) == []
