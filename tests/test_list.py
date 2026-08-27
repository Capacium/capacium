import pytest
from pathlib import Path
from capacium.commands.list_capabilities import list_capabilities, _get_valid_frameworks
from capacium.models import Capability, Kind
from datetime import datetime

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
