

class TestSpecOnlyKinds:
    """Verify spec-only kinds (operator, checkpoint, policy) fail with clear errors."""

    def test_operator_kind_rejected(self, tmp_home, tmp_path, capsys):
        """kind: operator → explicit unsupported-kind error, no package copy."""
        source_dir = tmp_path / "operator-cap"
        source_dir.mkdir()
        (source_dir / "capability.yaml").write_text("""\
kind: operator
name: operator-cap
version: 1.0.0
description: A test operator capability
""")

        from capacium.commands.install import install_capability
        result = install_capability(
            "test/operator-cap@1.0.0",
            source_dir=source_dir,
            force=True,
            yes=True,
            no_lock=True,
            skip_runtime_check=True,
        )

        assert result is False
        out = capsys.readouterr().out
        assert "unsupported" in out.lower()
        assert "operator" in out

        packages_dir = tmp_home / ".capacium" / "packages"
        operator_pkg = packages_dir / "test" / "operator-cap"
        assert not operator_pkg.exists()

    def test_checkpoint_kind_rejected(self, tmp_home, tmp_path, capsys):
        """kind: checkpoint → explicit unsupported-kind error, no package copy."""
        source_dir = tmp_path / "checkpoint-cap"
        source_dir.mkdir()
        (source_dir / "capability.yaml").write_text("""\
kind: checkpoint
name: checkpoint-cap
version: 1.0.0
description: A test checkpoint capability
""")

        from capacium.commands.install import install_capability
        result = install_capability(
            "test/checkpoint-cap@1.0.0",
            source_dir=source_dir,
            force=True,
            yes=True,
            no_lock=True,
            skip_runtime_check=True,
        )

        assert result is False
        out = capsys.readouterr().out
        assert "unsupported" in out.lower()
        assert "checkpoint" in out

        packages_dir = tmp_home / ".capacium" / "packages"
        checkpoint_pkg = packages_dir / "test" / "checkpoint-cap"
        assert not checkpoint_pkg.exists()

    def test_policy_kind_rejected(self, tmp_home, tmp_path, capsys):
        """kind: policy → explicit unsupported-kind error, no package copy."""
        source_dir = tmp_path / "policy-cap"
        source_dir.mkdir()
        (source_dir / "capability.yaml").write_text("""\
kind: policy
name: policy-cap
version: 1.0.0
description: A test policy capability
""")

        from capacium.commands.install import install_capability
        result = install_capability(
            "test/policy-cap@1.0.0",
            source_dir=source_dir,
            force=True,
            yes=True,
            no_lock=True,
            skip_runtime_check=True,
        )

        assert result is False
        out = capsys.readouterr().out
        assert "unsupported" in out.lower()
        assert "policy" in out

        packages_dir = tmp_home / ".capacium" / "packages"
        policy_pkg = packages_dir / "test" / "policy-cap"
        assert not policy_pkg.exists()

    def test_unsupported_kind_error_message_is_actionable(self, tmp_home, tmp_path, capsys):
        """Error message tells user which kind is unsupported and what is supported."""
        source_dir = tmp_path / "operator-cap"
        source_dir.mkdir()
        (source_dir / "capability.yaml").write_text("""\
kind: operator
name: operator-cap
version: 1.0.0
description: A test operator capability
""")

        from capacium.commands.install import install_capability
        result = install_capability(
            "test/operator-cap@1.0.0",
            source_dir=source_dir,
            force=True,
            yes=True,
            no_lock=True,
            skip_runtime_check=True,
        )

        assert result is False
        out = capsys.readouterr().out
        assert "operator" in out
        for expected_kind in (
            "skill", "bundle", "tool", "prompt", "template",
            "workflow", "mcp-server", "connector-pack", "resource",
        ):
            assert expected_kind in out, f"expected '{expected_kind}' in error output"

    def test_no_registry_entry_written_on_unsupported_kind(self, tmp_home, tmp_path, capsys):
        """Neither registry entry nor client config is written for unsupported kind."""
        source_dir = tmp_path / "operator-cap"
        source_dir.mkdir()
        (source_dir / "capability.yaml").write_text("""\
kind: operator
name: operator-cap
version: 1.0.0
description: A test operator capability
""")

        from capacium.commands.install import install_capability
        result = install_capability(
            "test/operator-cap@1.0.0",
            source_dir=source_dir,
            force=True,
            yes=True,
            no_lock=True,
            skip_runtime_check=True,
        )

        assert result is False

        from capacium.registry import Registry
        registry = Registry()
        cap = registry.get_capability("test/operator-cap", "1.0.0")
        assert cap is None

        packages_dir = tmp_home / ".capacium" / "packages"
        operator_pkg = packages_dir / "test" / "operator-cap" / "1.0.0"
        assert not operator_pkg.exists()

    def test_validate_manifest_rejects_spec_only_kinds(self, tmp_path):
        """Manifest validation catches spec-only kinds before install."""
        manifest_yaml = tmp_path / "capability.yaml"
        manifest_yaml.write_text("""\
kind: operator
name: operator-cap
version: 1.0.0
description: A test operator capability
""")

        from capacium.manifest import Manifest
        manifest = Manifest.load(manifest_yaml)
        errors = manifest.validate()
        assert len(errors) >= 1
        assert any("unsupported" in e.lower() for e in errors)
        assert any("operator" in e for e in errors)
