"""UP-001 (V8): cap hold — update guard for locally patched packages.

- cap hold <cap> prevents cap update from touching the package
- fingerprint drift (local patch) without hold suppresses the
  newer-version force-reinstall and points to 'cap hold'
- unhold releases the guard
"""
import json

import pytest

from capacium.commands.hold import (
    get_hold,
    hold_capability,
    load_holds,
    unhold_capability,
)
from capacium.commands.update import update_capability
from capacium.fingerprint import compute_fingerprint
from capacium.models import Capability, Kind
from capacium.registry import Registry


@pytest.fixture
def installed_cap(tmp_home):
    package_dir = tmp_home / ".capacium" / "packages" / "helallao" / "px" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "capability.yaml").write_text(
        "name: px\nversion: 1.0.0\nkind: skill\ndescription: t\n"
    )
    (package_dir / "SKILL.md").write_text("# px\n")
    fingerprint = compute_fingerprint(
        package_dir,
        exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store",
                          ".capacium-meta.json", ".cap-meta.json",
                          "capability.lock"],
    )
    registry = Registry()
    cap = Capability(
        owner="helallao", name="px", version="1.0.0", kind=Kind.SKILL,
        install_path=package_dir, fingerprint=fingerprint,
        framework="claude-code", frameworks=["claude-code"],
        source_url="https://github.com/helallao/px",
    )
    assert registry.add_capability(cap)
    return {"registry": registry, "cap": cap, "package_dir": package_dir}


class TestHoldLifecycle:
    def test_hold_set_and_persisted(self, tmp_home, installed_cap):
        assert hold_capability("helallao/px", reason="local patch") is True
        hold = get_hold("helallao/px")
        assert hold is not None
        assert hold["reason"] == "local patch"
        holds_file = tmp_home / ".capacium" / "holds.json"
        assert holds_file.is_file()
        assert "helallao/px" in json.loads(holds_file.read_text())

    def test_hold_records_drift(self, tmp_home, installed_cap, capsys):
        (installed_cap["package_dir"] / "SKILL.md").write_text("# patched\n")
        assert hold_capability("helallao/px") is True
        out = capsys.readouterr().out
        assert "drift" in out.lower() or "modifications" in out.lower()

    def test_hold_unknown_cap_fails(self, tmp_home):
        assert hold_capability("nobody/nothing") is False

    def test_unhold_releases(self, tmp_home, installed_cap):
        hold_capability("helallao/px")
        assert unhold_capability("helallao/px") is True
        assert get_hold("helallao/px") is None
        assert unhold_capability("helallao/px") is False

    def test_load_holds_tolerates_garbage(self, tmp_home):
        holds_file = tmp_home / ".capacium" / "holds.json"
        holds_file.parent.mkdir(parents=True, exist_ok=True)
        holds_file.write_text("{not json")
        assert load_holds() == {}


class TestUpdateGuard:
    def test_update_skips_held_package_with_notice(
        self, tmp_home, installed_cap, capsys, monkeypatch
    ):
        called = []
        monkeypatch.setattr(
            "capacium.commands.update._check_for_newer_version",
            lambda *a, **kw: called.append(a),
        )
        hold_capability("helallao/px", reason="pending upstream PR")
        capsys.readouterr()

        ok = update_capability("helallao/px")
        out = capsys.readouterr().out
        assert ok is True
        assert "held" in out
        assert "pending upstream PR" in out
        assert called == []  # no fetch, no reconcile mutation

    def test_update_with_drift_suppresses_newer_version_fetch(
        self, tmp_home, installed_cap, capsys, monkeypatch
    ):
        called = []
        monkeypatch.setattr(
            "capacium.commands.update._check_for_newer_version",
            lambda *a, **kw: called.append(a),
        )
        (installed_cap["package_dir"] / "SKILL.md").write_text("# patched locally\n")

        ok = update_capability("helallao/px")
        out = capsys.readouterr().out
        assert ok is True
        assert called == [], "drifted package must not be force-reinstalled"
        assert "cap hold" in out

    def test_update_without_drift_checks_newer_version(
        self, tmp_home, installed_cap, capsys, monkeypatch
    ):
        called = []
        monkeypatch.setattr(
            "capacium.commands.update._check_for_newer_version",
            lambda *a, **kw: called.append(a) or False,
        )
        ok = update_capability("helallao/px")
        assert ok is True
        assert len(called) == 1

    def test_unhold_restores_update_path(
        self, tmp_home, installed_cap, capsys, monkeypatch
    ):
        called = []
        monkeypatch.setattr(
            "capacium.commands.update._check_for_newer_version",
            lambda *a, **kw: called.append(a) or False,
        )
        hold_capability("helallao/px")
        unhold_capability("helallao/px")
        ok = update_capability("helallao/px")
        assert ok is True
        assert len(called) == 1
