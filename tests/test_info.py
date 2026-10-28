import json

from capacium.commands.info import (
    _resolve_from_local_registry,
    _fingerprint_status,
    cap_info,
)
from capacium.models import Capability, Kind
from capacium.registry import Registry
from datetime import datetime

STATE_KEYS = ("desired", "installed", "verified", "drifted", "unavailable")

INFO_EXISTING_KEYS = (
    "$schema",
    "name",
    "owner",
    "kind",
    "trust",
    "version",
    "description",
    "stars",
    "forks",
    "license",
    "categories",
    "tags",
    "frameworks",
    "runtimes",
    "dependencies",
    "fingerprint",
    "source_url",
    "source_ref",
    "source_commit",
    "publisher",
    "updated_at",
    "aliases",
)

class DummyRegistry:
    def __init__(self, cap):
        self.cap = cap
    def get_capability(self, id, version=None):
        return self.cap

def test_resolve_local_phantom(tmp_path, monkeypatch):
    cap = Capability(
        owner="acme", name="test-skill", version="1.0.0", kind=Kind.SKILL,
        install_path=tmp_path / "does_not_exist"
    )
    monkeypatch.setattr("capacium.registry.Registry", lambda *a, **kw: DummyRegistry(cap))
    
    res = _resolve_from_local_registry("acme/test-skill")
    assert res is None, "Should return None for phantom capability"

def test_fingerprint_status_unverified():
    detail = {"fingerprint": "abc", "fingerprint_verified": False}
    status = _fingerprint_status(detail)
    assert "unverified" in status

def test_fingerprint_status_verified():
    detail = {"fingerprint": "abc", "fingerprint_verified": True}
    status = _fingerprint_status(detail)
    assert "verified" in status


def _no_harness_dirs(monkeypatch):
    """Hide the live harness directories from the attestation scan, so the
    state shown comes only from what the registry recorded."""
    monkeypatch.setattr(
        "capacium.framework_detector.framework_skills_dirs", lambda: {}
    )


def _installed_registry(tmp_home, frameworks):
    registry = Registry()
    install_dir = tmp_home / "state-cap"
    install_dir.mkdir(parents=True, exist_ok=True)
    assert registry.add_capability(
        Capability(
            owner="acme",
            name="state-cap",
            version="1.0.0",
            kind=Kind.SKILL,
            fingerprint="fp",
            install_path=install_dir,
            installed_at=datetime.now(),
            frameworks=list(frameworks),
        )
    )
    return registry


def test_info_json_exposes_state_layers(tmp_home, capsys, monkeypatch):
    """Criterion 3: `cap info --json` exposes the five state fields."""
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    cap_info("acme/state-cap@1.0.0", json_output=True)
    detail = json.loads(capsys.readouterr().out)

    for key in STATE_KEYS:
        assert key in detail, f"cap info --json missing state field: {key}"


def test_info_json_keeps_existing_keys(tmp_home, capsys, monkeypatch):
    """The state fields are additive: the v1 key set stays unchanged."""
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    cap_info("acme/state-cap@1.0.0", json_output=True)
    detail = json.loads(capsys.readouterr().out)

    for key in INFO_EXISTING_KEYS:
        assert key in detail, f"cap info --json dropped existing key: {key}"
    assert detail["name"] == "state-cap"
    assert detail["owner"] == "acme"


def test_info_json_does_not_derive_installed_from_recommendations(
    tmp_home, capsys, monkeypatch
):
    """A recommended-but-unattested harness must not read as installed."""
    registry = _installed_registry(tmp_home, ["opencode"])
    registry.set_published_frameworks("acme/state-cap", "1.0.0", ["opencode"])
    registry.set_desired_bindings("acme/state-cap", "1.0.0", ["opencode"])
    _no_harness_dirs(monkeypatch)

    cap_info("acme/state-cap@1.0.0", json_output=True)
    detail = json.loads(capsys.readouterr().out)

    assert detail["installed"] == []
    assert detail["verified"] == []
    assert detail["desired"] == ["opencode"]
    assert "opencode" in detail["drifted"]


# ---------------------------------------------------------------------------
# Criterion 3: separated info sections
# ---------------------------------------------------------------------------

def test_info_separates_sections(tmp_home, capsys, monkeypatch):
    """Human-readable cap info separates recommendations, bindings,
    dependencies, provenance and runtime status."""
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    cap_info("acme/state-cap@1.0.0", json_output=False)
    out = capsys.readouterr().out

    assert "Publisher recommendations" in out
    assert "Bindings" in out
    assert "Dependencies" in out
    assert "Provenance" in out
    assert "Runtime status" in out


def test_info_bindings_shows_desired_verified(tmp_home, capsys, monkeypatch):
    """Human cap info shows desired and verified bindings separately."""
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    cap_info("acme/state-cap@1.0.0", json_output=False)
    out = capsys.readouterr().out

    assert "Desired:" in out
    assert "Verified:" in out


def test_info_no_color_suppresses_ansi(tmp_home, capsys, monkeypatch):
    """NO_COLOR env suppresses ANSI escape sequences in human output."""
    monkeypatch.setenv("NO_COLOR", "1")
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    cap_info("acme/state-cap@1.0.0", json_output=False)
    out = capsys.readouterr().out

    # ANSI escape codes should be absent — no monkeypatching the
    # production colour machinery.
    assert "\x1b[" not in out.lower()
