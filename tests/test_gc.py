import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from capacium.models import Capability, Kind
from capacium.registry import Registry


def _add_capability(
    tmp_home: Path,
    registry: Registry,
    version: str,
    *,
    owner: str = "acme",
    name: str = "widget",
    payload: bytes = b"payload",
    kind: Kind = Kind.SKILL,
) -> Capability:
    package_dir = tmp_home / ".capacium" / "packages" / owner / name / version
    package_dir.mkdir(parents=True)
    (package_dir / "capability.yaml").write_text(
        f"kind: skill\nname: {name}\nversion: {version}\ndescription: fixture\n"
    )
    (package_dir / "payload.bin").write_bytes(payload)
    cap = Capability(
        owner=owner,
        name=name,
        version=version,
        kind=kind,
        fingerprint=f"fp-{version}",
        install_path=package_dir,
        installed_at=datetime.now(),
        dependencies=[],
        framework="opencode",
        frameworks=["opencode"],
    )
    assert registry.add_capability(cap)
    return cap


def test_gc_dry_run_and_apply_preserve_latest_held_and_linked_versions(
    tmp_home, capsys
):
    from capacium.commands.gc import garbage_collect

    registry = Registry()
    prunable = _add_capability(tmp_home, registry, "0.5.0", payload=b"old-bytes")
    linked = _add_capability(tmp_home, registry, "1.0.0")
    held = _add_capability(tmp_home, registry, "2.0.0")
    latest = _add_capability(tmp_home, registry, "3.0.0")

    skills_dir = tmp_home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "widget").symlink_to(linked.install_path, target_is_directory=True)
    holds_path = tmp_home / ".capacium" / "holds.json"
    holds_path.write_text(
        json.dumps({"acme/widget": {"version": held.version, "reason": "patched"}})
    )

    dry_run = garbage_collect(keep=1, dry_run=True)
    assert [entry.ref for entry in dry_run.entries] == ["acme/widget@0.5.0"]
    assert dry_run.reclaimed_bytes >= len(b"old-bytes")
    assert dry_run.removed == []
    assert prunable.install_path.exists()
    assert registry.get_capability("acme/widget", "0.5.0") is not None
    assert "Dry run" in capsys.readouterr().out

    applied = garbage_collect(keep=1, dry_run=False)
    assert applied.removed == ["acme/widget@0.5.0"]
    assert not prunable.install_path.exists()
    assert registry.get_capability("acme/widget", "0.5.0") is None
    for protected in (linked, held, latest):
        assert protected.install_path.exists()
        assert registry.get_capability(
            f"{protected.owner}/{protected.name}", protected.version
        ) is not None


def test_gc_uses_configured_keep_versions_when_flag_is_omitted(tmp_home):
    from capacium.commands.gc import garbage_collect
    from capacium.utils.config import save_config

    registry = Registry()
    old = _add_capability(tmp_home, registry, "1.0.0")
    middle = _add_capability(tmp_home, registry, "2.0.0")
    latest = _add_capability(tmp_home, registry, "3.0.0")
    save_config({"keep_versions": 2})

    report = garbage_collect(keep=None, dry_run=False)
    assert report.removed == ["acme/widget@1.0.0"]
    assert not old.install_path.exists()
    assert middle.install_path.exists()
    assert latest.install_path.exists()


def test_gc_preserves_configured_pins_and_members_of_retained_bundles(tmp_home):
    from capacium.commands.gc import garbage_collect
    from capacium.utils.config import save_config

    registry = Registry()
    pinned = _add_capability(tmp_home, registry, "1.0.0", name="pinned")
    _add_capability(tmp_home, registry, "2.0.0", name="pinned")

    _add_capability(tmp_home, registry, "1.0.0", name="member")
    _add_capability(tmp_home, registry, "2.0.0", name="member")
    old_bundle = _add_capability(
        tmp_home,
        registry,
        "1.0.0",
        name="bundle",
        kind=Kind.BUNDLE,
    )
    _add_capability(
        tmp_home,
        registry,
        "2.0.0",
        name="bundle",
        kind=Kind.BUNDLE,
    )
    registry.add_bundle_member(
        "acme/bundle@1.0.0", "acme/member@1.0.0"
    )
    holds_path = tmp_home / ".capacium" / "holds.json"
    holds_path.write_text(
        json.dumps({"acme/bundle": {"version": old_bundle.version}})
    )
    save_config({"pinned_versions": {"acme/pinned": [pinned.version]}})

    report = garbage_collect(keep=1, dry_run=True)
    refs = {entry.ref for entry in report.entries}
    assert "acme/pinned@1.0.0" not in refs
    assert "acme/bundle@1.0.0" not in refs
    assert "acme/member@1.0.0" not in refs
    assert report.protected["acme/pinned@1.0.0"] == "pinned"
    assert report.protected["acme/member@1.0.0"].startswith(
        "member of retained bundle"
    )


