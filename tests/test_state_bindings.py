"""CAP117-STATE-001 — desired-harness lifecycle and binding-state fixtures
(criteria 4 and 5).

Criterion 4: removing or replacing a desired harness target requires no
manifest edit and leaves foreign harness entries unchanged.

Criterion 5: state fixtures for desired, present, missing, foreign and broken
bindings pass on macOS, Linux and Windows.

These proofs fail against the base (``5dba8da``): the desired layer can only be
written wholesale through ``set_desired_bindings`` and there is no per-target
add/remove/replace, no binding-state classification, and no guarantee that a
desired-target change leaves foreign harness entries alone.

Portability: fixtures materialize real directories carrying a
``.cap-meta.json`` marker instead of symlinks, because creating symlinks on
Windows needs elevation. "broken" is expressed as a version mismatch, which is
host-independent; the dangling-symlink branch of the classifier is exercised on
macOS/Linux only.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from capacium.framework_detector import framework_skills_dirs
from capacium.models import Capability, Kind
from capacium.registry import Registry


def _cap(name: str = "bind-cap", frameworks=None, install_path: Path | None = None) -> Capability:
    return Capability(
        owner="test",
        name=name,
        version="1.0.0",
        kind=Kind.SKILL,
        fingerprint="fp",
        install_path=install_path or Path(f"/tmp/{name}"),
        installed_at=datetime.now(),
        frameworks=list(frameworks or []),
    )


def _harness_dir(framework: str) -> Path:
    dirs = framework_skills_dirs()
    assert framework in dirs, f"unknown harness location: {framework}"
    return dirs[framework]


def _materialize(framework: str, name: str, *, owner: str, version: str,
                 marker: str = "live") -> Path:
    """Write a Capacium-attested skill entry (real dir + ``.cap-meta.json``)."""
    entry = _harness_dir(framework) / name
    entry.mkdir(parents=True, exist_ok=True)
    (entry / ".cap-meta.json").write_text(json.dumps({
        "name": name,
        "owner": owner,
        "version": version,
    }))
    (entry / "SKILL.md").write_text(marker)
    return entry


def _materialize_foreign(framework: str, name: str, marker: str = "foreign") -> Path:
    """Write a foreign entry: present in the harness dir, no Capacium mark."""
    entry = _harness_dir(framework) / name
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "SKILL.md").write_text(marker)
    return entry


def _snapshot(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = path.read_text() if path.is_file() else None
    return out


def _manifest_dir(tmp_path: Path, name: str = "bind-cap") -> Path:
    pkg = tmp_path / "pkg" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "capability.yaml").write_text(
        f"kind: skill\nname: {name}\nversion: 1.0.0\n"
        "frameworks:\n  - opencode\n"
    )
    return pkg


class TestCriterion4DesiredTargetLifecycle:
    """Removing or replacing a desired target is a local-state operation that
    leaves the published manifest and foreign harness entries untouched."""

    def test_remove_desired_target_needs_no_manifest_edit(self, tmp_path):
        pkg = _manifest_dir(tmp_path)
        manifest_before = (pkg / "capability.yaml").read_bytes()
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"], install_path=pkg))
        reg.set_published_frameworks("test/bind-cap", "1.0.0", ["opencode"])
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode", "codex"])

        assert reg.remove_desired_binding("test/bind-cap", "1.0.0", "codex") is True

        assert reg.get_desired_bindings("test/bind-cap", "1.0.0") == ["opencode"]
        # No manifest edit: the published recommendation and the manifest file
        # on disk are byte-identical.
        assert reg.get_published_frameworks("test/bind-cap", "1.0.0") == ["opencode"]
        assert (pkg / "capability.yaml").read_bytes() == manifest_before

    def test_replace_desired_target_needs_no_manifest_edit(self, tmp_path):
        pkg = _manifest_dir(tmp_path)
        manifest_before = (pkg / "capability.yaml").read_bytes()
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"], install_path=pkg))
        reg.set_published_frameworks("test/bind-cap", "1.0.0", ["opencode"])
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])

        assert reg.replace_desired_binding(
            "test/bind-cap", "1.0.0", "opencode", "codex"
        ) is True

        assert reg.get_desired_bindings("test/bind-cap", "1.0.0") == ["codex"]
        assert reg.get_published_frameworks("test/bind-cap", "1.0.0") == ["opencode"]
        assert (pkg / "capability.yaml").read_bytes() == manifest_before

    def test_add_desired_target_is_registry_only(self, tmp_home, tmp_path):
        pkg = _manifest_dir(tmp_path)
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"], install_path=pkg))
        reg.set_published_frameworks("test/bind-cap", "1.0.0", ["opencode"])

        assert reg.add_desired_binding("test/bind-cap", "1.0.0", "codex") is True
        assert reg.get_desired_bindings("test/bind-cap", "1.0.0") == ["codex"]
        # Nothing was materialized on disk by a state-layer change.
        assert not (_harness_dir("codex") / "bind-cap").exists()

    def test_remove_leaves_foreign_harness_entries_unchanged(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"]))
        reg.set_published_frameworks("test/bind-cap", "1.0.0", ["opencode"])
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode", "codex"])

        foreign = _materialize_foreign("codex", "bind-cap", marker="foreign-owned")
        before = _snapshot(_harness_dir("codex"))

        assert reg.remove_desired_binding("test/bind-cap", "1.0.0", "codex") is True

        assert foreign.exists()
        assert _snapshot(_harness_dir("codex")) == before

    def test_replace_leaves_foreign_harness_entries_unchanged(self, tmp_home):
        reg = Registry()
        reg.add_capability(_cap(frameworks=["opencode"]))
        reg.set_published_frameworks("test/bind-cap", "1.0.0", ["opencode"])
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])

        foreign = _materialize_foreign("claude-code", "bind-cap", marker="foreign-owned")
        before = _snapshot(_harness_dir("claude-code"))

        assert reg.replace_desired_binding(
            "test/bind-cap", "1.0.0", "opencode", "codex"
        ) is True

        assert foreign.exists()
        assert _snapshot(_harness_dir("claude-code")) == before


class TestCriterion5BindingStateFixtures:
    """One fixture per binding state; every fixture is host-independent."""

    def _registry(self) -> Registry:
        reg = Registry()
        reg.add_capability(_cap())
        return reg

    def test_desired_binding_is_desired(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])

        states = reg.get_binding_states("test/bind-cap", "1.0.0")
        assert states["opencode"]["desired"] is True
        assert states["opencode"]["state"] == "missing"

    def test_present_binding_is_present(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])
        _materialize("opencode", "bind-cap", owner="test", version="1.0.0")

        states = reg.get_binding_states("test/bind-cap", "1.0.0")
        assert states["opencode"]["state"] == "present"

    def test_missing_binding_is_missing(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode", "codex"])

        states = reg.get_binding_states("test/bind-cap", "1.0.0")
        assert states["codex"]["state"] == "missing"
        assert states["codex"]["location"] is None

    def test_foreign_binding_is_foreign(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])
        _materialize_foreign("opencode", "bind-cap")

        states = reg.get_binding_states("test/bind-cap", "1.0.0")
        assert states["opencode"]["state"] == "foreign"

    def test_broken_binding_is_broken(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])
        # Attested for the same owner/name but a different version: the marker
        # no longer matches, so the binding is broken rather than healthy.
        _materialize("opencode", "bind-cap", owner="test", version="0.9.0")

        states = reg.get_binding_states("test/bind-cap", "1.0.0")
        assert states["opencode"]["state"] == "broken"

    def test_all_five_states_in_one_projection(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings(
            "test/bind-cap", "1.0.0",
            ["opencode", "codex", "claude-code", "gemini-cli"],
        )
        _materialize("opencode", "bind-cap", owner="test", version="1.0.0")  # present
        _materialize_foreign("codex", "bind-cap")                            # foreign
        _materialize("claude-code", "bind-cap", owner="test", version="0.9.0")  # broken
        # gemini-cli: desired, never materialized -> missing

        states = reg.get_binding_states("test/bind-cap", "1.0.0")
        assert states["opencode"]["state"] == "present"
        assert states["codex"]["state"] == "foreign"
        assert states["claude-code"]["state"] == "broken"
        assert states["gemini-cli"]["state"] == "missing"
        assert all(s["desired"] for s in states.values())

    def test_foreign_entry_survives_state_layer_rewrites(self, tmp_home):
        reg = self._registry()
        reg.set_desired_bindings("test/bind-cap", "1.0.0", ["opencode"])
        foreign = _materialize_foreign("opencode", "bind-cap", marker="keep-me")
        before = _snapshot(_harness_dir("opencode"))

        reg.replace_desired_binding("test/bind-cap", "1.0.0", "opencode", "codex")
        reg.add_desired_binding("test/bind-cap", "1.0.0", "claude-code")
        reg.remove_desired_binding("test/bind-cap", "1.0.0", "claude-code")

        assert foreign.exists()
        assert _snapshot(_harness_dir("opencode")) == before
