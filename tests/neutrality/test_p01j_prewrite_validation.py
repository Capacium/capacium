"""CAPR3-P01J-C: Prove zero storage/filesystem/adapter/registry writes for
invalid/missing Kind manifests in _install_single_sub_cap.

Also verifies _remove_sub_capabilities validates Kind before adapter dispatch.
"""

from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from capacium.manifest import Manifest
from capacium.models import Capability, Kind


# ── Helpers ────────────────────────────────────────────────────────────────


def _valid_manifest(kind="skill", **overrides):
    defaults = {
        "kind": kind,
        "name": "test-sub",
        "version": "1.0.0",
        "owner": "test-owner",
    }
    defaults.update(overrides)
    return Manifest.from_dict(defaults)


def _make_patched_call(kind=None, name="test-sub", version="1.0.0",
                       owner="test-owner", source_path="/fake/src/test-sub",
                       manifest_errors=None, package_dir=None):
    """Patch _install_single_sub_cap dependencies and test invocation.

    Every effectful surface is patched: manifest detection, framework
    resolution, adapter resolution, storage, registry, and the filesystem copy.

    CAPR3-P01K-D — `get_adapter` in particular must be patched. Without it the
    real OpenCode adapter runs and resolves the operator's actual
    ``~/.capacium/packages`` tree, which is how the P01J success-path test
    created and rewrote ``test-owner/test-sub/1.0.0`` on the operator's machine.
    """
    from capacium.commands.install import _install_single_sub_cap

    manifest = _valid_manifest(kind=kind) if kind is not None else Manifest(kind="", name=name)
    if manifest_errors is not None:
        manifest.validate = Mock(return_value=manifest_errors)

    mock_storage = MagicMock()
    if package_dir is not None:
        # Materialise the isolated package directory so any real metadata
        # write lands under tmp_path instead of a mocked-away path.
        package_dir.mkdir(parents=True, exist_ok=True)
        mock_storage.get_package_path.return_value = package_dir
        mock_storage.create_package_reference.return_value = package_dir
    mock_registry = MagicMock()
    mock_adapter = MagicMock()

    with (
        patch("capacium.commands.install.Manifest.detect_from_directory",
              return_value=manifest),
        patch("capacium.commands.install.resolve_frameworks",
              return_value=["opencode"]),
        patch("capacium.adapters.get_adapter", return_value=mock_adapter),
        patch("capacium.commands.install.compute_fingerprint",
              return_value="deadbeef"),
        patch("capacium.commands.install._detect_git_remote", return_value=""),
        patch("capacium.commands.install.shutil.copytree") as mock_copytree,
    ):
        try:
            _install_single_sub_cap(
                sub_name=name,
                version=version,
                source_path=Path(source_path),
                owner=owner,
                registry=mock_registry,
                storage=mock_storage,
                no_lock=False,
            )
        except (ValueError, SystemExit) as exc:
            return exc, mock_storage, mock_registry, mock_copytree
        return None, mock_storage, mock_registry, mock_copytree


# ── Pre-write validation: install path ─────────────────────────────────────


def test_missing_kind_raises_before_any_storage_write():
    """Missing Kind manifest raises ValueError before any storage/filesystem op."""
    exc, storage, registry, copytree = _make_patched_call(kind="")

    assert exc is not None
    assert isinstance(exc, ValueError)
    assert "no 'kind' field" in str(exc)

    storage.create_package_reference.assert_not_called()
    storage.get_package_path.assert_not_called()
    copytree.assert_not_called()
    registry.add_capability.assert_not_called()
    registry.update_capability.assert_not_called()


def test_unknown_kind_raises_before_any_storage_write():
    """Unknown Kind manifest raises ValueError before any storage/filesystem op."""
    exc, storage, registry, copytree = _make_patched_call(kind="nonexistent-kind-xyz")

    assert exc is not None
    assert isinstance(exc, ValueError)
    assert "Unknown kind" in str(exc)

    storage.create_package_reference.assert_not_called()
    storage.get_package_path.assert_not_called()
    copytree.assert_not_called()
    registry.add_capability.assert_not_called()
    registry.update_capability.assert_not_called()


def test_legacy_kind_raises_before_any_storage_write():
    """Legacy Kind (operator) raises ValueError before any storage/filesystem op."""
    exc, storage, registry, copytree = _make_patched_call(kind="operator")

    assert exc is not None
    assert isinstance(exc, ValueError)
    assert "legacy" in str(exc).lower() or "operator" in str(exc).lower()

    storage.create_package_reference.assert_not_called()
    storage.get_package_path.assert_not_called()
    copytree.assert_not_called()
    registry.add_capability.assert_not_called()
    registry.update_capability.assert_not_called()


