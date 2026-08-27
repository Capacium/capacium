from pathlib import Path


def _write_bundle(root: Path, *, members=("alpha", "beta"), name: str = "toolkit") -> Path:
    bundle_dir = root / f"{name}-source"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    capability_entries = []
    for member in members:
        member_dir = bundle_dir / "skills" / member
        member_dir.mkdir(parents=True, exist_ok=True)
        (member_dir / "capability.yaml").write_text(
            "\n".join(
                [
                    "kind: skill",
                    f"name: {member}",
                    "version: 1.0.0",
                    f"description: {member} fixture",
                    "frameworks:",
                    "- opencode",
                    "",
                ]
            )
        )
        (member_dir / "SKILL.md").write_text(f"# {member}\n" + (member * 256))
        capability_entries.extend(
            [
                f"- name: {member}",
                f"  source: ./skills/{member}",
                "  version: 1.0.0",
            ]
        )

    (bundle_dir / "capability.yaml").write_text(
        "\n".join(
            [
                "kind: bundle",
                f"name: {name}",
                "version: 1.0.0",
                "description: Bundle storage fixture",
                "frameworks:",
                "- opencode",
                "capabilities:",
                *capability_entries,
                "",
            ]
        )
    )
    return bundle_dir


def test_force_reinstalls_every_existing_bundle_member_and_updates_status(
    tmp_home, tmp_path, monkeypatch
):
    from capacium.commands.install import install_capability
    from capacium.registry import Registry

    bundle_dir = _write_bundle(tmp_path)
    calls = []

    class RecordingAdapter:
        def capability_exists(self, _name):
            return False

        def install_capability(self, name, version, source_dir, owner, kind):
            calls.append((name, version, Path(source_dir), owner, kind))
            return True

    adapter = RecordingAdapter()
    monkeypatch.setattr("capacium.adapters.get_adapter", lambda _framework: adapter)

    assert install_capability(
        "acme/toolkit@1.0.0",
        source_dir=bundle_dir,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
    )

    registry = Registry()
    for name in ("alpha", "beta"):
        registry.set_adapter_status(
            f"acme/{name}", "1.0.0", "opencode", "not-installed"
        )

    calls.clear()
    assert install_capability(
        "acme/toolkit@1.0.0",
        source_dir=bundle_dir,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
    )

    assert [name for name, *_rest in calls] == ["toolkit", "alpha", "beta"]
    for name in ("alpha", "beta"):
        statuses = registry.get_adapter_statuses(f"acme/{name}", "1.0.0")
        assert statuses["opencode"].status == "installed"


def test_bundle_members_share_physical_storage_and_client_links_resolve(
    tmp_home, tmp_path
):
    from capacium.commands.install import install_capability
    from capacium.registry import Registry
    from capacium.storage import StorageManager

    bundle_dir = _write_bundle(tmp_path)
    assert install_capability(
        "acme/toolkit@1.0.0",
        source_dir=bundle_dir,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
    )

    registry = Registry()
    bundle = registry.get_capability("acme/toolkit", "1.0.0")
    assert bundle is not None

    for name in ("alpha", "beta"):
        member = registry.get_capability(f"acme/{name}", "1.0.0")
        assert member is not None
        assert member.install_path.is_symlink()
        assert member.install_path.resolve() == (
            bundle.install_path / "skills" / name
        ).resolve()

        bundle_skill = bundle.install_path / "skills" / name / "SKILL.md"
        member_skill = member.install_path / "SKILL.md"
        assert member_skill.stat().st_ino == bundle_skill.stat().st_ino

        client_link = tmp_home / ".opencode" / "skills" / name
        assert client_link.is_symlink()
        assert client_link.resolve() == member.install_path.resolve()

    physical_bytes, _package_count = StorageManager().get_storage_usage()
    bundle_bytes = sum(
        path.stat().st_size
        for path in bundle.install_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    avoided_duplicate_bytes = sum(
        path.stat().st_size
        for name in ("alpha", "beta")
        for path in (bundle.install_path / "skills" / name).rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    assert physical_bytes == bundle_bytes
    assert avoided_duplicate_bytes > 0
    print(
        "bundle-storage-fixture: "
        f"physical={physical_bytes}B avoided_duplicate={avoided_duplicate_bytes}B"
    )


def test_removing_bundle_cleans_shared_member_references(tmp_home, tmp_path):
    from capacium.commands.install import install_capability
    from capacium.commands.remove import remove_capability
    from capacium.registry import Registry

    bundle_dir = _write_bundle(tmp_path)
    assert install_capability(
        "acme/toolkit@1.0.0",
        source_dir=bundle_dir,
        no_lock=True,
        skip_runtime_check=True,
        force=True,
        yes=True,
    )

    registry = Registry()
    bundle = registry.get_capability("acme/toolkit", "1.0.0")
    member_paths = [
        registry.get_capability(f"acme/{name}", "1.0.0").install_path
        for name in ("alpha", "beta")
    ]

    assert remove_capability("acme/toolkit@1.0.0")
    assert not bundle.install_path.exists()
    for member_path in member_paths:
        assert not member_path.exists()
        assert not member_path.is_symlink()
        assert not any(member_path.parent.glob("1.0.0.removing*"))


def test_shared_member_fingerprint_is_included_for_verify(tmp_home, tmp_path):
    """P6-007: a bundle whose member is already owned by another bundle must
    still include that member's fingerprint in its stored hash, so 'cap verify'
    recomputes the same value instead of reporting a false TAMPERED."""
    from capacium.commands.install import install_capability
    from capacium.commands.verify import _verify_bundle
    from capacium.registry import Registry

    bundle_a = _write_bundle(tmp_path / "a", members=("alpha", "beta"), name="toolkit-a")
    bundle_b = _write_bundle(tmp_path / "b", members=("alpha", "gamma"), name="toolkit-b")

    assert install_capability(
        "acme/toolkit-a@1.0.0",
        source_dir=bundle_a,
        no_lock=True,
        skip_runtime_check=True,
        yes=True,
    )

    registry = Registry()
    bundle_b_install = install_capability(
        "acme/toolkit-b@1.0.0",
        source_dir=bundle_b,
        no_lock=True,
        skip_runtime_check=True,
        yes=True,
    )
    assert bundle_b_install is True

    # alpha is shared between both bundles, not stolen from the first.
    assert registry.get_reference_count("acme/alpha@1.0.0") == 2

    # The stored fingerprint and the live recomputation must agree for BOTH
    # bundles (a single shared install must not make either report TAMPERED).
    for bundle_name in ("toolkit-a", "toolkit-b"):
        bundle = registry.get_capability(f"acme/{bundle_name}", "1.0.0")
        assert bundle is not None, bundle_name
        assert _verify_bundle(bundle, registry) is True, bundle_name
