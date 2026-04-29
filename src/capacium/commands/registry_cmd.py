import json
import sys
from pathlib import Path
from typing import Optional

from ..registry_client import RegistryClient, RegistryClientError
from ..manifest import Manifest
from ..utils.config import (
    load_auth_token,
    load_auth_data,
    save_auth_token,
    clear_auth,
    get_registry_url,
    load_user_config,
)


def registry_login(registry_url: Optional[str] = None) -> bool:
    import getpass

    effective_url = registry_url or get_registry_url()

    print(f"\n  Capacium Registry Login")
    print("\u2500" * 28)
    print(f"\n  Registry: {effective_url}")

    existing = load_auth_data()
    if existing:
        print(f"  Already authenticated.")
        reconfirm = input("  Re-authenticate? (y/N): ").strip().lower()
        if reconfirm not in ("y", "yes"):
            return True

    print()
    token = getpass.getpass("  Exchange API Token: ").strip()
    if not token:
        print("  Token cannot be empty. Aborted.")
        return False

    save_auth_token(token, effective_url)
    print(f"\n\u2705 Token saved to ~/.capacium/auth")

    client = RegistryClient(token=token)
    try:
        if client.verify_token(registry_url=effective_url):
            print(f"\u2705 Connection verified successfully.\n")
            return True
        else:
            print(f"\u26a0\ufe0f  Token verification failed. Token saved but may be invalid.\n")
            return False
    except RegistryClientError as e:
        print(f"\u26a0\ufe0f  Could not verify connection: {e}\n")
        return False


def registry_publish(path: Path, registry_url: Optional[str] = None) -> bool:
    effective_url = registry_url or get_registry_url()

    if not path.exists() or not path.is_dir():
        print(f"Error: path does not exist or is not a directory: {path}")
        return False

    manifest = Manifest.detect_from_directory(path)
    print(f"\n  Publishing {manifest.owner}/{manifest.name}@{manifest.version}")

    print(f"  Validating manifest...")
    errors = manifest.validate()
    if errors:
        print(f"\u274c Validation failed:")
        for e in errors:
            print(f"   \u2022 {e}")
        return False
    print(f"  \u2705 Manifest valid.")

    payload = {
        "name": manifest.name,
        "owner": manifest.owner or "global",
        "version": manifest.version,
        "kind": manifest.kind or "skill",
        "description": manifest.description,
        "frameworks": manifest.frameworks,
        "dependencies": manifest.dependencies,
        "runtimes": manifest.runtimes,
        "repository": manifest.repository,
        "homepage": manifest.homepage,
        "license": manifest.license,
        "keywords": manifest.keywords,
    }

    token = load_auth_token()
    if not token:
        print(f"\u26a0\ufe0f  Not authenticated. Run 'cap registry login' first.")
        return False

    client = RegistryClient(token=token)
    try:
        print(f"  Publishing to {effective_url}...")
        result = client.publish(payload, registry_url=effective_url)
    except RegistryClientError as e:
        print(f"\u274c Publish failed: {e}")
        return False

    print(f"\n\u2705 Published successfully!")

    trust = result.get("trust", result.get("trust_state", "untrusted"))
    if trust:
        print(f"   Trust:   {trust}")
    score = result.get("trust_score", result.get("score"))
    if score is not None:
        print(f"   Score:   {score}")
    cap_url = result.get("url") or f"{effective_url}/capabilities/{manifest.owner}/{manifest.name}"
    print(f"   URL:     {cap_url}")
    print()
    return True


def registry_status(registry_url: Optional[str] = None) -> bool:
    effective_url = registry_url or get_registry_url()

    print(f"\n  Capacium Registry Status")
    print("\u2500" * 26)
    print(f"  \U0001f310 Registry URL: {effective_url}")

    auth_data = load_auth_data()
    token = load_auth_token()

    if token and auth_data:
        print(f"  \U0001f511 Authenticated: yes")
        if auth_data.get("registry"):
            print(f"       Stored registry: {auth_data.get('registry')}")
    else:
        print(f"  \U0001f511 Authenticated: no")

    config = load_user_config()
    if config.get("trust_level"):
        print(f"  \U0001f6e1\ufe0f  Trust level:   {config['trust_level']}")
    if config.get("auto_update"):
        print(f"  \U0001f504 Auto-update:    {config['auto_update']}")

    if token:
        client = RegistryClient(token=token)
        try:
            user = client.get_user_info(registry_url=effective_url)
            if user:
                print(f"\n  \U0001f464 User Info:")
                print(f"       Username: {user.get('username', user.get('name', 'unknown'))}")
                if user.get("email"):
                    print(f"       Email:    {user.get('email')}")
                if user.get("role"):
                    print(f"       Role:     {user.get('role')}")
        except RegistryClientError:
            pass

        try:
            stats = client.get_stats(registry_url=effective_url)
            if stats:
                print(f"\n  \U0001f4ca Registry Stats:")
                for key, value in sorted(stats.items()):
                    print(f"       {key}: {value}")
        except RegistryClientError:
            print(f"\n  \u26a0\ufe0f  Could not fetch registry stats (registry may be unreachable)")

    print()
    return True
