import base64
import os
from pathlib import Path
from datetime import datetime


from capacium.signing import (
    generate_keypair,
    save_keypair,
    load_private_key,
    load_public_key,
    list_keys,
    import_key,
    export_public_key,
    export_public_key_pem,
    sign,
    verify,
)
from capacium.registry import Registry
from capacium.fingerprint import compute_fingerprint
from capacium.models import Capability, Kind
from capacium.commands.sign import sign_capability
from capacium.commands.verify import verify_capability


class TestKeyManager:
    def test_generate_keypair_returns_bytes(self):
        priv, pub = generate_keypair("test-key")
        assert isinstance(priv, bytes) and len(priv) > 0
        assert isinstance(pub, bytes) and len(pub) > 0

    def test_generate_keypair_ed25519_sizes(self):
        priv, pub = generate_keypair("test-key-size")
        # Ed25519 private key raw = 32 bytes, public key raw = 32 bytes
        # (cryptography stores seed as 32 bytes)
        assert len(pub) == 32
        assert len(priv) in (32, 64)  # nacl stores 64-byte sk (seed + pk)

    def test_save_and_load_keypair(self, tmp_path):
        priv, pub = generate_keypair("test-key")
        save_keypair("test-key", priv, pub, key_dir=tmp_path)
        loaded_priv = load_private_key("test-key", key_dir=tmp_path)
        loaded_pub = load_public_key("test-key", key_dir=tmp_path)
        assert loaded_priv == priv
        assert loaded_pub == pub

    def test_list_keys(self, tmp_path):
        assert list_keys(key_dir=tmp_path) == []
        priv1, pub1 = generate_keypair("key-a")
        priv2, pub2 = generate_keypair("key-b")
        save_keypair("key-a", priv1, pub1, key_dir=tmp_path)
        save_keypair("key-b", priv2, pub2, key_dir=tmp_path)
        keys = list_keys(key_dir=tmp_path)
        assert keys == ["key-a", "key-b"]

    def test_list_keys_uses_default_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert list_keys() == []
        priv, pub = generate_keypair("mykey")
        save_keypair("mykey", priv, pub)
        keys = list_keys()
        assert "mykey" in keys

    def test_export_public_key(self, tmp_path):
        priv, pub = generate_keypair("test-key")
        save_keypair("test-key", priv, pub, key_dir=tmp_path)
        exported = export_public_key("test-key", key_dir=tmp_path)
        assert exported == pub

    def test_export_public_key_pem(self, tmp_path):
        priv, pub = generate_keypair("test-key")
        save_keypair("test-key", priv, pub, key_dir=tmp_path)
        pem = export_public_key_pem("test-key", key_dir=tmp_path)
        assert pem is not None
        assert "BEGIN PUBLIC KEY" in pem

    def test_import_key(self, tmp_path):
        import cryptography.hazmat.primitives.asymmetric.ed25519 as ed25519
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, NoEncryption,
        )

        orig_priv = ed25519.Ed25519PrivateKey.generate()
        pem_bytes = orig_priv.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        priv_imported, pub_imported = import_key("imported", pem_bytes, key_dir=tmp_path)
        assert len(priv_imported) > 0
        assert len(pub_imported) == 32

        loaded_priv = load_private_key("imported", key_dir=tmp_path)
        loaded_pub = load_public_key("imported", key_dir=tmp_path)
        assert loaded_priv == priv_imported
        assert loaded_pub == pub_imported


class TestSignAndVerify:
    def test_sign_and_verify_roundtrip(self):
        priv, pub = generate_keypair("test-roundtrip")
        data = b"hello, world"
        sig = sign(priv, data)
        assert verify(pub, sig, data) is True

    def test_sign_and_verify_fails_on_tampered_data(self):
        priv, pub = generate_keypair("test-tamper")
        data = b"original data"
        sig = sign(priv, data)
        assert verify(pub, sig, b"tampered data") is False

    def test_sign_and_verify_fails_on_wrong_key(self):
        priv, pub = generate_keypair("key-a")
        priv_b, pub_b = generate_keypair("key-b")
        data = b"some data"
        sig = sign(priv, data)
        assert verify(pub_b, sig, data) is False

    def test_sign_and_verify_large_data(self):
        priv, pub = generate_keypair("test-large")
        data = os.urandom(1024 * 1024)  # 1MB
        sig = sign(priv, data)
        assert verify(pub, sig, data) is True

    def test_sign_and_verify_empty_data(self):
        priv, pub = generate_keypair("test-empty")
        data = b""
        sig = sign(priv, data)
        assert verify(pub, sig, data) is True

    def test_sign_and_verify_base64_roundtrip(self):
        priv, pub = generate_keypair("test-b64")
        data = b"fingerprint-12345"
        sig = sign(priv, data)
        sig_b64 = base64.b64encode(sig).decode("ascii")
        sig_restored = base64.b64decode(sig_b64)
        assert verify(pub, sig_restored, data) is True


