import base64
import os
from pathlib import Path
from typing import Optional, List, Tuple

_SIGNING_BACKEND = None


def _get_backend():
    global _SIGNING_BACKEND
    if _SIGNING_BACKEND is not None:
        return _SIGNING_BACKEND

    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PrivateFormat,
            PublicFormat,
            NoEncryption,
            load_pem_private_key,
            load_pem_public_key,
        )
        _SIGNING_BACKEND = {
            "name": "cryptography",
            "ed25519": ed25519,
            "PrivateFormat": PrivateFormat,
            "PublicFormat": PublicFormat,
            "Encoding": Encoding,
            "NoEncryption": NoEncryption,
            "load_pem_private_key": load_pem_private_key,
            "load_pem_public_key": load_pem_public_key,
        }
    except ImportError:
        try:
            from nacl.bindings import (
                crypto_sign_ed25519_keypair,
                crypto_sign_ed25519_sk_to_pk,
                crypto_sign_ed25519,
                crypto_sign_ed25519_open,
            )
            _SIGNING_BACKEND = {
                "name": "nacl",
                "crypto_sign_ed25519_keypair": crypto_sign_ed25519_keypair,
                "crypto_sign_ed25519_sk_to_pk": crypto_sign_ed25519_sk_to_pk,
                "crypto_sign_ed25519": crypto_sign_ed25519,
                "crypto_sign_ed25519_open": crypto_sign_ed25519_open,
            }
        except ImportError:
            _SIGNING_BACKEND = {"name": "openssl"}

    return _SIGNING_BACKEND


def get_keys_dir() -> Path:
    return Path.home() / ".capacium" / "keys"


def _ensure_keys_dir() -> Path:
    kd = get_keys_dir()
    kd.mkdir(parents=True, exist_ok=True)
    return kd


def _key_path(name: str) -> Path:
    return _ensure_keys_dir() / f"{name}.key"


def _pub_path(name: str) -> Path:
    return _ensure_keys_dir() / f"{name}.pub"


def generate_keypair(name: str) -> Tuple[bytes, bytes]:
    backend = _get_backend()
    if backend["name"] == "cryptography":
        private_key = backend["ed25519"].Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=backend["Encoding"].Raw,
            format=backend["PrivateFormat"].Raw,
            encryption_algorithm=backend["NoEncryption"](),
        )
        public_bytes = private_key.public_key().public_bytes(
            encoding=backend["Encoding"].Raw,
            format=backend["PublicFormat"].Raw,
        )
        return private_bytes, public_bytes
    elif backend["name"] == "nacl":
        pk, sk = backend["crypto_sign_ed25519_keypair"]()
        return bytes(sk), bytes(pk)
    else:
        import subprocess
        priv_path = _key_path(name)
        pub_path = _pub_path(name)
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv_path)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(priv_path), "-pubout", "-out", str(pub_path)],
            check=True, capture_output=True,
        )
        private_bytes = priv_path.read_bytes()
        public_bytes = pub_path.read_bytes()
        return private_bytes, public_bytes


def save_keypair(name: str, private_key: bytes, public_key: bytes, key_dir: Optional[Path] = None) -> None:
    if key_dir is None:
        key_dir = _ensure_keys_dir()
    else:
        key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / f"{name}.key").write_bytes(private_key)
    (key_dir / f"{name}.pub").write_bytes(public_key)


def load_private_key(name: str, key_dir: Optional[Path] = None) -> Optional[bytes]:
    if key_dir is None:
        key_dir = get_keys_dir()
    path = key_dir / f"{name}.key"
    if path.exists():
        return path.read_bytes()
    return None


def load_public_key(name: str, key_dir: Optional[Path] = None) -> Optional[bytes]:
    if key_dir is None:
        key_dir = get_keys_dir()
    path = key_dir / f"{name}.pub"
    if path.exists():
        return path.read_bytes()
    return None


def list_keys(key_dir: Optional[Path] = None) -> List[str]:
    if key_dir is None:
        key_dir = get_keys_dir()
    if not key_dir.exists():
        return []
    seen = set()
    for f in sorted(key_dir.iterdir()):
        if f.suffix == ".key":
            seen.add(f.stem)
    return sorted(seen)


