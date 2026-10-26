"""CLI contract tests for the machine-readable publisher (CL-111).

Locks the exit-code contract, JSON-mode stdout discipline, stderr diagnostics,
transport-uncertain handling and trusted-publishing help text for ``cap publish``.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import capacium.cli as cli_mod
from capacium.registry_client import RegistryClientError
from capacium.commands.publish import (
    EXIT_OK,
    EXIT_USER_ERROR,
    EXIT_TRANSPORT_UNCERTAIN,
    EXIT_UNAUTHORIZED,
    EXIT_FORBIDDEN,
    EXIT_CONFLICT,
    EXIT_VALIDATION,
)

RECEIPT = {
    "publication_id": "stable-id-123",
    "canonical_name": "acme/cap-demo",
    "name": "cap-demo",
    "version": "1.1.1",
    "publication_digest": "sha256-of-normalized-metadata",
    "created": True,
    "idempotent": False,
    "status": "accepted",
}


def _write_capability(tmp_path: Path, deps=None) -> Path:
    cap_dir = tmp_path / "cap-demo"
    cap_dir.mkdir(parents=True, exist_ok=True)
    dep_block = ""
    if deps:
        dep_block = "dependencies:\n" + "\n".join(
            f"  {k}: {v}" for k, v in deps.items()
        )
    (cap_dir / "capability.yaml").write_text(
        "\n".join(
            [
                "kind: skill",
                "name: cap-demo",
                "version: 1.1.1",
                "description: demo capability",
                "owner: acme",
                "frameworks:",
                "  - opencode",
                dep_block,
            ]
        )
        + "\n"
    )
    return cap_dir


class TestPublishJsonMode:
    def test_json_emits_only_receipt_on_stdout(
        self, capsys, tmp_path, monkeypatch
    ):
        cap_dir = _write_capability(tmp_path)
        instance = mock.MagicMock()
        instance.publish.return_value = dict(RECEIPT)
        client_cls = mock.MagicMock(return_value=instance)
        monkeypatch.setattr(
            "capacium.commands.publish.RegistryClient", client_cls
        )
        monkeypatch.setattr(
            "sys.argv",
            ["cap", "publish", "--json", str(cap_dir)],
        )
        with pytest.raises(SystemExit) as exc:
            cli_mod.main()
        out = capsys.readouterr()
        assert exc.value.code == EXIT_OK
        lines = [line for line in out.out.splitlines() if line.strip()]
        # Only one JSON payload on stdout, no progress prose.
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["canonical_name"] == "acme/cap-demo"
        assert parsed["name"] == "cap-demo"
        assert parsed["version"] == "1.1.1"
        assert parsed["publication_id"] == "stable-id-123"
        assert parsed["publication_digest"] == "sha256-of-normalized-metadata"
        assert parsed["created"] is True
        assert parsed["idempotent"] is False
        assert parsed["status"] == "accepted"

    def test_json_idempotent_retry_flags(self, capsys, tmp_path, monkeypatch):
        cap_dir = _write_capability(tmp_path)
        instance = mock.MagicMock()
        retry = dict(RECEIPT)
        retry["created"] = False
        retry["idempotent"] = True
        instance.publish.return_value = retry
        client_cls = mock.MagicMock(return_value=instance)
        monkeypatch.setattr(
            "capacium.commands.publish.RegistryClient", client_cls
        )
        monkeypatch.setattr(
            "sys.argv", ["cap", "publish", "--json", str(cap_dir)]
        )
        with pytest.raises(SystemExit) as exc:
            cli_mod.main()
        out = capsys.readouterr()
        assert exc.value.code == EXIT_OK
        parsed = json.loads(out.out.strip())
        assert parsed["created"] is False
        assert parsed["idempotent"] is True


class TestPublishExitCodes:
    def _direct(self, status_raise, tmp_path):
        cap_dir = _write_capability(tmp_path)
        instance = mock.MagicMock()
        instance.publish.side_effect = status_raise
        with mock.patch(
            "capacium.commands.publish.RegistryClient", return_value=instance
        ):
            from capacium.commands.publish import publish_capability

            return publish_capability(cap_dir)

    def test_unauthorized_401(self, tmp_path):
        assert self._direct(
            RegistryClientError("HTTP 401 ...", status_code=401), tmp_path
        ) == EXIT_UNAUTHORIZED

    def test_forbidden_403(self, tmp_path):
        assert self._direct(
            RegistryClientError("HTTP 403 ...", status_code=403), tmp_path
        ) == EXIT_FORBIDDEN

    def test_conflict_409(self, tmp_path):
        assert self._direct(
            RegistryClientError("HTTP 409 ...", status_code=409), tmp_path
        ) == EXIT_CONFLICT

    def test_validation_422(self, tmp_path):
        assert self._direct(
            RegistryClientError("HTTP 422 ...", status_code=422), tmp_path
        ) == EXIT_VALIDATION

    def test_transport_uncertain_2(self, tmp_path):
        assert self._direct(
            RegistryClientError("Connection failed", status_code=None), tmp_path
        ) == EXIT_TRANSPORT_UNCERTAIN

    def test_local_user_error(self, tmp_path):
        cap_dir = tmp_path / "nope"
        cap_dir.mkdir()
        from capacium.commands.publish import publish_capability

        assert publish_capability(cap_dir.absolute() / "missing.yaml") == EXIT_USER_ERROR


class TestPublishTransportNotice:
    def test_stderr_carries_lookup_key_without_definitive_failure(
        self, capsys, tmp_path
    ):
        cap_dir = _write_capability(tmp_path)
        instance = mock.MagicMock()
        instance.publish.side_effect = RegistryClientError(
            "Connection failed: [Errno 61]", status_code=None
        )
        with mock.patch(
            "capacium.commands.publish.RegistryClient", return_value=instance
        ):
            from capacium.commands.publish import publish_capability

            rc = publish_capability(cap_dir)
            out = capsys.readouterr()
        assert rc == EXIT_TRANSPORT_UNCERTAIN
        assert "acme/cap-demo" in out.err
        assert "read" in out.err.lower()
        # Records the state as unconfirmed, not a done-and-failed verdict.
        assert "could not confirm" in out.err.lower()

    def test_transport_exits_nonzero_via_cli(self, capsys, tmp_path, monkeypatch):
        cap_dir = _write_capability(tmp_path)
        instance = mock.MagicMock()
        instance.publish.side_effect = RegistryClientError(
            "Connection failed: [Errno 61]", status_code=None
        )
        client_cls = mock.MagicMock(return_value=instance)
        monkeypatch.setattr(
            "capacium.commands.publish.RegistryClient", client_cls
        )
        monkeypatch.setattr("sys.argv", ["cap", "publish", str(cap_dir)])

        with pytest.raises(SystemExit) as exc:
            cli_mod.main()
        assert exc.value.code == EXIT_TRANSPORT_UNCERTAIN


class TestPublishHelp:
    def test_help_describes_trusted_publishing(self, tmp_path, monkeypatch):
        # Start from the ambient environment: a bare ``{"PYTHONPATH": ...}``
        # env drops SystemRoot/TEMP on Windows and the interpreter aborts
        # before argparse runs ("failed to get random numbers to initialize
        # Python"). Only PYTHONPATH is overridden; everything else is inherited.
        import os

        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
        result = subprocess.run(
            [sys.executable, "-m", "capacium.cli", "publish", "--help"],
            capture_output=True,
            text=True,
            env=env,
        )
        text = (result.stdout + result.stderr).lower()
        assert result.returncode == 0
        assert "trusted exchange registry" in text
        assert "match the exchange server secret" not in text


class TestDefaultRequestShape:
    def test_default_11_dependency_map_preserved(self, tmp_path):
        """Criterion 1: the 1.1.0-shaped dependency map ships unchanged."""
        cap_dir = _write_capability(
            tmp_path, deps={"dependency-a": "^1.2.0", "dependency-b": "2.0.1"}
        )
        instance = mock.MagicMock()
        instance.publish.return_value = dict(RECEIPT)
        with mock.patch(
            "capacium.commands.publish.RegistryClient", return_value=instance
        ):
            from capacium.commands.publish import publish_capability

            rc = publish_capability(cap_dir, json_output=True)
            assert rc == EXIT_OK
        payload = instance.publish.call_args.args[0]
        # Still a name->constraint map, not a normalized list; normalization is
        # server-side behaviour retained for backward compatibility.
        assert payload["dependencies"] == {
            "dependency-a": "^1.2.0",
            "dependency-b": "2.0.1",
        }
