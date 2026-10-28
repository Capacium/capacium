import json

from capacium.commands.list_capabilities import list_capabilities, _get_valid_frameworks
from capacium.models import Capability, Kind
from capacium.registry import Registry
from datetime import datetime

STATE_KEYS = ("desired", "installed", "verified", "drifted", "unavailable")


def _no_harness_dirs(monkeypatch):
    """Hide the live harness directories from both the symlink scan and the
    attestation scan, so the state shown is purely what the registry holds."""
    monkeypatch.setattr(
        "capacium.commands.list_capabilities.framework_skills_dirs", lambda: {}
    )
    monkeypatch.setattr(
        "capacium.framework_detector.framework_skills_dirs", lambda: {}
    )


def _installed_registry(tmp_home, frameworks):
    registry = Registry()
    install_dir = tmp_home / "installed"
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

def test_get_valid_frameworks(tmp_path, monkeypatch):
    cap_path = tmp_path / "packages" / "acme" / "test-skill" / "1.0.0"
    cap_path.mkdir(parents=True)
    
    cap = Capability(
        owner="acme", name="test-skill", version="1.0.0", kind=Kind.SKILL,
        install_path=cap_path, fingerprint="xyz123", installed_at=datetime.now()
    )
    
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    symlink = skills_dir / "test-skill"
    symlink.symlink_to(cap_path)
    
    monkeypatch.setattr(
        "capacium.commands.list_capabilities.framework_skills_dirs",
        lambda: {"opencode": skills_dir}
    )
    
    valid = _get_valid_frameworks(cap)
    assert valid == ["opencode"]


def test_list_json_exposes_state_layers(tmp_home, capsys):
    """Criterion 3: `cap list --json` exposes the five state fields."""
    _installed_registry(tmp_home, ["opencode"])

    list_capabilities(json_output=True)
    listing = json.loads(capsys.readouterr().out)

    assert listing, "listing must contain the installed capability"
    entry = listing[0]
    for key in STATE_KEYS:
        assert key in entry, f"cap list --json missing state field: {key}"


def test_list_json_does_not_derive_installed_from_recommendations(
    tmp_home, capsys, monkeypatch
):
    """A harness that is only *recommended* (published/desired) must never be
    reported as installed or verified in `cap list --json`."""
    registry = _installed_registry(tmp_home, ["opencode"])
    registry.set_published_frameworks("acme/state-cap", "1.0.0", ["opencode"])
    registry.set_desired_bindings("acme/state-cap", "1.0.0", ["opencode"])
    _no_harness_dirs(monkeypatch)

    list_capabilities(json_output=True)
    listing = json.loads(capsys.readouterr().out)

    entry = listing[0]
    assert entry["installed"] == []
    assert entry["verified"] == []
    assert entry["desired"] == ["opencode"]
    assert "opencode" in entry["drifted"]


def test_list_json_keeps_existing_keys(tmp_home, capsys):
    """The state fields are additive: the v1 key set stays unchanged."""
    _installed_registry(tmp_home, ["opencode"])

    list_capabilities(json_output=True)
    entry = json.loads(capsys.readouterr().out)[0]

    for key in (
        "owner",
        "name",
        "version",
        "kind",
        "fingerprint",
        "frameworks",
        "adapter_statuses",
        "installed_at",
        "dependencies",
        "source_url",
        "source_ref",
        "source_commit",
        "previous_identities",
    ):
        assert key in entry, f"cap list --json dropped existing key: {key}"


# ---------------------------------------------------------------------------
# Criterion 2: compact table output
# ---------------------------------------------------------------------------

def test_compact_table_shows_coordinate_version_harnesses_health(
    tmp_home, capsys, monkeypatch
):
    """cap list defaults to a compact table with coordinate, version,
    verified harnesses and one stable health marker."""
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    list_capabilities()
    out = capsys.readouterr().out

    assert "Coordinate" in out
    assert "Version" in out
    assert "Harnesses" in out
    assert "Health" in out
    assert "acme/state-cap" in out
    assert "1.0.0" in out


def test_compact_table_health_unverified(tmp_home, capsys, monkeypatch):
    """Capabilities with no verified harnesses show unverified marker."""
    _installed_registry(tmp_home, [])
    _no_harness_dirs(monkeypatch)

    list_capabilities()
    out = capsys.readouterr().out
    assert "unverified" in out


def test_details_flag_shows_detailed_output(tmp_home, capsys, monkeypatch):
    """--details flag shows per-adapter status, not the compact table."""
    _installed_registry(tmp_home, ["opencode"])
    _no_harness_dirs(monkeypatch)

    list_capabilities(details=True)
    out = capsys.readouterr().out
    assert "Frameworks:" in out or "fingerprint" in out
