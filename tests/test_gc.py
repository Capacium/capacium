import json
import shutil
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


def test_gc_preserves_bundle_that_physically_owns_a_retained_member(tmp_home):
    from capacium.commands.gc import garbage_collect

    registry = Registry()
    old_bundle = _add_capability(
        tmp_home, registry, "1.0.0", name="bundle", kind=Kind.BUNDLE
    )
    new_bundle = _add_capability(
        tmp_home, registry, "2.0.0", name="bundle", kind=Kind.BUNDLE
    )
    member = _add_capability(tmp_home, registry, "1.0.0", name="member")

    member_payload = old_bundle.install_path / "skills" / "member"
    member_payload.mkdir(parents=True)
    (member_payload / "SKILL.md").write_text("# Member\n")
    shutil.rmtree(member.install_path)
    member.install_path.symlink_to(member_payload, target_is_directory=True)
    registry.update_capability(member)
    registry.add_bundle_member(
        f"acme/bundle@{new_bundle.version}", f"acme/member@{member.version}"
    )

    report = garbage_collect(keep=1, dry_run=True)
    refs = {entry.ref for entry in report.entries}
    assert f"acme/bundle@{old_bundle.version}" not in refs
    assert report.protected[f"acme/bundle@{old_bundle.version}"].startswith(
        "physical owner of retained"
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


# ---------------------------------------------------------------------------
# CAP-REC-D2 — cleanup plan: adopt / relink / quarantine / delete per entry
# ---------------------------------------------------------------------------


def _plan_for(tmp_home, monkeypatch):
    """Build the reconciler fixture state and return the cleanup plan."""
    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    from tests.test_reconcile_fixture import build_fixture_state
    from capacium.commands.gc import build_cleanup_plan

    build_fixture_state(tmp_home)
    return build_cleanup_plan()


def test_cleanup_plan_names_each_action_with_reason(tmp_home, monkeypatch):
    """Acceptance 3: the plan emits adopt/relink/quarantine/delete per entry,
    and every action carries a non-empty reason — never a bare action name."""
    from capacium.commands.gc import CleanupAction

    actions = _plan_for(tmp_home, monkeypatch)

    # All dispositions appear, including the deliberate non-mutation "refuse"
    # a linked-but-unregistered install must be refused rather than moved.
    by_action = {}
    for action in actions:
        by_action.setdefault(action.action, []).append(action)
    assert set(by_action) <= {"adopt", "relink", "quarantine", "delete", "refuse"}
    assert "delete" in by_action
    assert "quarantine" in by_action
    assert "relink" in by_action
    assert "adopt" in by_action
    assert "refuse" in by_action

    for action in actions:
        assert isinstance(action, CleanupAction)
        assert action.reason, "a cleanup action must carry a per-entry reason"

    # Dead links map to delete.
    dead = {str(a.target) for a in by_action["delete"]}
    assert any("sub-skill" in p for p in dead)
    assert any("kind-skill" in p for p in dead)

    # Foreign entries (rtk symlink, stray SKILL.md) map to adopt.
    adopted = {str(a.target) for a in by_action["adopt"]}
    assert any("rtk" in p for p in adopted)
    assert any("SKILL.md" in p for p in adopted)


def test_cleanup_plan_distinguishes_stale_from_dead(tmp_home, monkeypatch):
    """The 2026-08-16 guard: look-alike links with different purposes are never
    collapsed. The stale txtHumanizer links are relinked, the dead
    txtHumanizer-dead link is deleted — two distinct dispositions."""
    actions = _plan_for(tmp_home, monkeypatch)

    relinked = {str(a.target) for a in actions if a.action == "relink"}
    deleted = {str(a.target) for a in actions if a.action == "delete"}

    assert any("txtHumanizer" in p and "dead" not in p for p in relinked)
    assert any("txtHumanizer-dead" in p for p in deleted)

    # The stale link carries the superseded version and the current version in
    # its reason, proving the disposition is entry-specific.
    stale = next(
        a for a in actions
        if a.action == "relink" and "txtHumanizer" in str(a.target) and "dead" not in str(a.target)
    )
    assert "0.0.2" in stale.reason
    assert "1.0.0" in stale.reason


def test_cleanup_plan_quarantines_unregistered_and_deletes_phantom(tmp_home, monkeypatch):
    """Acceptance 2 half: an unregistered install (no registry row) is
    quarantined, never deleted; a phantom registered row (no files) is deleted."""
    actions = _plan_for(tmp_home, monkeypatch)

    quarantined = {str(a.target) for a in actions if a.action == "quarantine"}
    assert any("mempalace" in p for p in quarantined)
    # global/elementeer-mcp old-owner copy is on disk but unregistered. It is
    # also the target of a live harness link (antigravity-backup -> old owner),
    # so it MUST be refused, never quarantined — quarantining it would sever
    # the live link (CAP-REC-D2 blocker). The genuinely unlinked mempalace is
    # still quarantined above.
    refused = {str(a.target) for a in actions if a.action == "refuse"}
    assert any("global/elementeer-mcp" in p for p in refused)
    assert not any("global/elementeer-mcp" in p for p in quarantined)

    deleted = {
        a.ref: a for a in actions if a.action == "delete" and a.ref
    }
    assert any(
        ref and "skillweave-blueprint@1.3.0" in ref for ref in deleted
    )


def test_apply_cleanup_dry_run_mutates_nothing(tmp_home, monkeypatch, capsys):
    """Dry-run prints the plan but leaves the filesystem untouched."""
    from tests.test_reconcile_fixture import build_fixture_state
    from capacium.commands.gc import build_cleanup_plan, apply_cleanup

    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    build_fixture_state(tmp_home)

    dead_link = tmp_home / ".gemini" / "antigravity-backup" / "skills" / "txtHumanizer-dead"
    assert dead_link.is_symlink()

    actions = build_cleanup_plan()
    report = apply_cleanup(actions, dry_run=True)

    assert report.applied == []
    assert report.quarantined == []
    assert dead_link.is_symlink(), "dry-run must not delete a dead link"

    out = capsys.readouterr().out
    assert "delete" in out
    assert "relink" in out
    assert "quarantine" in out


def test_apply_cleanup_relinks_stale_and_deletes_dead(tmp_home, monkeypatch):
    """Real apply: a stale link is rewritten to the current generation, a dead
    link is removed, and the current generation is left registered (criterion 1 + 2)."""
    from tests.test_reconcile_fixture import build_fixture_state
    from capacium.commands.gc import build_cleanup_plan, apply_cleanup
    from capacium.registry import Registry

    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)
    build_fixture_state(tmp_home)
    registry = Registry()

    dead_link = tmp_home / ".gemini" / "antigravity-backup" / "skills" / "txtHumanizer-dead"
    assert dead_link.is_symlink()

    apply_cleanup(build_cleanup_plan(registry=registry), dry_run=False, registry=registry)

    assert not dead_link.is_symlink(), "dead link should be removed after apply"

    # The stale top-level txtHumanizer link now points at the current 1.0.0.
    stale_link = tmp_home / ".gemini" / "antigravity-backup" / "skills" / "txtHumanizer"
    assert stale_link.is_symlink()
    assert "1.0.0" in str(stale_link.resolve())

    # The current generation is still registered.
    assert registry.get_capability("LangeVC/txtHumanizer", "1.0.0") is not None


