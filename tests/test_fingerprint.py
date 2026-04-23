from pathlib import Path
from capacium.fingerprint import compute_fingerprint, verify_fingerprint


class TestFingerprint:
    def test_compute_deterministic(self, tmp_path):
        d = tmp_path / "a"
        d.mkdir()
        (d / "file1.txt").write_text("hello")
        (d / "file2.txt").write_text("world")
        fp1 = compute_fingerprint(d)
        fp2 = compute_fingerprint(d)
        assert fp1 == fp2

    def test_compute_changes_on_modification(self, tmp_path):
        d = tmp_path / "b"
        d.mkdir()
        (d / "data.txt").write_text("original")
        fp1 = compute_fingerprint(d)
        (d / "data.txt").write_text("modified")
        fp2 = compute_fingerprint(d)
        assert fp1 != fp2

    def test_exclude_patterns(self, tmp_path):
        d = tmp_path / "c"
        d.mkdir()
        (d / "keep.txt").write_text("keep me")
        (d / ".excluded").write_text("ignore me")
        fp1 = compute_fingerprint(d, exclude_patterns=[".excluded"])
        (d / ".excluded").write_text("changed")
        fp2 = compute_fingerprint(d, exclude_patterns=[".excluded"])
        assert fp1 == fp2

    def test_verify_match(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        (d / "file.txt").write_text("content")
        fp = compute_fingerprint(d)
        assert verify_fingerprint(d, fp)

    def test_verify_mismatch(self, tmp_path):
        d = tmp_path / "e"
        d.mkdir()
        (d / "file.txt").write_text("content")
        assert not verify_fingerprint(d, "deadbeef")
