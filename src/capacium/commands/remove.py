import shutil
from pathlib import Path
from typing import List

from ..storage import StorageManager
from ..registry import Registry
from ..versioning import VersionManager
from ..adapters import get_adapter
from ._resolve import resolve_cap_id


class _RemovalSnapshot:
    """Rollback journal for transactional removes (V14/STAB-002).

    Records the pre-remove state of every write surface (client config
    files, skills-dir links, package trees, registry rows) before any
    mutation. ``restore()`` puts everything back; ``commit()`` purges the
    parked package trees once all steps succeeded.
    """

    def __init__(self, registry: Registry):
        self._registry = registry
        self._files: dict = {}        # Path -> bytes | None (absent)
        self._links: dict = {}        # Path -> link target str | None (absent)
        self._moves: List[tuple] = [] # (original Path, parked Path)
        self._rows: List = []         # Capability objects removed from registry
        self._members: List[tuple] = []  # (bundle_id, [member_id, ...])

    # ── recording ──────────────────────────────────────────────────────
    def record_file(self, path: Path) -> None:
        path = Path(path)
        if path in self._files:
            return
        try:
            self._files[path] = path.read_bytes() if path.is_file() else None
        except OSError:
            self._files[path] = None

    def record_link(self, path: Path) -> None:
        path = Path(path)
        if path in self._links:
            return
        import os
        if path.is_symlink():
            self._links[path] = os.readlink(path)
        else:
            self._links[path] = None

    def record_registry_row(self, cap) -> None:
        self._rows.append(cap)

    def record_bundle_members(self, bundle_id: str, member_ids: List[str]) -> None:
        self._members.append((bundle_id, list(member_ids)))

    def park_tree(self, path: Path) -> None:
        """Move a package tree aside instead of deleting it outright."""
        path = Path(path)
        if not path.exists():
            return
        parked = path.with_name(path.name + ".removing")
        idx = 0
        while parked.exists():
            idx += 1
            parked = path.with_name(f"{path.name}.removing{idx}")
        path.rename(parked)
        self._moves.append((path, parked))

    # ── outcome ────────────────────────────────────────────────────────
    def restore(self) -> None:
        for original, parked in reversed(self._moves):
            if parked.exists() and not original.exists():
                parked.rename(original)
        for path, content in self._files.items():
            try:
                if content is None:
                    if path.is_file():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            except OSError:
                pass
        for path, target in self._links.items():
            try:
                if target is None:
                    if path.is_symlink():
                        path.unlink()
                elif not path.is_symlink() and not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(target)
            except OSError:
                pass
        for cap in self._rows:
            try:
                if not self._registry.add_capability(cap):
                    self._registry.update_capability(cap)
            except Exception:
                pass
        for bundle_id, member_ids in self._members:
            for member_id in member_ids:
                try:
                    self._registry.add_bundle_member(bundle_id, member_id)
                except Exception:
                    pass

    def commit(self) -> None:
        for _original, parked in self._moves:
            shutil.rmtree(parked, ignore_errors=True)


def _snapshot_cap_surfaces(snapshot: _RemovalSnapshot, cap_name: str,
                           frameworks: List[str]) -> None:
    """Record client config files and skills-dir links a remove may touch."""
    config_backed = set(frameworks) | {"claude-desktop", "codex", "gemini-cli",
                                       "antigravity", "opencode"}
    for fw_name in config_backed:
        try:
            adapter = get_adapter(fw_name)
        except Exception:
            continue
        config_path = getattr(adapter, "config_path", None)
        if config_path is not None:
            snapshot.record_file(Path(config_path))

    for parent_dir in _known_skill_paths():
        snapshot.record_link(parent_dir / cap_name)
        snapshot.record_link(parent_dir / f"{cap_name}.md")
        if parent_dir.is_dir():
            for item in parent_dir.iterdir():
                if item.is_dir() and not item.is_symlink():
                    snapshot.record_link(item / cap_name)
                    snapshot.record_link(item / f"{cap_name}.md")


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

    # Transactional remove (V14/STAB-002): snapshot every write surface
    # first, run all adapter steps, park the package tree, and only then
    # touch the registry. Any failure restores the full pre-remove state.
    snapshot = _RemovalSnapshot(registry)
    _snapshot_cap_surfaces(snapshot, cap_name, list(cap.frameworks or []))

    try:
        _remove_sub_capabilities(cap, registry, force, snapshot=snapshot)

        frameworks = cap.frameworks if cap.frameworks else [cap.framework or "opencode"]
        for fw_name in frameworks:
            try:
                adapter = get_adapter(fw_name)
            except ValueError:
                continue
            adapter.remove_capability(
                cap_name, owner=owner, kind=cap.kind.value if cap.kind else "skill"
            )

        package_dir = storage.get_package_dir(cap_name, version, owner=owner)
        snapshot.park_tree(package_dir)

        # Registry change only after all adapter + filesystem steps succeeded.
        snapshot.record_registry_row(cap)
        removed = registry.remove_capability(bare_id, version)
        if not removed:
            raise RuntimeError(f"registry row for {bare_id}@{version} vanished mid-remove")

        if force:
            _purge_all_adapter_symlinks(cap_name)
    except Exception as exc:
        snapshot.restore()
        print(f"Remove of {bare_id}@{version} failed: {exc}")
        print("  All changes rolled back — state restored.")
        return False

    snapshot.commit()
    print(f"Removed {bare_id}@{version}")
    return True


def _known_skill_paths() -> List[Path]:
    """Skills/command directories any adapter may have written links into."""
    return [
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


def _purge_all_adapter_symlinks(cap_name: str) -> None:
    cache_root = Path.home() / ".capacium" / "packages"

    for parent_dir in _known_skill_paths():
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
        # Missing client dirs are normal (V14, 2026-06-11): not every machine
        # has every framework — never crash on absent paths.
        if not parent_dir.is_dir():
            continue
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


def _remove_sub_capabilities(
    cap,
    registry: Registry,
    force: bool = False,
    snapshot: _RemovalSnapshot = None,
) -> None:
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

        owner_name = member_cap_id.split("/", 1)
        m_owner = owner_name[0] if len(owner_name) > 1 else "global"
        m_name = owner_name[-1]

        if snapshot is not None:
            _snapshot_cap_surfaces(
                snapshot, m_name,
                list(member_cap.frameworks or []) if member_cap else [],
            )

        if member_cap is not None:
            _remove_sub_capabilities(member_cap, registry, force, snapshot=snapshot)

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
            if snapshot is not None:
                snapshot.record_registry_row(member_cap)
            registry.remove_capability(member_cap_id, member_version)

        storage = StorageManager()
        if member_version:
            pkg_dir = storage.get_package_dir(m_name, member_version, owner=m_owner)
            if snapshot is not None:
                snapshot.park_tree(pkg_dir)
            elif pkg_dir.exists():
                shutil.rmtree(pkg_dir)

        if force and member_cap is None:
            alt_pkg_dir = storage.get_package_dir(
                m_name, member_version or "latest", owner="global"
            )
            if snapshot is not None:
                snapshot.park_tree(alt_pkg_dir)
            elif alt_pkg_dir.exists():
                shutil.rmtree(alt_pkg_dir)
            _purge_all_adapter_symlinks(m_name)

        print(f"  Removed sub-capability {member_id}")

    if snapshot is not None:
        snapshot.record_bundle_members(bundle_id, member_ids)
    registry.remove_bundle_members(bundle_id)
