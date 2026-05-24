"""Tests for the resource kind (CAP-001 + CAP-002)."""

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


class TestResourceSchema:
    """CAP-002: Resource kind 5-layer progressive schema."""

    def test_load_resource_standard(self):
        m = Manifest.load(FIXTURES_DIR / "resource-standard.yaml")
        assert m.kind == "resource"
        assert m.name == "test-config-templates"
        assert m.resource_type == "config-template"
        assert m.resource_format == "yaml"
        assert m.access == {"method": "file", "path": "templates/"}
        errors = m.validate()
        assert errors == []

    def test_load_resource_full_layers(self):
        m = Manifest.load(FIXTURES_DIR / "resource-full.yaml")
        assert m.kind == "resource"
        assert m.name == "test-dataset"
        assert m.resource_type == "dataset"
        assert m.resource_format == "parquet"
        assert m.size_hint == "medium"
        assert m.access == {"method": "git-submodule", "path": "data/sentiment/"}
        assert m.compatibility == {
            "frameworks": ["claude-code", "cursor"],
            "min_version": "1.0.0",
        }
        errors = m.validate()
        assert errors == []

    def test_invalid_resource_type_rejected(self):
        m = Manifest(
            kind="resource",
            name="bad-type",
            version="1.0.0",
            description="Has bad resource_type",
            resource_type="magic-beans",
        )
        errors = m.validate()
        assert any("Invalid resource_type: magic-beans" in e for e in errors)

    def test_invalid_resource_format_rejected(self):
        m = Manifest(
            kind="resource",
            name="bad-format",
            version="1.0.0",
            description="Has bad format",
            resource_format="xlsx",
        )
        errors = m.validate()
        assert any("Invalid resource format: xlsx" in e for e in errors)

    def test_invalid_size_hint_rejected(self):
        m = Manifest(
            kind="resource",
            name="bad-size",
            version="1.0.0",
            description="Has bad size hint",
            size_hint="enormous",
        )
        errors = m.validate()
        assert any("Invalid size_hint: enormous" in e for e in errors)

    def test_resource_no_mcp_fields_required(self):
        m = Manifest(
            kind="resource",
            name="no-mcp",
            version="1.0.0",
            description="Resource without MCP",
            resource_type="prompt-library",
            resource_format="yaml",
            size_hint="small",
        )
        errors = m.validate()
        assert errors == []
        assert m.mcp == {}
        assert m.entrypoint == ""

    def test_valid_resource_types_accepted(self):
        for rt in ("prompt-library", "dataset", "config-template",
                    "model-weights", "tool-index", "embedding"):
            m = Manifest(
                kind="resource",
                name="rt-test",
                version="1.0.0",
                description="Testing resource type",
                resource_type=rt,
            )
            errors = m.validate()
            assert not any("resource_type" in e for e in errors), f"resource_type {rt} should be valid"

    def test_valid_formats_accepted(self):
        for fmt in ("yaml", "json", "csv", "parquet", "binary", "directory"):
            m = Manifest(
                kind="resource",
                name="fmt-test",
                version="1.0.0",
                description="Testing format",
                resource_format=fmt,
            )
            errors = m.validate()
            assert not any("resource format" in e for e in errors), f"format {fmt} should be valid"

    def test_valid_size_hints_accepted(self):
        for sz in ("small", "medium", "large"):
            m = Manifest(
                kind="resource",
                name="sz-test",
                version="1.0.0",
                description="Testing size hint",
                size_hint=sz,
            )
            errors = m.validate()
            assert not any("size_hint" in e for e in errors), f"size_hint {sz} should be valid"

    def test_resource_fields_none_by_default(self):
        m = Manifest(kind="resource", name="defaults", version="1.0.0", description="Defaults")
        assert m.resource_type is None
        assert m.resource_format is None
        assert m.size_hint is None
        assert m.access is None
        assert m.compatibility is None

    def test_resource_validation_skips_for_non_resource(self):
        """Resource-specific validation should not fire for kind=skill."""
        m = Manifest(kind="skill", name="a-skill", version="1.0.0", description="")
        errors = m.validate()
        assert not any("resource_type" in e for e in errors)
        assert not any("resource format" in e for e in errors)
        assert not any("size_hint" in e for e in errors)
