import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from capacium.models import Capability, Kind
from capacium.registry import Registry


def _register_cap(
    tmp_home: Path,
    *,
    owner: str,
    name: str,
    version: str,
    kind: Kind = Kind.SKILL,
    payload: bytes = b"payload",
) -> Capability:
    package_dir = tmp_home / ".capacium" / "packages" / owner / name / version
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "capability.yaml").write_text(
        f"kind: {kind.value}\nname: {name}\nversion: {version}\n"
        "description: Batch E fixture\n"
    )
    (package_dir / "payload.bin").write_bytes(payload)
    cap = Capability(
        owner=owner,
        name=name,
        version=version,
        kind=kind,
        fingerprint=f"fp-{name}-{version}",
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework="opencode",
        frameworks=["opencode"],
    )
    assert Registry().add_capability(cap)
    return cap


def _write_skill(directory: Path, frontmatter_name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {frontmatter_name}\ndescription: fixture\n---\n{body}\n"
    )


def test_deep_doctor_detects_divergent_skill_content_and_mixed_runtime(tmp_home):
    from capacium.commands.doctor import _check_content_drift

    opencode_skill = tmp_home / ".opencode" / "skills" / "shared"
    claude_skill = tmp_home / ".claude" / "skills" / "shared"
    _write_skill(opencode_skill, "shared", "content A")
    _write_skill(claude_skill, "shared", "content B")

    managed = _register_cap(
        tmp_home, owner="acme", name="runtime-skill", version="1.0.0"
    )
    (managed.install_path / "SKILL.md").write_text(
        "# Runtime\nUse ~/.understand-anything-plugin for execution.\n"
    )
    foreign = tmp_home / "foreign-understand-runtime"
    foreign.mkdir()
    runtime_link = tmp_home / ".understand-anything-plugin"
    runtime_link.symlink_to(foreign, target_is_directory=True)

    name, passed, detail = _check_content_drift()
    assert name == "Duplicate content / runtime drift"
    assert passed is False
    assert "shared" in detail
    assert str(opencode_skill) in detail
    assert str(claude_skill) in detail
    assert "mixed runtime" in detail
    assert str(runtime_link) in detail
    assert str(foreign) in detail


def test_deep_doctor_detects_referenced_runtime_without_package_version(tmp_home):
    from capacium.commands.doctor import _check_runtime_package_mismatch

    _register_cap(
        tmp_home,
        owner="MemPalace",
        name="mempalace",
        version="3.3.2",
        kind=Kind.MCP_SERVER,
    )
    _register_cap(
        tmp_home,
        owner="MemPalace",
        name="mempalace",
        version="3.3.4",
        kind=Kind.MCP_SERVER,
    )
    config = tmp_home / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "mempalace": {
                        "command": str(
                            tmp_home
                            / ".capacium"
                            / "runtimes"
                            / "mempalace-3.3.3"
                            / "bin"
                        )
                    }
                }
            }
        )
    )

    name, passed, detail = _check_runtime_package_mismatch()
    assert name == "Runtime/package versions"
    assert passed is False
    assert "mempalace" in detail
    assert "3.3.3" in detail
    assert "3.3.2" in detail
    assert "3.3.4" in detail


def test_deep_doctor_reports_store_size_top_packages_and_prunable_count(tmp_home):
    from capacium.commands.doctor import _check_store_health

    _register_cap(
        tmp_home, owner="acme", name="large", version="1.0.0", payload=b"a" * 20
    )
    _register_cap(
        tmp_home, owner="acme", name="large", version="2.0.0", payload=b"b" * 30
    )
    _register_cap(
        tmp_home, owner="acme", name="large", version="3.0.0", payload=b"c" * 40
    )

    name, passed, detail = _check_store_health(top_n=2)
    assert name == "Package store"
    assert passed is True
    assert "total" in detail
    assert "top" in detail
    assert "acme/large@3.0.0" in detail
    assert "2 prunable" in detail
    assert "cap gc" in detail


def test_repair_removes_only_stale_bundle_root_link(tmp_home, capsys):
    from capacium.commands.repair import repair

    bundle = tmp_home / ".capacium" / "packages" / "acme" / "toolkit" / "1.0.0"
    member = bundle / "skills" / "member"
    member.mkdir(parents=True)
    (bundle / "capability.yaml").write_text(
        "kind: bundle\nname: toolkit\nversion: 1.0.0\ndescription: fixture\n"
        "capabilities:\n- name: member\n  source: ./skills/member\n"
    )
    (member / "capability.yaml").write_text(
        "kind: skill\nname: member\nversion: 1.0.0\ndescription: member\n"
    )
    (member / "SKILL.md").write_text("# Member\n")
    skills = tmp_home / ".opencode" / "skills"
    skills.mkdir(parents=True)
    root_link = skills / "toolkit"
    member_link = skills / "member"
    root_link.symlink_to(bundle, target_is_directory=True)
    member_link.symlink_to(member, target_is_directory=True)

    args = SimpleNamespace(capability=None, dry_run=True, yes=False, json=False)
    assert repair(args)
    assert root_link.is_symlink()
    assert member_link.is_symlink()
    assert "stale bundle root" in capsys.readouterr().out

    args.dry_run = False
    args.yes = True
    assert repair(args)
    assert not root_link.exists()
    assert not root_link.is_symlink()
    assert member_link.is_symlink()


