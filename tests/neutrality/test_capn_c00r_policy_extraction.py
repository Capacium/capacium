"""CAPN-C00R: consumer policy is external to neutral Capacium Core."""

from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path

import pytest

from capacium.commands.validate import validate_capability
from capacium.kinds import (
    migrate_legacy_kind,
    migrate_legacy_payload,
    validate_kind,
)


def _run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    from capacium import cli

    monkeypatch.setattr(sys, "argv", ["cap", *args])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code)


def test_policy_shim_exits_before_network_resolver_installer_or_storage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forbidden_imports = {
        "capacium.commands.install",
        "capacium.commands.policy",
        "capacium.commands._resolve",
    }
    imported: list[str] = []
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        imported.append(name)
        if name in forbidden_imports:
            raise AssertionError(f"legacy policy shim imported {name}")
        return real_import(name, globals, locals, fromlist, level)

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError("legacy policy shim attempted a network request")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr("urllib.request.urlopen", forbidden_network)

    exit_code = _run_cli(
        monkeypatch,
        "install",
        "acme/demo",
        "--policy",
        "legacy-policy.yaml",
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "cap-policy install <capability> --policy <policy-file>" in captured.err
    assert forbidden_imports.isdisjoint(imported)


def test_install_help_does_not_advertise_policy_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _run_cli(monkeypatch, "install", "--help")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "--policy" not in captured.out
    assert "--policy" not in captured.err


def test_regular_install_path_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from capacium.commands import install as install_module

    calls: list[tuple[str, object, dict[str, object]]] = []

    def fake_install(cap_spec, source_dir, **kwargs):
        calls.append((cap_spec, source_dir, kwargs))
        return True

    monkeypatch.setattr(install_module, "install_capability", fake_install)

    exit_code = _run_cli(monkeypatch, "install", "acme/demo", "--offline")

    assert exit_code == 0
    assert len(calls) == 1
    cap_spec, source_dir, kwargs = calls[0]
    assert cap_spec == "acme/demo"
    assert source_dir is None
    assert kwargs["offline"] is True


def test_policy_module_is_absent_from_core_package() -> None:
    assert importlib.util.find_spec("capacium.commands.policy") is None


@pytest.mark.parametrize(
    "operation",
    [
        lambda: validate_kind("policy"),
        lambda: migrate_legacy_kind("policy"),
        lambda: migrate_legacy_payload({"kind": "policy"}),
    ],
)
def test_policy_kind_is_rejected_without_workflow_guidance(operation) -> None:
    with pytest.raises(ValueError) as exc:
        operation()

    message = str(exc.value)
    assert "policy" in message
    assert "cap-policy" in message or "external install-policy" in message
    assert "workflow" not in message.lower()


def test_validate_rejects_policy_as_external_document(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "capability.yaml"
    manifest.write_text(
        "\n".join(
            [
                "name: acme/policy-doc",
                "version: 1.0.0",
                "kind: policy",
                "description: Legacy policy document",
            ]
        ),
        encoding="utf-8",
    )

    result = validate_capability(str(manifest), offline=True)

    assert result["valid"] is False
    message = "\n".join(result["errors"])
    assert "external install-policy document" in message
    assert "cap-policy" in message
    assert "workflow" not in message.lower()