def test_prune_superseded_relinks_stale_harness_link(tmp_home, monkeypatch):
    """Criterion 1: after a superseding install, a harness link still pointing at
    the old generation is relinked to the new one — no harness exposes two
    versions at once (the measured 2026-08-22 `install --prune` removed nothing)."""
    from capacium.commands.gc import prune_superseded_versions

    registry = Registry()
    old = _add_capability(tmp_home, registry, "1.0.0")
    _add_capability(tmp_home, registry, "2.0.0")

    skills_dir = tmp_home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    link = skills_dir / "widget"
    link.symlink_to(old.install_path, target_is_directory=True)

    prune_superseded_versions("acme", "widget", "2.0.0")

    assert link.is_symlink()
    assert str(link.resolve()).endswith("2.0.0"), "stale link was not relinked to the new generation"
    assert registry.get_capability("acme/widget", "2.0.0") is not None


def test_prune_superseded_leaves_linked_version_alone(tmp_home, monkeypatch):
    """Criterion 2: a generation a harness still links to is never removed while
    linked, even when it is not the newest."""
    from capacium.commands.gc import prune_superseded_versions

    registry = Registry()
    old = _add_capability(tmp_home, registry, "1.0.0")
    _add_capability(tmp_home, registry, "2.0.0")

    skills_dir = tmp_home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    link = skills_dir / "widget"
    link.symlink_to(old.install_path, target_is_directory=True)

    prune_superseded_versions("acme", "widget", "2.0.0")

    # The old generation directory survives (registry-linked), and its files exist.
    assert old.install_path.exists()
    assert registry.get_capability("acme/widget", "1.0.0") is not None


