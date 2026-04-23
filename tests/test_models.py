from datetime import datetime, date
from pathlib import Path
from capacium.models import Capability, Kind


class TestKind:
    def test_kind_values(self):
        assert Kind.SKILL.value == "skill"
        assert Kind.BUNDLE.value == "bundle"
        assert Kind.TOOL.value == "tool"
        assert Kind.PROMPT.value == "prompt"
        assert Kind.TEMPLATE.value == "template"
        assert Kind.WORKFLOW.value == "workflow"

    def test_all_kinds_covered(self):
        kinds = set(k.value for k in Kind)
        expected = {"skill", "bundle", "tool", "prompt", "template", "workflow"}
        assert kinds == expected


class TestCapability:
    def test_default_kind_is_skill(self):
        cap = Capability(owner="test", name="my-cap", version="1.0.0")
        assert cap.kind == Kind.SKILL

    def test_id_format(self):
        cap = Capability(owner="alice", name="my-cap", version="1.0.0")
        assert cap.id == "alice/my-cap"

    def test_id_without_owner(self):
        cap = Capability(owner="global", name="my-cap", version="1.0.0")
        assert cap.id == "global/my-cap"

    def test_to_dict_roundtrip(self):
        now = datetime.now()
        cap = Capability(
            owner="test",
            name="roundtrip-cap",
            version="1.2.3",
            kind=Kind.TOOL,
            fingerprint="abc123",
            install_path=Path("/tmp/test"),
            installed_at=now,
            dependencies=["dep1", "dep2"],
            framework="opencode",
        )
        d = cap.to_dict()
        restored = Capability.from_dict(d)
        assert restored.owner == "test"
        assert restored.name == "roundtrip-cap"
        assert restored.version == "1.2.3"
        assert restored.kind == Kind.TOOL
        assert restored.fingerprint == "abc123"
        assert restored.framework == "opencode"
        assert restored.installed_at is not None
        assert restored.installed_at.date() == now.date()
        assert restored.dependencies == ["dep1", "dep2"]

    def test_from_dict_defaults(self):
        d = {"name": "minimal", "fingerprint": "x", "install_path": "/tmp/x", "installed_at": "2024-01-01T00:00:00"}
        cap = Capability.from_dict(d)
        assert cap.owner == "global"
        assert cap.kind == Kind.SKILL
        assert cap.framework is None
        assert cap.dependencies is None