class TestCapabilitySigning:
    def _setup_cap(self, tmp_path, monkeypatch, cap_name="test-cap", owner="owner", version="1.0.0"):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        cap_dir = tmp_path / ".capacium" / "packages" / owner / cap_name / version
        cap_dir.mkdir(parents=True)
        (cap_dir / "capability.yaml").write_text(
            f"kind: skill\nname: {cap_name}\nversion: {version}\nowner: {owner}\n"
        )
        (cap_dir / "main.py").write_text("print('hello')")

        fp = compute_fingerprint(cap_dir, exclude_patterns=[".git", "__pycache__", "*.pyc", ".DS_Store", ".capacium-meta.json"])
        registry = Registry()
        cap = Capability(
            owner=owner, name=cap_name, version=version,
            kind=Kind.SKILL, fingerprint=fp, install_path=cap_dir,
            installed_at=datetime.now(), dependencies=[], framework="opencode",
        )
        registry.add_capability(cap)
        return cap, registry

    def _setup_key(self, tmp_path, monkeypatch, key_name="test-key"):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from capacium.signing import generate_keypair, save_keypair
        priv, pub = generate_keypair(key_name)
        save_keypair(key_name, priv, pub)
        return priv, pub

    def test_sign_capability(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        cap, registry = self._setup_cap(tmp_path, monkeypatch)

        result = sign_capability("owner/test-cap", key_name="test-key")
        assert result

        sig = registry.get_signature("owner", "test-cap", "1.0.0")
        assert sig is not None
        assert sig["key_name"] == "test-key"
        assert len(sig["signature"]) > 0

    def test_verify_valid_signature(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        cap, registry = self._setup_cap(tmp_path, monkeypatch)

        sign_capability("owner/test-cap", key_name="test-key")

        assert verify_capability("owner/test-cap", verify_signature="test-key")

    def test_verify_invalid_signature_wrong_key(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch, key_name="key-a")
        self._setup_key(tmp_path, monkeypatch, key_name="key-b")
        cap, registry = self._setup_cap(tmp_path, monkeypatch)

        sign_capability("owner/test-cap", key_name="key-a")

        assert not verify_capability("owner/test-cap", verify_signature="key-b")

    def test_verify_signature_after_tamper(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        cap, registry = self._setup_cap(tmp_path, monkeypatch)

        sign_capability("owner/test-cap", key_name="test-key")

        (cap.install_path / "main.py").write_text("print('tampered')")

        assert not verify_capability("owner/test-cap", verify_signature="test-key")

    def test_sign_nonexistent_cap(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = sign_capability("owner/nonexistent", key_name="test-key")
        assert not result

    def test_sign_with_missing_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cap, _ = self._setup_cap(tmp_path, monkeypatch)
        result = sign_capability("owner/test-cap", key_name="nonexistent-key")
        assert not result

    def test_multiple_signatures_different_keys(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch, key_name="key-a")
        self._setup_key(tmp_path, monkeypatch, key_name="key-b")
        cap, registry = self._setup_cap(tmp_path, monkeypatch)

        assert sign_capability("owner/test-cap", key_name="key-a")
        assert sign_capability("owner/test-cap", key_name="key-b")

        assert verify_capability("owner/test-cap", verify_signature="key-a")
        assert verify_capability("owner/test-cap", verify_signature="key-b")

    def test_verify_all_with_signature(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        cap, registry = self._setup_cap(tmp_path, monkeypatch, cap_name="cap-a", owner="owner", version="1.0.0")
        sign_capability("owner/cap-a", key_name="test-key")

        cap2, _ = self._setup_cap(tmp_path, monkeypatch, cap_name="cap-b", owner="owner", version="1.0.0")

        result = verify_capability(verify_all=True, verify_signature="test-key")
        assert result  # cap-a verified, cap-b has no signature but --all doesn't fail on missing sig

    def test_store_and_retrieve_signature(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        cap, registry = self._setup_cap(tmp_path, monkeypatch)

        sign_capability("owner/test-cap", key_name="test-key")
        sig_record = registry.get_signature("owner", "test-cap", "1.0.0")
        assert sig_record is not None
        assert sig_record["key_name"] == "test-key"
        assert sig_record["cap_owner"] == "owner"
        assert sig_record["cap_name"] == "test-cap"
        assert sig_record["cap_version"] == "1.0.0"


class TestKeyCLICommands:
    def test_generate_and_list_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from capacium.commands.key import key_generate, key_list
        assert key_generate("cli-test-key")
        assert key_generate("cli-test-key-2")
        capsys = key_list()
        assert capsys is True

    def test_export_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from capacium.commands.key import key_generate, key_export
        assert key_generate("export-test")
        result = key_export("export-test")
        assert result is True

    def test_export_nonexistent_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from capacium.commands.key import key_export
        assert not key_export("nonexistent")