def test_valid_kind_with_blocking_manifest_errors_raises_before_write():
    """Valid Kind but validate() returns errors (e.g. bundle without capabilities)
    raises ValueError before any storage/filesystem op."""
    errors = ["Bundle manifest must define at least one capability in the 'capabilities' section"]
    exc, storage, registry, copytree = _make_patched_call(
        kind="bundle", manifest_errors=errors
    )

    assert exc is not None
    assert isinstance(exc, ValueError)
    assert "validation failed before write" in str(exc)

    storage.create_package_reference.assert_not_called()
    storage.get_package_path.assert_not_called()
    copytree.assert_not_called()
    registry.add_capability.assert_not_called()
    registry.update_capability.assert_not_called()


def test_malformed_manifest_empty_kind_caught_before_write():
    """A manifest whose detect_from_directory returns kind='' raises ValueError
    before any storage/filesystem op."""
    exc, storage, registry, copytree = _make_patched_call(kind="")

    assert exc is not None
    assert isinstance(exc, ValueError)
    assert "no 'kind' field" in str(exc)

    storage.create_package_reference.assert_not_called()
    storage.get_package_path.assert_not_called()
    copytree.assert_not_called()
    registry.add_capability.assert_not_called()
    registry.update_capability.assert_not_called()


def test_valid_manifest_proceeds_to_storage_and_registry_write(tmp_path):
    """A valid manifest passes all pre-write checks and proceeds to storage +
    registry writes.

    Runs fully isolated: the package directory is under ``tmp_path`` and every
    write surface — including adapter resolution — is mocked, so the success
    path can be proven without touching the operator's real package home.
    """
    package_dir = tmp_path / "packages" / "test-owner" / "test-sub" / "1.0.0"
    exc, storage, registry, copytree = _make_patched_call(
        kind="skill",
        source_path=str(tmp_path / "src" / "test-sub"),
        package_dir=package_dir,
    )

    assert exc is None, f"Unexpected exception: {exc}"

    copytree.assert_called()
    registry.add_capability.assert_called()

    # The success path must stay inside the isolated root.
    copied_to = Path(copytree.call_args.args[1])
    assert tmp_path in copied_to.parents or copied_to == package_dir


# ── Pre-write validation: remove path ──────────────────────────────────────


def test_remove_sub_capabilities_validates_kind_before_adapter_removal():
    """_remove_sub_capabilities calls validate_kind before any
    adapter.remove_capability dispatch."""
    from capacium.commands.remove import _remove_sub_capabilities

    sub_cap = Capability(
        owner="test-owner",
        name="sub-skill",
        version="1.0.0",
        kind=Kind.SKILL,
        fingerprint="abc123",
        install_path=Path("/fake/path"),
        frameworks=["opencode"],
    )

    mock_registry = MagicMock()
    mock_registry.get_bundle_members.return_value = ["test-owner/sub-skill@1.0.0"]
    mock_registry.get_reference_count.return_value = 1
    mock_registry.get_capability.return_value = sub_cap

    with (
        patch("capacium.commands.remove.validate_kind") as mock_validate_kind,
        patch("capacium.commands.remove.get_adapter") as mock_get_adapter,
        patch("capacium.commands.remove.StorageManager") as mock_storage_cls,
        patch("capacium.commands.remove._snapshot_cap_surfaces"),
        patch("capacium.commands.remove._remove_sub_capabilities") as mock_recurse,
        patch("capacium.commands.remove.shutil.rmtree"),
    ):
        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter
        mock_storage = MagicMock()
        mock_storage.get_package_dir.return_value = Path("/tmp/nonexistent/path")
        mock_storage_cls.return_value = mock_storage

        _remove_sub_capabilities(sub_cap, mock_registry)

        mock_validate_kind.assert_called_with("skill")
        mock_adapter.remove_capability.assert_called_once()


def test_remove_sub_capabilities_invalid_kind_raises_before_removal():
    """Sub-cap with unknown kind raises ValueError BEFORE adapter.remove_capability."""
    from capacium.commands.remove import _remove_sub_capabilities

    sub_cap = Capability(
        owner="test-owner",
        name="sub-skill",
        version="1.0.0",
        kind=Kind("skill"),
        fingerprint="abc123",
        install_path=Path("/fake/path"),
        frameworks=["opencode"],
    )
    sub_cap.kind = MagicMock()
    sub_cap.kind.value = "unknown"

    mock_registry = MagicMock()
    mock_registry.get_bundle_members.return_value = ["test-owner/sub-skill@1.0.0"]
    mock_registry.get_reference_count.return_value = 1
    mock_registry.get_capability.return_value = sub_cap

    with (
        patch("capacium.commands.remove.get_adapter") as mock_get_adapter,
        patch("capacium.commands.remove._snapshot_cap_surfaces"),
        patch("capacium.commands.remove._remove_sub_capabilities") as mock_recurse,
    ):
        mock_adapter = MagicMock()
        mock_get_adapter.return_value = mock_adapter

        with pytest.raises(ValueError, match="invalid Kind"):
            _remove_sub_capabilities(sub_cap, mock_registry)

        mock_adapter.remove_capability.assert_not_called()
