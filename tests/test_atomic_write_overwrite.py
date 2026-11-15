"""WIN-001: atomic write overwrite — simulate Windows FileExistsError.

On Windows, ``Path.rename`` raises ``FileExistsError`` (WinError 183) when
the target already exists. ``Path.replace`` / ``os.replace`` does not.
The journal writer (``_write_journal``) and the pointer writer
(``_write_pointer``) must use replace so an existing target is overwritten
rather than raising.
"""

import os
from pathlib import Path

import pytest

from capacium.commands._journal import _write_journal, _read_journal
from capacium.commands.exec import _write_pointer, _read_pointer


# ── helpers ───────────────────────────────────────────────────────────


def _windows_rename_factory(real_rename):
    """Return a rename that raises FileExistsError when the target exists."""

    def _raising_rename(self, target):
        target_path = Path(str(target))
        if target_path.exists():
            raise FileExistsError(
                17, "Cannot create a file when that file already exists", str(target)
            )
        return real_rename(self, target)

    return _raising_rename


# ── fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def simulate_windows(tmp_path, monkeypatch):
    """Patch Path.rename and os.rename to raise FileExistsError when target exists.

    Returns *tmp_path* so tests can use it as their working directory.
    """
    real_path_rename = Path.rename
    real_os_rename = os.rename

    monkeypatch.setattr(
        Path, "rename", _windows_rename_factory(real_path_rename)
    )
    monkeypatch.setattr(
        os, "rename", _windows_rename_factory(real_os_rename)
    )

    return tmp_path


# ── tests ──────────────────────────────────────────────────────────────


class TestJournalWriterOverwrite:
    """_write_journal must overwrite an existing target without raising."""

    def test_overwrites_existing_target(self, tmp_path, monkeypatch):
        """_write_journal overwrites a pre-existing journal file."""
        journal_path = tmp_path / "journal.json"
        journal_path.write_text('{"old": true}')

        data = {"new": True, "status": "ok"}
        _write_journal(journal_path, data)

        result = _read_journal(journal_path)
        assert result == data

    def test_no_tmp_left_after_write(self, tmp_path):
        """No .tmp file remains after _write_journal completes."""
        journal_path = tmp_path / "clean.json"
        _write_journal(journal_path, {"key": "val"})

        assert not Path(str(journal_path) + ".tmp").exists()

    def test_red_on_windows_semantics(self, tmp_path, simulate_windows):
        """Under simulated Windows semantics, _write_journal overwrites
        an existing target without raising FileExistsError."""
        journal_path = tmp_path / "win-journal.json"
        journal_path.write_text('{"existing": "target"}')

        data = {"cap_id": "test/win", "version": "1.0.0", "committed": False}
        _write_journal(journal_path, data)

        result = _read_journal(journal_path)
        assert result == data
        assert not Path(str(journal_path) + ".tmp").exists()


class TestPointerWriterOverwrite:
    """_write_pointer must overwrite an existing target without raising."""

    def test_overwrites_existing_target(self, tmp_path):
        """_write_pointer overwrites a pre-existing pointer file."""
        ptr_path = tmp_path / "pointer.txt"
        ptr_path.write_text("old-digest\n")

        _write_pointer(ptr_path, "new-digest")
        assert _read_pointer(ptr_path) == "new-digest"

    def test_no_tmp_left_after_write(self, tmp_path):
        """No .tmp file remains after _write_pointer completes."""
        ptr_path = tmp_path / "clean-ptr.txt"
        _write_pointer(ptr_path, "abc123")

        assert not Path(str(ptr_path) + ".tmp").exists()

    def test_red_on_windows_semantics(self, tmp_path, simulate_windows):
        """Under simulated Windows semantics, _write_pointer overwrites
        an existing target without raising FileExistsError."""
        ptr_path = tmp_path / "win-pointer.txt"
        ptr_path.write_text("previous-digest\n")

        _write_pointer(ptr_path, "new-digest")
        assert _read_pointer(ptr_path) == "new-digest"
        assert not Path(str(ptr_path) + ".tmp").exists()
