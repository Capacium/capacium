import base64
from ..registry import Registry
from ..signing import load_private_key, sign, list_keys
from ..fingerprint import compute_fingerprint, compute_bundle_fingerprint
from ..models import Kind
from ._resolve import resolve_cap_id


def sign_capability(cap_spec: str, key_name: str) -> bool:
    registry = Registry()
    cap_id = resolve_cap_id(cap_spec)
    cap = registry.get_capability(cap_id)
    if cap is None:
        print(f"Capability {cap_spec} not found.")
        return False

    if not cap.install_path or not cap.install_path.exists():
        print(f"Install path for {cap_spec} does not exist.")
        return False

    privkey = load_private_key(key_name)
    if privkey is None:
        print(f"Private key '{key_name}' not found. Use 'cap key generate {key_name}' first.")
        available = list_keys()
        if available:
            print(f"Available keys: {', '.join(available)}")
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
                print(f"  Sub-capability {member_id} not found in registry.")
                return False
            sub_fingerprints.append(member_cap.fingerprint)
        fingerprint = compute_bundle_fingerprint(sub_fingerprints)
    else:
        fingerprint = compute_fingerprint(
            cap.install_path,
            exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json", "capability.lock"]
        )

    fingerprint_bytes = fingerprint.encode("utf-8")
    sig_bytes = sign(privkey, fingerprint_bytes)
    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

    registry.store_signature(cap.owner, cap.name, cap.version, key_name, sig_b64)
    print(f"Signed {cap.id}@{cap.version} with key '{key_name}'")
    print(f"Signature: {sig_b64[:32]}...")
    return True
