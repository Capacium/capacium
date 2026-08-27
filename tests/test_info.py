import pytest
from pathlib import Path
from capacium.commands.info import _resolve_from_local_registry, _fingerprint_status
from capacium.models import Capability, Kind
from datetime import datetime

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
