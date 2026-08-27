"""Cleanup command and library function for removing test artifacts.

Detects and removes:
1. Test / mock registry entries (e.g. fingerprint starting with 'ffffffff', 'unknown' status,
   install paths pointing to temp directories or non-existent files).
2. Test / dummy package store directories in ~/.capacium/packages/ (e.g. dummy test metadata,
   empty stubs, packages with 'ffffffff' fingerprints).
3. Dead, dangling, or temporary framework symlinks.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..framework_detector import framework_skills_dirs
from ..registry import Registry
from ..utils.config import get_packages_dir


def is_test_fingerprint(fp: Optional[str]) -> bool:
    """Return True if fingerprint is a known test, dummy, or invalid fingerprint."""
    if not fp:
        return True
    cleaned = str(fp).strip().lower()
    if cleaned in ("", "unknown", "none", "null", "undefined", "deadbeef", "badfp"):
        return True
    if cleaned.startswith("ffffffff"):
        return True
    if len(cleaned) >= 8 and set(cleaned) <= {"f"}:
        return True
    return False


def is_temp_path(p: Optional[Path | str], packages_dir: Optional[Path] = None) -> bool:
    """Return True if path points to a temporary / test filesystem location."""
    if not p:
        return False
    try:
        path = Path(p)
        pkgs = (packages_dir or get_packages_dir())
        try:
            if path == pkgs or pkgs in path.parents or path.is_relative_to(pkgs):
                return False
        except Exception:
            pass
    except Exception:
        pass

    path_str = str(p)
    if "pytest-" in path_str or "tmp_home" in path_str or "fake_home" in path_str:
        return True
    system_temp = tempfile.gettempdir()
    if (
        path_str.startswith(system_temp)
        or path_str.startswith("/tmp")
        or path_str.startswith("/private/tmp")
        or path_str.startswith("/var/folders")
        or path_str.startswith("/private/var/folders")
    ):
        return True
    return False


def clean_test_artifacts(
    dry_run: bool = False,
    json_output: bool = False,
    registry: Optional[Registry] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Clean up test artifacts from registry, package store, and framework links.

    Returns a report dictionary with lists of removed items.
    """
    registry = registry or Registry()
    packages_dir = get_packages_dir()

    removed_registry_entries: List[str] = []
    removed_packages: List[str] = []
    removed_symlinks: List[str] = []

    # 1. Clean test entries from Registry
    for cap in registry.list_capabilities():
        is_test_entry = False

        if is_test_fingerprint(cap.fingerprint):
            is_test_entry = True
        elif is_temp_path(cap.install_path, packages_dir):
            is_test_entry = True
        elif cap.install_path and not Path(cap.install_path).exists():
            # Missing install path with test-like attributes or dummy owners
            if cap.owner in (
                "test",
                "test-owner",
                "acme",
                "alice",
                "bob",
                "newco",
                "orphan",
                "pruneme",
                "foo",
            ):
                is_test_entry = True
        elif not cap.installed_at or str(cap.installed_at).strip().lower() == "unknown":
            is_test_entry = True
        elif not cap.kind or str(cap.kind.value).strip().lower() == "unknown":
            is_test_entry = True

        if is_test_entry:
            cap_ref = f"{cap.owner}/{cap.name}@{cap.version}"
            removed_registry_entries.append(cap_ref)
            if not dry_run:
                registry.remove_capability(cap.id, cap.version)
                registry.remove_bundle_references(f"{cap.id}@{cap.version}")
                registry.remove_bundle_references(cap.id)
                registry.remove_signature(cap.owner, cap.name, cap.version, "default")

    # 2. Clean test packages in ~/.capacium/packages/
    packages_dir = get_packages_dir()
    if packages_dir.exists() and packages_dir.is_dir():
        for owner_dir in list(packages_dir.iterdir()):
            if not owner_dir.is_dir() or owner_dir.is_symlink():
                continue
            for name_dir in list(owner_dir.iterdir()):
                if not name_dir.is_dir() or name_dir.is_symlink():
                    continue
                for version_dir in list(name_dir.iterdir()):
                    if not version_dir.is_dir() or version_dir.is_symlink():
                        continue

                    is_test_pkg = False
                    meta_path = version_dir / ".cap-meta.json"
                    meta_path_alt = version_dir / ".capacium-meta.json"

                    target_meta = (
                        meta_path
                        if meta_path.exists()
                        else (meta_path_alt if meta_path_alt.exists() else None)
                    )
                    if target_meta:
                        try:
                            meta = json.loads(target_meta.read_text())
                            if is_test_fingerprint(meta.get("fingerprint")):
                                is_test_pkg = True
                            elif meta.get("kind") == "unknown" or meta.get("name") in (
                                "test-sub",
                                "bar",
                                "test-cap",
                            ):
                                if (
                                    not (version_dir / "capability.yaml").exists()
                                    and not (version_dir / "main.py").exists()
                                    and not (version_dir / "main.go").exists()
                                ):
                                    is_test_pkg = True
                        except (json.JSONDecodeError, OSError):
                            pass
                    else:
                        skill_md = version_dir / "SKILL.md"
                        if skill_md.exists():
                            try:
                                content = skill_md.read_text(errors="replace")
                                if content.strip() in (
                                    "---\nname: bar\n---",
                                    "---\nname: test\n---",
                                    "---\nname: custom-skill\n---",
                                ):
                                    is_test_pkg = True
                            except OSError:
                                pass
                        try:
                            if not any(version_dir.iterdir()):
                                is_test_pkg = True
                        except OSError:
                            pass

                    # Check if the package is under a known test-only owner and has no capability.yaml
                    if owner_dir.name in ("test-owner", "foo") and not (
                        version_dir / "capability.yaml"
                    ).exists():
                        is_test_pkg = True

                    if is_test_pkg:
                        removed_packages.append(str(version_dir))
                        if not dry_run:
                            shutil.rmtree(version_dir, ignore_errors=True)

                if not dry_run:
                    if name_dir.exists():
                        try:
                            if not any(name_dir.iterdir()):
                                shutil.rmtree(name_dir, ignore_errors=True)
                        except OSError:
                            pass
            if not dry_run:
                if owner_dir.exists():
                    try:
                        if not any(owner_dir.iterdir()):
                            shutil.rmtree(owner_dir, ignore_errors=True)
                    except OSError:
                        pass

    # 3. Clean test/broken framework symlinks
    for fw, skills_dir in framework_skills_dirs().items():
        if not skills_dir.exists() or not skills_dir.is_dir():
            continue
        try:
            items = list(skills_dir.iterdir())
        except OSError:
            continue
        for item in items:
            if item.is_symlink():
                try:
                    target = item.resolve()
                    if not target.exists():
                        removed_symlinks.append(str(item))
                        if not dry_run:
                            item.unlink(missing_ok=True)
                    elif is_temp_path(target, packages_dir):
                        removed_symlinks.append(str(item))
                        if not dry_run:
                            item.unlink(missing_ok=True)
                    elif str(target).startswith(str(packages_dir)) and any(
                        str(target).startswith(p) for p in removed_packages
                    ):
                        removed_symlinks.append(str(item))
                        if not dry_run:
                            item.unlink(missing_ok=True)
                except OSError:
                    removed_symlinks.append(str(item))
                    if not dry_run:
                        item.unlink(missing_ok=True)

    report = {
        "registry_entries_removed": removed_registry_entries,
        "packages_removed": removed_packages,
        "symlinks_removed": removed_symlinks,
        "dry_run": dry_run,
    }

    if json_output:
        print(json.dumps(report, indent=2))
    elif verbose:
        prefix = "Would clean" if dry_run else "Cleaned"
        total = (
            len(removed_registry_entries)
            + len(removed_packages)
            + len(removed_symlinks)
        )
        if total == 0:
            print("No test artifacts found.")
        else:
            print(f"{prefix} test artifacts ({total} item(s)):")
            if removed_registry_entries:
                print(f"  Registry entries ({len(removed_registry_entries)}):")
                for entry in removed_registry_entries:
                    print(f"    - {entry}")
            if removed_packages:
                print(f"  Packages ({len(removed_packages)}):")
                for pkg in removed_packages:
                    print(f"    - {pkg}")
            if removed_symlinks:
                print(f"  Symlinks ({len(removed_symlinks)}):")
                for symlink in removed_symlinks:
                    print(f"    - {symlink}")

    return report