def test_manifest_relocation_records_alias_and_keeps_one_canonical_row(
    tmp_home, tmp_path, capsys
):
    from capacium.commands.install import install_capability
    from capacium.commands.list_capabilities import list_capabilities

    _register_cap(
        tmp_home, owner="oldco", name="widget", version="1.0.0"
    )
    source = tmp_path / "widget"
    source.mkdir()
    (source / "capability.yaml").write_text(
        "kind: skill\nname: widget\nowner: newco\nversion: 1.0.0\n"
        "description: relocated fixture\nmoved_to: newco/widget\n"
        "replaces:\n- oldco/widget\nframeworks:\n- opencode\n"
    )
    (source / "SKILL.md").write_text("# Widget\n")

    assert install_capability(
        "oldco/widget@1.0.0",
        source_dir=source,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
    )

    registry = Registry()
    assert registry.get_capability("oldco/widget", "1.0.0") is None
    canonical = registry.get_capability("newco/widget", "1.0.0")
    assert canonical is not None
    assert canonical.install_path == (
        tmp_home / ".capacium" / "packages" / "newco" / "widget" / "1.0.0"
    )
    assert registry.get_relocation("oldco/widget") == "newco/widget"
    rows = [
        cap
        for cap in registry.list_capabilities()
        if cap.name == "widget" and cap.version == "1.0.0"
    ]
    assert len(rows) == 1

    list_capabilities()
    output = capsys.readouterr().out
    assert "oldco/widget → newco/widget" in output


def test_repository_identity_detects_redirected_canonical_owner():
    from capacium.commands.install import _canonical_identity
    from capacium.manifest import Manifest

    manifest = Manifest(
        kind="skill",
        name="widget",
        repository="https://github.com/newco/widget.git",
    )
    assert (
        _canonical_identity(manifest, "oldco/widget", manifest.repository)
        == "newco/widget"
    )


def test_manifest_relocation_rejects_unsafe_canonical_identity(capsys):
    from capacium.commands.install import _canonical_identity
    from capacium.manifest import Manifest

    manifest = Manifest(
        kind="skill",
        name="widget",
        moved_to="../../outside-store",
    )

    assert _canonical_identity(manifest, "oldco/widget", None) == "oldco/widget"
    assert "unsafe canonical identity" in capsys.readouterr().out


def test_bundle_install_warns_deterministically_on_duplicate_frontmatter_names(
    tmp_home, tmp_path, capsys
):
    from capacium.commands.install import install_capability

    bundle = tmp_path / "bundle"
    for member_name in ("alpha", "beta"):
        member = bundle / "skills" / member_name
        member.mkdir(parents=True)
        (member / "capability.yaml").write_text(
            f"kind: skill\nname: {member_name}\nversion: 1.0.0\n"
            f"description: {member_name}\nframeworks:\n- opencode\n"
        )
        _write_skill(member, "launch", member_name)
    (bundle / "capability.yaml").write_text(
        "kind: bundle\nname: toolkit\nversion: 1.0.0\ndescription: fixture\n"
        "frameworks:\n- opencode\ncapabilities:\n"
        "- name: alpha\n  source: ./skills/alpha\n  version: 1.0.0\n"
        "- name: beta\n  source: ./skills/beta\n  version: 1.0.0\n"
    )

    assert install_capability(
        "acme/toolkit@1.0.0",
        source_dir=bundle,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
    )
    output = capsys.readouterr().out
    assert (
        "Warning: bundle frontmatter name 'launch' is shared by: alpha, beta"
        in output
    )


def test_distinct_bundle_frontmatter_names_are_warning_free(tmp_path, capsys):
    from capacium.commands.install import _warn_bundle_frontmatter_collisions
    from capacium.manifest import Manifest

    bundle = tmp_path / "distinct-bundle"
    entries = []
    for name in ("alpha", "beta"):
        member = bundle / "skills" / name
        _write_skill(member, name, name)
        entries.append(
            {"name": name, "source": f"./skills/{name}", "version": "1.0.0"}
        )
    manifest = Manifest(
        kind="bundle",
        name="distinct-bundle",
        capabilities=entries,
    )

    _warn_bundle_frontmatter_collisions(manifest, bundle)
    assert capsys.readouterr().out == ""
