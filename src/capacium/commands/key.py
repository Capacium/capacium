from pathlib import Path
from ..signing import (
    generate_keypair,
    save_keypair,
    list_keys,
    export_public_key_pem,
    import_key,
    get_keys_dir,
)


def key_generate(name: str) -> bool:
    if not name.strip():
        print("Error: key name cannot be empty.")
        return False
    if (get_keys_dir() / f"{name}.key").exists():
        print(f"Key '{name}' already exists. Use a different name or remove the existing key.")
        return False
    priv, pub = generate_keypair(name)
    save_keypair(name, priv, pub)
    print(f"Generated keypair '{name}'")
    print(f"  Private key: {get_keys_dir() / f'{name}.key'}")
    print(f"  Public key:  {get_keys_dir() / f'{name}.pub'}")
    return True


def key_list() -> bool:
    keys = list_keys()
    if not keys:
        print("No keys found. Use 'cap key generate <name>' to create one.")
        return True
    print("Available keys:")
    for k in keys:
        pub_path = get_keys_dir() / f"{k}.pub"
        pub_size = pub_path.stat().st_size if pub_path.exists() else 0
        print(f"  {k}  ({pub_size} bytes public key)")
    return True


def key_export(name: str) -> bool:
    pem = export_public_key_pem(name)
    if pem is None:
        print(f"Key '{name}' not found.")
        return False
    print(pem)
    return True


def key_import(name: str, pem_file: str) -> bool:
    path = Path(pem_file)
    if not path.exists():
        print(f"File not found: {pem_file}")
        return False
    pem_data = path.read_bytes()
    priv, pub = import_key(name, pem_data)
    print(f"Imported key '{name}' from {pem_file}")
    return True