def test_cleanup_refuses_quarantine_for_a_live_harness_link(tmp_home, monkeypatch, capsys):
    """The adversarial-reviewer reproduction, acceptance 1 + 3: an on-disk install
    with no registry row that a live harness link resolves into must be refused,
    never quarantined — quarantining it would sever the link the reconciler just
    classified ok/alive. Dry-run must name the conflict, not print a benign move."""
    from capacium.commands.gc import build_cleanup_plan, apply_cleanup

    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)

    packages = tmp_home / ".capacium" / "packages"
    install_dir = packages / "foo" / "bar" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "SKILL.md").write_text("---\nname: bar\n---\n")

    skills_dir = tmp_home / ".opencode" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "bar").symlink_to(install_dir, target_is_directory=True)

    actions = build_cleanup_plan()

    by_action = {}
    for a in actions:
        by_action.setdefault(a.action, []).append(a)
    assert "refuse" in by_action
    quarantined = {str(a.target) for a in actions if a.action == "quarantine"}
    refused = {str(a.target) for a in actions if a.action == "refuse"}
    assert str(install_dir.resolve()) in refused
    assert not any("foo/bar" in p for p in quarantined)

    # The directory and the live link are untouched after a real apply.
    apply_cleanup(actions, dry_run=False)
    assert install_dir.exists()
    assert (skills_dir / "bar").is_symlink()

    # Dry-run names the conflict, not a benign move.
    out = capsys.readouterr().out
    assert "refuse" in out
    assert "live harness link" in out or "linked" in out


def test_adopt_writes_real_provenance_not_placeholder(tmp_home, monkeypatch):
    """R4-A LOW-1: adopt derives owner/name/version/kind/fingerprint from the
    adopted directory's own manifest, never a hardcoded global/0.0.0 placeholder."""
    import json as _json

    from capacium.commands.gc import _apply_cleanup_action, CleanupAction
    from capacium.registry import Registry

    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)

    foreign = tmp_home / "custom-skill"
    foreign.mkdir(parents=True)
    (foreign / "capability.yaml").write_text(
        "kind: skill\nname: custom-skill\nversion: 2.3.4\ndescription: adopted\n"
    )
    (foreign / "SKILL.md").write_text("---\nname: custom-skill\n---\n")

    registry = Registry()
    action = CleanupAction(
        action="adopt",
        target=foreign,
        reason="foreign entry is not managed by Capacium",
        ref=str(foreign),
    )
    assert _apply_cleanup_action(action, registry, tmp_home / "q")

    meta = _json.loads((foreign / ".cap-meta.json").read_text())
    assert meta["name"] == "custom-skill"
    assert meta["version"] == "2.3.4"
    assert meta["kind"] == "skill"
    assert meta["fingerprint"] and meta["fingerprint"] != "f" * 64


def test_hold_drift_emits_no_empty_target_relink(tmp_home, monkeypatch):
    """R4-A LOW-2: a hold_drift finding with no matching harness link emits no
    relink action carrying an empty target=Path()."""
    import json as _json

    from capacium.commands.gc import build_cleanup_plan

    monkeypatch.delenv("CAPACIUM_PROJECT_ROOT", raising=False)

    registry = Registry()
    _add_capability(tmp_home, registry, "1.0.0", owner="acme", name="held-cap")

    holds_path = tmp_home / ".capacium" / "holds.json"
    holds_path.write_text(
        _json.dumps({"acme/held-cap": {"version": "0.9.0", "reason": "patched"}})
    )

    actions = build_cleanup_plan()

    hold_relinks = [a for a in actions if a.action == "relink" and a.ref == "acme/held-cap"]
    for a in hold_relinks:
        assert str(a.target), "hold_drift must never emit an empty relink target"
    empty_targets = [a for a in actions if a.action == "relink" and not str(a.target)]
    assert empty_targets == []
