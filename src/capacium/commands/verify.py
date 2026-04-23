import base64
from typing import Optional
from ..registry import Registry
from ..fingerprint import compute_fingerprint, compute_bundle_fingerprint
from ..models import Kind
from ..signing import load_public_key, verify


def verify_capability(cap_spec: Optional[str] = None, verify_all: bool = False,
                      verify_signature: Optional[str] = None) -> bool:
    registry = Registry()

    if verify_signature and not verify_all and cap_spec:
        cap = registry.get_capability(cap_spec)
        if cap is None:
            print(f"Capability {cap_spec} not found.")
            return False
        return _verify_signature(cap, registry, verify_signature)

    if verify_all:
        capabilities = registry.list_capabilities()
        if not capabilities:
            print("No capabilities installed.")
            return True

        all_ok = True
        for cap in capabilities:
            if verify_signature:
                sig = registry.get_signature(cap.owner, cap.name, cap.version, verify_signature)
                if sig is None:
                    continue
                ok = _verify_signature(cap, registry, verify_signature)
            else:
                ok = _verify_single(cap, registry)
            if not ok:
                all_ok = False
        return all_ok

    elif cap_spec:
        cap = registry.get_capability(cap_spec)
        if cap is None:
            print(f"Capability {cap_spec} not found.")
            return False
        return _verify_single(cap, registry)

    else:
        print("Error: specify a capability or --all")
        return False


def _verify_signature(cap, registry: Registry, key_name: str) -> bool:
    sig_record = registry.get_signature(cap.owner, cap.name, cap.version, key_name)
    if sig_record is None:
        print(f"NO SIGNATURE: {cap.id}@{cap.version}")
        return False

    pubkey = load_public_key(key_name)
    if pubkey is None:
        print(f"Public key '{key_name}' not found.")
        return False

    if cap.kind == Kind.BUNDLE:
        bundle_id = f"{cap.owner}/{cap.name}@{cap.version}"
        member_ids = registry.get_bundle_members(bundle_id)
        sub_fingerprints = []
        for member_id in member_ids:
            parts = member_id.split("@", 1)
            member_cap_id = parts[0]
            member_version = parts[1] if len(parts) > 1 else None
            member_cap = registry.get_capability(member_cap_id, member_version)
            if member_cap is None:
                sub_fingerprints.append("UNKNOWN")
            else:
                sub_fingerprints.append(member_cap.fingerprint)
        fingerprint = compute_bundle_fingerprint(sub_fingerprints)
    else:
        fingerprint = compute_fingerprint(
            cap.install_path,
            exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", "capability.lock"]
        )

    sig_bytes = base64.b64decode(sig_record["signature"])
    fingerprint_bytes = fingerprint.encode("utf-8")

    if verify(pubkey, sig_bytes, fingerprint_bytes):
        print(f"SIGNATURE VERIFIED: {cap.id}@{cap.version} (key: {key_name})")
        return True
    else:
        print(f"SIGNATURE INVALID: {cap.id}@{cap.version} (key: {key_name})")
        return False


def _verify_single(cap, registry: Registry) -> bool:
    if cap.kind == Kind.BUNDLE:
        return _verify_bundle(cap, registry)
    return _verify_regular(cap, registry)


def _verify_regular(cap, registry: Registry) -> bool:
    if not cap.install_path or not cap.install_path.exists():
        print(f"ERROR: Install path for {cap.id}@{cap.version} does not exist: {cap.install_path}")
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


def _verify_bundle(cap, registry: Registry) -> bool:
    bundle_id = f"{cap.owner}/{cap.name}@{cap.version}"
    member_ids = registry.get_bundle_members(bundle_id)

    print(f"Verifying bundle {cap.id}@{cap.version} ({len(member_ids)} sub-capabilities)")

    all_ok = True

    sub_fingerprints = []
    for member_id in member_ids:
        parts = member_id.split("@", 1)
        member_cap_id = parts[0]
        member_version = parts[1] if len(parts) > 1 else None

        member_cap = registry.get_capability(member_cap_id, member_version)
        if member_cap is None:
            print(f"  MISSING: {member_id} (not in registry)")
            all_ok = False
            continue

        ok = _verify_single(member_cap, registry)
        if not ok:
            all_ok = False
        sub_fingerprints.append(member_cap.fingerprint)

    expected_bundle_fp = compute_bundle_fingerprint(sub_fingerprints)
    if expected_bundle_fp != cap.fingerprint:
        print(f"TAMPERED: {cap.id}@{cap.version} (bundle fingerprint mismatch)")
        print(f"  expected (from sub-caps): {expected_bundle_fp}")
        print(f"  stored:                   {cap.fingerprint}")
        all_ok = False

    if all_ok:
        print(f"VERIFIED: {cap.id}@{cap.version}")

    return all_ok
