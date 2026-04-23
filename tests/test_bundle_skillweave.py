
from capacium.manifest import Manifest
from capacium.fingerprint import compute_bundle_fingerprint


SKILLWEAVE_BUNDLE_YAML = """\
kind: bundle
name: skillweave
version: 0.5.0
description: SkillWeave - multi-agent orchestration system for AI agent workflows
author: Capacium Team
license: MIT
frameworks:
  - opencode
  - claude-code
  - gemini-cli

capabilities:
  - name: skillweave-core
    source: ./skills/skillweave-core
  - name: skillweave-blueprint
    source: ./skills/skillweave-blueprint
  - name: skillweave-promptchain
    source: ./skills/skillweave-promptchain

dependencies:
  pyyaml: ">=6.0"
  jsonschema: ">=4.0"
"""


class TestSkillWeaveBundleManifest:

    def test_parses_from_yaml_string(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        assert data.name == "skillweave"
        assert data.version == "0.5.0"
        assert data.kind == "bundle"

    def test_kind_is_bundle(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        assert data.kind == "bundle"

    def test_capabilities_section_has_entries(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        assert len(data.capabilities) == 3

    def test_capability_names(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        names = [c["name"] for c in data.capabilities]
        assert "skillweave-core" in names
        assert "skillweave-blueprint" in names
        assert "skillweave-promptchain" in names

    def test_capability_sources(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        sources = [c["source"] for c in data.capabilities]
        assert "./skills/skillweave-core" in sources
        assert "./skills/skillweave-blueprint" in sources
        assert "./skills/skillweave-promptchain" in sources

    def test_frameworks_include_all_three(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        assert "opencode" in data.frameworks
        assert "claude-code" in data.frameworks
        assert "gemini-cli" in data.frameworks

    def test_bundle_validation_passes(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        errors = data.validate()
        assert errors == []

    def test_parses_from_file(self, tmp_path):
        cap_dir = tmp_path / "skillweave"
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text(SKILLWEAVE_BUNDLE_YAML)
        manifest = Manifest.detect_from_directory(cap_dir)
        assert manifest.kind == "bundle"
        assert manifest.name == "skillweave"
        assert manifest.version == "0.5.0"
        assert len(manifest.capabilities) == 3

    def test_metadata_fields(self):
        data = Manifest.loads(SKILLWEAVE_BUNDLE_YAML)
        assert data.author == "Capacium Team"
        assert data.description == "SkillWeave - multi-agent orchestration system for AI agent workflows"
        assert data.license == "MIT"


class TestSkillWeaveBundleFingerprint:

    def test_bundle_fingerprint_with_three_sub_caps(self):
        sub_fps = ["a" * 64, "b" * 64, "c" * 64]
        fp = compute_bundle_fingerprint(sub_fps)
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_bundle_fingerprint_deterministic(self):
        sub_fps = ["corefingerprint", "blueprintfingerprint", "promptchainfingerprint"]
        fp1 = compute_bundle_fingerprint(sub_fps)
        fp2 = compute_bundle_fingerprint(sub_fps)
        assert fp1 == fp2

    def test_bundle_fingerprint_order_independent(self):
        fps1 = ["fp-core", "fp-blueprint", "fp-promptchain"]
        fps2 = ["fp-promptchain", "fp-blueprint", "fp-core"]
        assert compute_bundle_fingerprint(fps1) == compute_bundle_fingerprint(fps2)

    def test_bundle_fingerprint_different_for_different_inputs(self):
        fp1 = compute_bundle_fingerprint(["core-a", "blueprint-b", "promptchain-c"])
        fp2 = compute_bundle_fingerprint(["core-x", "blueprint-b", "promptchain-c"])
        assert fp1 != fp2

    def test_bundle_fingerprint_empty_list(self):
        fp = compute_bundle_fingerprint([])
        assert isinstance(fp, str)
        assert len(fp) == 64
