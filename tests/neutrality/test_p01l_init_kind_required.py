"""CAPR3-P01L-B: `cap init` never assumes a Kind.

The non-interactive path used to run ``kind = kind or CapaciumKind.SKILL.value``,
so ``cap init --name x`` silently declared a Kind the author never chose and
persisted it into the generated manifest. That default is removed: omitting
``--kind`` now fails closed.

The interactive prompt keeps a default, and this module is the exact test
proof for its ``KNOWN_EXCEPTIONS`` entry. It must show that the default only
pre-fills a prompt the operator can override, and that the answer is validated.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import pytest

from capacium.commands import init as init_mod
from capacium.kinds import ACTIVE_KINDS, CapaciumKind


# ── Non-interactive path fails closed ────────────────────────────────────


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_non_interactive_init_requires_kind(tmp_path, monkeypatch, capsys,
                                            missing):
    monkeypatch.chdir(tmp_path)
    ok = init_mod.init_capability(name="my-cap", kind=missing)

    assert ok is False, "cap init assumed a Kind instead of failing closed"
    out = capsys.readouterr().out
    assert "--kind is required" in out
    assert "does not assume a Kind" in out
    assert not (tmp_path / "capability.yaml").exists(), (
        "a refused init still wrote a manifest"
    )


def test_refusal_lists_valid_kinds(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init_mod.init_capability(name="my-cap", kind=None)
    out = capsys.readouterr().out
    for kind in ("skill", "bundle", "mcp-server"):
        assert kind in out, f"guidance omitted valid kind {kind!r}"


@pytest.mark.parametrize("declared", sorted(ACTIVE_KINDS))
def test_non_interactive_init_accepts_every_active_kind(tmp_path, monkeypatch,
                                                        declared):
    monkeypatch.chdir(tmp_path)
    ok = init_mod.init_capability(name="my-cap", kind=declared)
    assert ok is True
    written = (tmp_path / "capability.yaml").read_text()
    assert f"kind: {declared}" in written


def test_non_interactive_init_rejects_unknown_kind(tmp_path, monkeypatch,
                                                   capsys):
    monkeypatch.chdir(tmp_path)
    ok = init_mod.init_capability(name="my-cap", kind="nonsense")
    assert ok is False
    assert "invalid kind" in capsys.readouterr().out
    assert not (tmp_path / "capability.yaml").exists()


def test_capability_name_never_influences_kind(tmp_path, monkeypatch):
    """A bait name must not resurrect inference through the init path."""
    monkeypatch.chdir(tmp_path)
    ok = init_mod.init_capability(name="my-mcp-tool-bundle", kind="prompt")
    assert ok is True
    assert "kind: prompt" in (tmp_path / "capability.yaml").read_text()


# ── Interactive prompt: exact proof for the KNOWN_EXCEPTIONS entry ───────


def test_p01l_init_prompt_default_is_interactive_only(tmp_path, monkeypatch,
                                                      capsys):
    """Exact test proof for the commands/init.py `or-default` exception.

    The seed may only pre-fill a prompt: the operator sees every active Kind,
    a typed answer replaces the seed, and the answer is validated.
    """
    monkeypatch.chdir(tmp_path)
    answers = iter([
        "chosen-cap",   # Name
        "workflow",     # Kind — overrides the 'skill' default
        "1.0.0",        # Version
        "",             # Description
        "",             # Owner
        "",             # Frameworks
        "",             # Runtimes
    ])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    init_mod.init_capability()

    written = (tmp_path / "capability.yaml").read_text()
    assert "kind: workflow" in written, (
        "the operator's answer must override the prompt default"
    )
    assert "kind: skill" not in written

    shown = capsys.readouterr().out
    for kind in ACTIVE_KINDS:
        assert kind in shown, f"operator was never shown kind {kind!r}"


def test_interactive_prompt_default_applies_on_empty_answer(tmp_path,
                                                            monkeypatch):
    """Pressing enter accepts the displayed default — visibly, not silently."""
    monkeypatch.chdir(tmp_path)
    answers = iter(["chosen-cap", "", "1.0.0", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    init_mod.init_capability()

    written = (tmp_path / "capability.yaml").read_text()
    assert f"kind: {CapaciumKind.SKILL.value}" in written


def test_interactive_prompt_reprompts_on_invalid_kind(tmp_path, monkeypatch,
                                                      capsys):
    """An invalid answer is rejected, so the default never masks it."""
    monkeypatch.chdir(tmp_path)
    answers = iter([
        "chosen-cap", "nonsense", "tool", "1.0.0", "", "", "", "",
    ])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    init_mod.init_capability()

    assert "invalid kind" in capsys.readouterr().out
    assert "kind: tool" in (tmp_path / "capability.yaml").read_text()