def test_gc_prunes_only_empty_package_and_owner_stubs(tmp_home):
    from capacium.commands.gc import garbage_collect

    packages = tmp_home / ".capacium" / "packages"
    stale_cap = packages / "retired-owner" / "empty-cap"
    (stale_cap / "1.0.0").mkdir(parents=True)
    real_cap = packages / "real-owner" / "real-cap" / "1.0.0"
    real_cap.mkdir(parents=True)
    (real_cap / "payload.bin").write_bytes(b"keep")

    dry_run = garbage_collect(keep=1, dry_run=True)
    assert stale_cap in dry_run.empty_stubs
    assert stale_cap.exists()
    assert real_cap.exists()

    applied = garbage_collect(keep=1, dry_run=False)
    assert stale_cap in applied.pruned_stubs
    assert not (packages / "retired-owner").exists()
    assert real_cap.exists()
    assert (packages / "real-owner").exists()


def test_gc_dry_run_does_not_trigger_legacy_store_migration(tmp_home):
    from capacium.commands.gc import garbage_collect

    legacy = tmp_home / ".capacium" / "packages" / "legacy-cap" / "1.0.0"
    legacy.mkdir(parents=True)
    (legacy / "capability.yaml").write_text(
        "kind: skill\nname: legacy-cap\nversion: 1.0.0\ndescription: legacy\n"
    )

    garbage_collect(keep=1, dry_run=True)

    assert legacy.exists()
    assert not (
        tmp_home / ".capacium" / "packages" / "global" / "legacy-cap"
    ).exists()


def test_repair_dry_run_and_yes_handle_empty_stubs_only(tmp_home, capsys):
    from capacium.commands.repair import repair

    packages = tmp_home / ".capacium" / "packages"
    stale_cap = packages / "retired-owner" / "empty-cap"
    (stale_cap / "1.0.0").mkdir(parents=True)
    real_cap = packages / "real-owner" / "real-cap" / "1.0.0"
    real_cap.mkdir(parents=True)
    (real_cap / "payload.bin").write_bytes(b"keep")

    assert repair(
        SimpleNamespace(capability=None, dry_run=True, yes=False, json=False)
    )
    assert stale_cap.exists()
    assert "empty package stub" in capsys.readouterr().out

    assert repair(
        SimpleNamespace(capability=None, dry_run=False, yes=True, json=False)
    )
    assert not (packages / "retired-owner").exists()
    assert real_cap.exists()


def test_install_prune_runs_only_after_successful_explicit_opt_in(
    tmp_home, tmp_path, monkeypatch
):
    from capacium.commands.install import install_capability

    registry = Registry()
    _add_capability(tmp_home, registry, "0.9.0", kind=Kind.BUNDLE)
    _add_capability(tmp_home, registry, "0.9.0", name="member")
    source = tmp_path / "widget-source"
    member_source = source / "skills" / "member"
    member_source.mkdir(parents=True)
    (source / "capability.yaml").write_text(
        "kind: bundle\nname: widget\nversion: 1.0.0\ndescription: fixture\n"
        "frameworks:\n- opencode\ncapabilities:\n"
        "- name: member\n  source: ./skills/member\n  version: 1.0.0\n"
    )
    (member_source / "capability.yaml").write_text(
        "kind: skill\nname: member\nversion: 1.0.0\ndescription: member\n"
        "frameworks:\n- opencode\n"
    )
    (member_source / "SKILL.md").write_text("# Member\n")

    class Adapter:
        def capability_exists(self, _name):
            return False

        def install_capability(self, *_args, **_kwargs):
            return True

    adapter = Adapter()
    monkeypatch.setattr("capacium.adapters.get_adapter", lambda _framework: adapter)

    lock_succeeds = False
    monkeypatch.setattr(
        "capacium.commands.lock.enforce_lock",
        lambda *_args, **_kwargs: lock_succeeds,
    )

    prune_calls = []
    monkeypatch.setattr(
        "capacium.commands.gc.prune_superseded_versions",
        lambda owner, name, keep_version: prune_calls.append(
            (owner, name, keep_version)
        ),
    )

    assert not install_capability(
        "acme/widget@1.0.0",
        source_dir=source,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
        prune=True,
    )
    assert prune_calls == []

    lock_succeeds = True
    assert install_capability(
        "acme/widget@1.0.0",
        source_dir=source,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
        prune=True,
    )
    assert prune_calls == [
        ("acme", "member", "1.0.0"),
        ("acme", "widget", "1.0.0"),
    ]
