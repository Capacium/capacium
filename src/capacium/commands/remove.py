import shutil
from ..storage import StorageManager
from ..registry import Registry
from ..versioning import VersionManager
from ..adapters import get_adapter
from ._resolve import resolve_cap_id


def remove_capability(cap_spec: str, force: bool = False) -> bool:
    cap_id = resolve_cap_id(cap_spec)
    spec = VersionManager.parse_version_spec(cap_id)
    owner = spec["owner"]
    cap_name = spec["skill"]
    version_spec = spec["version"]

    bare_id = f"{owner}/{cap_name}"

    registry = Registry()
    storage = StorageManager()

    if version_spec in ["latest", "stable"]:
        cap = registry.get_capability(cap_id)
        if cap is None:
            print(f"Capability {bare_id} not found.")
            return False
        version = cap.version
    else:
        version = version_spec
        cap = registry.get_capability(bare_id, version)

    if cap is None:
        print(f"Capability {bare_id}@{version} not found.")
        return False

    _remove_sub_capabilities(cap, registry, force)

    frameworks = cap.frameworks if cap.frameworks else [cap.framework or "opencode"]
    for fw_name in frameworks:
        try:
            adapter = get_adapter(fw_name)
        except ValueError:
            continue
        adapter.remove_capability(
            cap_name, owner=owner, kind=cap.kind.value if cap.kind else "skill"
        )

    removed = registry.remove_capability(bare_id, version)
    if not removed:
        print(f"Capability {bare_id}@{version} not found in registry.")
        return False

    package_dir = storage.get_package_dir(cap_name, version, owner=owner)
    if package_dir.exists():
        shutil.rmtree(package_dir)

    if force:
        _purge_all_adapter_symlinks(cap_name)

    print(f"Removed {bare_id}@{version}")
    return True


def _purge_all_adapter_symlinks(cap_name: str) -> None:
    from pathlib import Path

    common_skill_paths = [
        Path.home() / ".opencode" / "skills",
        Path.home() / ".config" / "opencode" / "commands",
        Path.home() / ".opencode" / "mcp",
        Path.home() / ".claude" / "skills",
        Path.home() / ".claude" / "commands",
        Path.home() / ".gemini" / "skills",
        Path.home() / ".gemini" / "commands",
        Path.home() / ".gemini" / "config" / "skills",
        Path.home() / ".gemini" / "antigravity" / "skills",
        Path.home() / ".gemini" / "antigravity" / "commands",
        Path.home() / ".cursor" / "skills",
        Path.home() / ".cursor" / "commands",
        Path.home() / ".continue" / "skills",
        Path.home() / ".continue" / "commands",
        Path.home() / ".codex" / "skills",
        Path.home() / ".codex" / "commands",
        Path.home() / ".qwen" / "skills",
        Path.home() / ".qwen" / "commands",
        Path.home() / ".agents" / "skills",
        Path.home() / ".agents" / "commands",
    ]
    cache_root = Path.home() / ".capacium" / "packages"

    for parent_dir in common_skill_paths:
        link = parent_dir / cap_name
        if link.is_symlink():
            target = Path(link).resolve()
            if not target.exists() or str(target).startswith(str(cache_root)):
                link.unlink(missing_ok=True)
        elif link.is_dir():
            if not any(link.iterdir()):
                shutil.rmtree(link, ignore_errors=True)
        elif link.exists():
            link.unlink(missing_ok=True)

        command_link = parent_dir / f"{cap_name}.md"
        if command_link.is_symlink():
            target = Path(command_link).resolve()
            if not target.exists() or str(target).startswith(str(cache_root)):
                command_link.unlink(missing_ok=True)
        elif command_link.exists():
            command_link.unlink(missing_ok=True)

        # Owner-Prefix symlinks: skills/<owner>/<cap_name>
        for item in list(parent_dir.iterdir()):
            if not item.is_dir():
                continue
            owner_link = item / cap_name
            if owner_link.is_symlink():
                target = Path(owner_link).resolve()
                if not target.exists() or str(target).startswith(str(cache_root)):
                    owner_link.unlink(missing_ok=True)
            owner_cmd_link = item / f"{cap_name}.md"
            if owner_cmd_link.is_symlink():
                target = Path(owner_cmd_link).resolve()
                if not target.exists() or str(target).startswith(str(cache_root)):
                    owner_cmd_link.unlink(missing_ok=True)

    # Config-backed frameworks (TOML / JSON)
    for fw_name in ("claude-desktop", "codex", "antigravity", "gemini-cli"):
        try:
            adapter = get_adapter(fw_name)
        except ValueError:
            continue
        if adapter.capability_exists(cap_name):
            adapter.remove_capability(cap_name, kind="mcp-server")


def _remove_sub_capabilities(cap, registry: Registry, force: bool = False) -> None:
    bundle_id = f"{cap.owner}/{cap.name}@{cap.version}"
    member_ids = registry.get_bundle_members(bundle_id)

    if not member_ids:
        return

    for member_id in list(member_ids):
        ref_count = registry.get_reference_count(member_id)
        if ref_count > 1 and not force:
            print(f"  Preserving {member_id} (used by {ref_count} bundle(s))")
            continue

        parts = member_id.split("@", 1)
        member_cap_id = parts[0]
        member_version = parts[1] if len(parts) > 1 else None

        member_cap = registry.get_capability(member_cap_id, member_version)

        if member_cap is None and not force:
            continue

        if member_cap is not None:
            _remove_sub_capabilities(member_cap, registry, force)

        owner_name = member_cap_id.split("/", 1)
        m_owner = owner_name[0] if len(owner_name) > 1 else "global"
        m_name = owner_name[-1]

        frameworks = member_cap.frameworks if (member_cap and member_cap.frameworks) else [member_cap.framework if member_cap else "opencode"]
        for fw_name in frameworks:
            try:
                adapter = get_adapter(fw_name)
            except ValueError:
                continue
            adapter.remove_capability(
                m_name,
                owner=m_owner,
                kind=member_cap.kind.value if member_cap and member_cap.kind else "skill",
            )

        if member_cap is not None:
            registry.remove_capability(member_cap_id, member_version)

        storage = StorageManager()
        if member_version:
            pkg_dir = storage.get_package_dir(m_name, member_version, owner=m_owner)
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir)

        if force and member_cap is None:
            alt_pkg_dir = storage.get_package_dir(
                m_name, member_version or "latest", owner="global"
            )
            if alt_pkg_dir.exists():
                shutil.rmtree(alt_pkg_dir)
            _purge_all_adapter_symlinks(m_name)

        print(f"  Removed sub-capability {member_id}")

    registry.remove_bundle_members(bundle_id)
