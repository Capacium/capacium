"""CAPN-C00R: consumer policy is external to neutral Capacium Core."""

from __future__ import annotations

import ast
import builtins
import importlib.util
import os
import re
import shutil
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


def test_policy_shim_with_source_exits_before_all_external_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from capacium import cli  # Load the command module before I/O is denied.

    source = tmp_path / "source"
    source.mkdir()
    marker = source / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    before = marker.read_bytes()

    forbidden_imports = {
        "capacium.commands.install",
        "capacium.commands.policy",
        "capacium.commands._resolve",
        "capacium.registry",
        "capacium.storage",
    }
    attempted_effects: list[str] = []
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in forbidden_imports:
            attempted_effects.append(f"import:{name}")
            raise AssertionError(f"legacy policy shim imported {name}")
        return real_import(name, globals, locals, fromlist, level)

    def forbidden_effect(*_args, **_kwargs):
        attempted_effects.append("external-effect")
        raise AssertionError("legacy policy shim attempted an external effect")

    monkeypatch.setattr(sys, "argv", [
        "cap",
        "install",
        "acme/demo",
        "--source",
        str(source),
        "--policy",
        "legacy-policy.yaml",
    ])

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "__import__", guarded_import)
        guard.setattr("urllib.request.urlopen", forbidden_effect)
        for method in ("open", "read_text", "write_text", "mkdir", "unlink"):
            guard.setattr(Path, method, forbidden_effect)
        for operation in ("copy", "copy2", "copytree", "move", "rmtree"):
            guard.setattr(shutil, operation, forbidden_effect)
        for operation in ("replace", "rename", "remove", "unlink", "mkdir", "makedirs"):
            guard.setattr(os, operation, forbidden_effect)

        with pytest.raises(SystemExit) as exc:
            cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "cap-policy install <capability> --policy <policy-file>" in captured.err
    assert attempted_effects == []
    assert marker.read_bytes() == before


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


def test_source_scan_finds_no_active_policy_evaluator_or_workflow_migration() -> None:
    source_root = Path(__file__).parents[2] / "src" / "capacium"
    forbidden_calls = {"enforce_policy", "resolve_capability_info"}
    forbidden_text = {
        "capacium.commands.policy",
        "policy-as-code",
        "policy violation",
        "policy_meta",
    }
    policy_workflow = re.compile(r"policy.*workflow|workflow.*policy", re.IGNORECASE)
    findings: list[str] = []

    for path in sorted(source_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(source_root)
        tree = ast.parse(text, filename=str(relative))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in forbidden_calls:
                findings.append(f"{relative}:{node.lineno}: call:{name}")

        for lineno, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(token in lowered for token in forbidden_text):
                findings.append(f"{relative}:{lineno}: {line.strip()}")
            if policy_workflow.search(line):
                findings.append(f"{relative}:{lineno}: {line.strip()}")

    assert not (source_root / "commands" / "policy.py").exists()
    assert findings == []


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
