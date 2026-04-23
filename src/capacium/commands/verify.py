from pathlib import Path
from typing import Optional
from ..registry import Registry
from ..fingerprint import compute_fingerprint


def verify_capability(cap_spec: Optional[str] = None, verify_all: bool = False) -> bool:
    registry = Registry()

    if verify_all:
        capabilities = registry.list_capabilities()
        if not capabilities:
            print("No capabilities installed.")
            return True

        all_ok = True
        for cap in capabilities:
            ok = _verify_single(cap.id, registry)
            if not ok:
                all_ok = False
        return all_ok

    elif cap_spec:
        return _verify_single(cap_spec, registry)

    else:
        print("Error: specify a capability or --all")
        return False


def _verify_single(cap_spec: str, registry: Registry) -> bool:
    cap = registry.get_capability(cap_spec)
    if cap is None:
        print(f"Capability {cap_spec} not found.")
        return False

    if not cap.install_path or not cap.install_path.exists():
        print(f"ERROR: Install path for {cap_spec} does not exist: {cap.install_path}")
        return False

    actual = compute_fingerprint(cap.install_path, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json"])
    if actual == cap.fingerprint:
        print(f"VERIFIED: {cap.id}@{cap.version}")
        return True
    else:
        print(f"TAMPERED: {cap.id}@{cap.version}")
        print(f"  expected: {cap.fingerprint}")
        print(f"  actual:   {actual}")
        return False
