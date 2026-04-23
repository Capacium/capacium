from datetime import datetime
from pathlib import Path
from capacium.registry import Registry
from capacium.models import Capability, Kind


class TestRegistry:
    def test_init_creates_db(self, tmp_home):
        reg = Registry()
        assert reg.db_path.exists()

    def test_add_and_get_capability(self, tmp_home):
        reg = Registry()
        cap = Capability(
            owner="test",
            name="test-cap",
            version="1.0.0",
            fingerprint="abc123",
            install_path=Path("/tmp/test"),
            installed_at=datetime.now(),
        )
        assert reg.add_capability(cap)
        retrieved = reg.get_capability("test/test-cap")
        assert retrieved is not None
        assert retrieved.name == "test-cap"
        assert retrieved.fingerprint == "abc123"

    def test_get_nonexistent(self, tmp_home):
        reg = Registry()
        assert reg.get_capability("nonexistent") is None

    def test_add_duplicate(self, tmp_home):
        reg = Registry()
        cap = Capability(owner="test", name="dup", version="1.0.0", fingerprint="x",
                         install_path=Path("/tmp"), installed_at=datetime.now())
        assert reg.add_capability(cap)
        assert not reg.add_capability(cap)

    def test_remove_capability(self, tmp_home):
        reg = Registry()
        cap = Capability(owner="test", name="to-remove", version="1.0.0", fingerprint="x",
                         install_path=Path("/tmp"), installed_at=datetime.now())
        reg.add_capability(cap)
        assert reg.remove_capability("test/to-remove")
        assert reg.get_capability("test/to-remove") is None

    def test_list_capabilities(self, tmp_home):
        reg = Registry()
        for i in range(3):
            cap = Capability(owner="test", name=f"cap-{i}", version="1.0.0", fingerprint=str(i),
                             install_path=Path("/tmp"), installed_at=datetime.now())
            reg.add_capability(cap)
        caps = reg.list_capabilities()
        assert len(caps) == 3

    def test_get_by_kind(self, tmp_home):
        reg = Registry()
        for kind in [Kind.SKILL, Kind.BUNDLE, Kind.TOOL]:
            cap = Capability(owner="test", name=f"{kind.value}-cap", version="1.0.0",
                             kind=kind, fingerprint="x",
                             install_path=Path("/tmp"), installed_at=datetime.now())
            reg.add_capability(cap)
        skills = reg.get_by_kind(Kind.SKILL)
        assert len(skills) == 1
        assert skills[0].name == "skill-cap"

    def test_search(self, tmp_home):
        reg = Registry()
        caps = [
            Capability(owner="alice", name="web-helper", version="1.0.0", fingerprint="a",
                       install_path=Path("/tmp"), installed_at=datetime.now()),
            Capability(owner="bob", name="db-tool", version="2.0.0", fingerprint="b",
                       install_path=Path("/tmp"), installed_at=datetime.now()),
        ]
        for cap in caps:
            reg.add_capability(cap)
        results = reg.search_capabilities("web")
        assert len(results) == 1
        assert results[0].name == "web-helper"

    def test_cap_count(self, tmp_home):
        reg = Registry()
        assert reg.cap_count() == 0
        cap = Capability(owner="test", name="count-test", version="1.0.0", fingerprint="f",
                         install_path=Path("/tmp"), installed_at=datetime.now())
        reg.add_capability(cap)
        assert reg.cap_count() == 1

    def test_update_capability(self, tmp_home):
        reg = Registry()
        cap = Capability(owner="test", name="updatable", version="1.0.0", fingerprint="old",
                         install_path=Path("/tmp/old"), installed_at=datetime.now())
        reg.add_capability(cap)
        cap.fingerprint = "new"
        cap.install_path = Path("/tmp/new")
        assert reg.update_capability(cap)
        retrieved = reg.get_capability("test/updatable")
        assert retrieved.fingerprint == "new"
