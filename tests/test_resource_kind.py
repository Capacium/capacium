"""Tests for the resource kind (CAP-001)."""

from pathlib import Path

from capacium.manifest import Manifest
from capacium.models import Kind, Capability
from capacium.commands.init import VALID_KINDS, _validate_kind


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestResourceManifestFixtures:
    def test_load_resource_minimal(self):
        m = Manifest.load(FIXTURES_DIR / "resource-minimal.yaml")
        assert m.kind == "resource"
        assert m.name == "test-prompt-library"
        assert m.version == "1.0.0"
        assert m.description == "A collection of prompt templates for code review"

    def test_load_resource_full(self):
        m = Manifest.load(FIXTURES_DIR / "resource-full.yaml")
        assert m.kind == "resource"
        assert m.name == "test-dataset"
        assert m.version == "2.0.0"
        assert m.description == "Training dataset for sentiment analysis"
        assert m.author == "test-org"
        assert m.license == "MIT"
        assert m.keywords == ["dataset", "nlp", "sentiment"]

    def test_resource_kind_accepted(self):
        m = Manifest(kind="resource", name="my-resource", version="1.0.0", description="A resource")
        assert m.kind == "resource"
        errors = m.validate()
        assert errors == []

    def test_resource_no_mcp_required(self):
        m = Manifest(kind="resource", name="my-resource", version="1.0.0", description="A resource")
        errors = m.validate()
        # Should NOT contain any MCP-related errors
        assert not any("mcp" in e.lower() for e in errors)
        assert not any("transport" in e.lower() for e in errors)

    def test_resource_requires_description(self):
        m = Manifest(kind="resource", name="my-resource", version="1.0.0", description="")
        errors = m.validate()
        assert "Resource manifest requires a description" in errors

    def test_resource_with_description_passes(self):
        m = Manifest(kind="resource", name="my-resource", version="1.0.0", description="Has a description")
        errors = m.validate()
        assert "Resource manifest requires a description" not in errors


class TestResourceKindEnum:
    def test_resource_in_kind_enum(self):
        assert Kind.RESOURCE.value == "resource"

    def test_all_kinds_include_resource(self):
        kinds = {k.value for k in Kind}
        assert "resource" in kinds

    def test_capability_with_resource_kind(self):
        cap = Capability(owner="test", name="my-res", version="1.0.0", kind=Kind.RESOURCE)
        assert cap.kind == Kind.RESOURCE
        d = cap.to_dict()
        assert d["kind"] == "resource"

    def test_capability_from_dict_resource(self):
        d = {
            "owner": "test",
            "name": "my-res",
            "version": "1.0.0",
            "kind": "resource",
            "fingerprint": "",
            "install_path": "",
            "installed_at": "",
        }
        cap = Capability.from_dict(d)
        assert cap.kind == Kind.RESOURCE


class TestResourceInCLIInit:
    def test_resource_in_valid_kinds(self):
        assert "resource" in VALID_KINDS

    def test_validate_kind_accepts_resource(self):
        assert _validate_kind("resource") is None

    def test_validate_kind_rejects_invalid(self):
        assert _validate_kind("invalid-kind") is not None