def import_key(name: str, pem_data: bytes, key_dir: Optional[Path] = None) -> Tuple[bytes, bytes]:
    backend = _get_backend()
    if key_dir is None:
        key_dir = _ensure_keys_dir()
    else:
        key_dir.mkdir(parents=True, exist_ok=True)

    if backend["name"] == "cryptography":
        private_key = backend["load_pem_private_key"](pem_data, password=None)
        private_bytes = private_key.private_bytes(
            encoding=backend["Encoding"].Raw,
            format=backend["PrivateFormat"].Raw,
            encryption_algorithm=backend["NoEncryption"](),
        )
        public_bytes = private_key.public_key().public_bytes(
            encoding=backend["Encoding"].Raw,
            format=backend["PublicFormat"].Raw,
        )
    elif backend["name"] == "nacl":
        seed = pem_data[:32] if len(pem_data) >= 32 else pem_data
        from nacl.bindings import crypto_sign_seed_keypair
        pk, sk = crypto_sign_seed_keypair(seed)
        private_bytes = bytes(sk)
        public_bytes = bytes(pk)
    else:
        priv_path = key_dir / f"{name}.key"
        pub_path = key_dir / f"{name}.pub"
        priv_path.write_bytes(pem_data)
        import subprocess
        subprocess.run(
            ["openssl", "pkey", "-in", str(priv_path), "-pubout", "-out", str(pub_path)],
            check=True, capture_output=True,
        )
        private_bytes = priv_path.read_bytes()
        public_bytes = pub_path.read_bytes()
        return private_bytes, public_bytes

    save_keypair(name, private_bytes, public_bytes, key_dir)
    return private_bytes, public_bytes


def export_public_key(name: str, key_dir: Optional[Path] = None) -> Optional[bytes]:
    if key_dir is None:
        key_dir = get_keys_dir()
    path = key_dir / f"{name}.pub"
    if path.exists():
        return path.read_bytes()
    return None


def export_public_key_pem(name: str, key_dir: Optional[Path] = None) -> Optional[str]:
    raw = export_public_key(name, key_dir)
    if raw is None:
        return None
    backend = _get_backend()
    if backend["name"] == "cryptography":
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(raw)
        return pub_key.public_bytes(encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo).decode()
    elif backend["name"] == "nacl":
        b64 = base64.b64encode(raw).decode()
        return f"-----BEGIN PUBLIC KEY-----\n{b64}\n-----END PUBLIC KEY-----\n"
    else:
        return raw.decode() if isinstance(raw, bytes) else raw


def sign(privkey_bytes: bytes, data: bytes) -> bytes:
    backend = _get_backend()
    if backend["name"] == "cryptography":
        from cryptography.hazmat.primitives.asymmetric import ed25519
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(privkey_bytes)
        return private_key.sign(data)
    elif backend["name"] == "nacl":
        return backend["crypto_sign_ed25519"](data, privkey_bytes)[:64]
    else:
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".key") as kf:
            kf.write(privkey_bytes)
            kpath = kf.name
        spath = ""
        dpath = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".sig") as sf:
                spath = sf.name
            with tempfile.NamedTemporaryFile(delete=False, suffix=".data") as df:
                df.write(data)
                dpath = df.name
            subprocess.run(
                ["openssl", "pkeyutl", "-sign", "-inkey", kpath, "-rawin", "-in", dpath, "-out", spath],
                check=True, capture_output=True,
            )
            return Path(spath).read_bytes()
        finally:
            for p in [kpath, spath, dpath]:
                try:
                    if p:
                        os.unlink(p)
                except (OSError, NameError):
                    pass


def verify(pubkey_bytes: bytes, signature: bytes, data: bytes) -> bool:
    backend = _get_backend()
    try:
        if backend["name"] == "cryptography":
            from cryptography.hazmat.primitives.asymmetric import ed25519
            from cryptography.exceptions import InvalidSignature
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)
            public_key.verify(signature, data)
            return True
        elif backend["name"] == "nacl":
            from nacl.bindings import crypto_sign_ed25519_open
            sm = signature + data
            crypto_sign_ed25519_open(sm, pubkey_bytes)
            return True
        else:
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pub") as pkf:
                pub_pem = _raw_pub_to_pem_openssl(pubkey_bytes)
                pkf.write(pub_pem)
                pkpath = pkf.name
            spath = ""
            dpath = ""
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".sig") as sf:
                    sf.write(signature)
                    spath = sf.name
                with tempfile.NamedTemporaryFile(delete=False, suffix=".data") as df:
                    df.write(data)
                    dpath = df.name
                result = subprocess.run(
                    ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pkpath,
                     "-rawin", "-in", dpath, "-sigfile", spath],
                    capture_output=True, text=True,
                )
                return "Verified OK" in result.stdout or result.returncode == 0
            finally:
                for p in [pkpath, spath, dpath]:
                    try:
                        if p:
                            os.unlink(p)
                    except (OSError, NameError):
                        pass
    except Exception:
        return False


def _raw_pub_to_pem_openssl(raw: bytes) -> bytes:
    import base64
    b64 = base64.b64encode(raw).decode()
    builder = "-----BEGIN PUBLIC KEY-----\n"
    for i in range(0, len(b64), 64):
        builder += b64[i:i+64] + "\n"
    builder += "-----END PUBLIC KEY-----\n"
    return builder.encode()
