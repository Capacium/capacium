"""CAPR3-P01K-A2: No Kind is ever inferred from a repository name.

The P01J review's clean scan was partly illusory: the scanner could not see
``CapaciumKind.<MEMBER>.value``, so the naming heuristic in
``_auto_generate_manifest`` — which guessed a Kind from whether the repository
name happened to contain "mcp", "bundle", "tool", "template", or "workflow" —
was never reported.

A repository name is a naming coincidence, not a declaration. These tests
freeze both halves of the defect:

1. the scanner must detect the ``.value`` accessor form in assignments,
   parameter defaults, conditional cascades, and sink arguments;
2. the ingestion path must fail closed instead of guessing.

No test in this module may be skipped or xfailed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from capacium.commands.install import (
    KindDeclarationRequired,
    _auto_generate_manifest,
    _resolve_declared_kind,
)
from capacium.fallback_inventory import scan_directory
from capacium.kinds import CapaciumKind
from capacium.manifest import Manifest

CANONICAL_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "capacium"

# Names that used to trigger the heuristic, mapped to the Kind they wrongly produced.
INFERENCE_BAIT = [
    ("my-mcp-server", CapaciumKind.MCP.value),
    ("some-mcp", CapaciumKind.MCP.value),
    ("cool-bundle", CapaciumKind.BUNDLE.value),
    ("starter-pack", CapaciumKind.BUNDLE.value),
    ("my-tool", CapaciumKind.TOOL.value),
    ("page-template", CapaciumKind.TEMPLATE.value),
    ("build-workflow", CapaciumKind.WORKFLOW.value),
]


def _scan(code: str):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "probe.py").write_text(code)
        return scan_directory(Path(d))


def _patterns(result) -> set:
    return {f.pattern for f in result.findings}


# ── 1. Scanner sees the .value accessor form ─────────────────────────────


def test_scanner_detects_value_accessor_assignment():
    r = _scan("DEFAULT = CapaciumKind.SKILL.value\n")
    assert "assign-enum-default" in _patterns(r)
    assert not r.is_clean


def test_scanner_detects_value_accessor_parameter_default():
    r = _scan("def fn(kind=CapaciumKind.TOOL.value):\n    return kind\n")
    assert "enum-default" in _patterns(r)
    assert not r.is_clean


def test_scanner_detects_value_accessor_conditional_cascade():
    """The exact shape of the removed install.py heuristic."""
    r = _scan(
        'def infer(name):\n'
        '    kind = CapaciumKind.SKILL.value\n'
        '    if "mcp" in name:\n'
        '        kind = CapaciumKind.MCP.value\n'
        '    elif "bundle" in name:\n'
        '        kind = CapaciumKind.BUNDLE.value\n'
        '    return kind\n'
    )
    assert "enum-conditional" in _patterns(r)
    kinds = {f.resolved_kind for f in r.findings}
    # CAPR3-P01L-B: aliases resolve through the CapaciumKind registry, so
    # CapaciumKind.MCP records its canonical value 'mcp-server' rather than
    # the lowercased member name.
    assert {"skill", "mcp-server", "bundle"} <= kinds
    assert not r.is_clean


def test_scanner_detects_value_accessor_sink_argument():
    r = _scan(
        'def go(adapter, kind=None):\n'
        '    adapter.dispatch(kind or CapaciumKind.SKILL.value)\n'
        '    adapter.install(kind=CapaciumKind.TEMPLATE.value)\n'
    )
    assert "sink-enum-default" in _patterns(r)
    assert {"skill", "template"} <= {f.resolved_kind for f in r.findings}
    assert not r.is_clean


def test_scanner_still_detects_plain_member_form():
    """Extending to `.value` must not regress the original member form."""
    r = _scan("DEFAULT = CapaciumKind.SKILL\n")
    assert "assign-enum-default" in _patterns(r)


def test_canonical_source_has_no_unlisted_kind_defaults():
    """The whole canonical package, rescanned with the extended detector."""
    r = scan_directory(CANONICAL_SRC)
    assert r.violations == [], (
        "unlisted Kind defaults in canonical source:\n  "
        + "\n  ".join(r.violations)
    )
    assert r.is_clean and r.is_inventory_intact


def test_install_module_declares_no_kind_cascade():
    """The removed heuristic must not reappear in the ingestion module."""
    r = scan_directory(CANONICAL_SRC)
    offenders = [
        f for f in r.findings
        if f.file == "commands/install.py"
        and f.pattern in {"assign-enum-default", "enum-conditional",
                          "enum-default", "sink-enum-default"}
    ]
    assert offenders == [], (
        "install.py regained a hardcoded Kind default: "
        + "; ".join(f"{f.line}:{f.pattern}:{f.resolved_kind}" for f in offenders)
    )


# ── 2. Ingestion never infers a Kind from a name ─────────────────────────


@pytest.mark.parametrize("repo_name,formerly_inferred", INFERENCE_BAIT)
def test_repository_name_no_longer_infers_kind(tmp_path, repo_name,
                                               formerly_inferred, monkeypatch):
    """Names containing mcp/bundle/tool/template/workflow infer nothing.

    Each of these names previously produced *formerly_inferred* with no
    declaration anywhere. Now the same name yields no Kind and no manifest.
    """
    from capacium.commands import install as install_mod
    monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])

    repo = tmp_path / repo_name
    repo.mkdir()

    with pytest.raises(KindDeclarationRequired):
        _auto_generate_manifest(repo, f"https://github.com/acme/{repo_name}")

    assert not (repo / "capability.yaml").exists(), (
        f"{repo_name!r} failed closed but still wrote a manifest"
    )
    assert list(repo.iterdir()) == [], (
        f"{repo_name!r} produced a side effect while refusing"
    )


@pytest.mark.parametrize("repo_name,formerly_inferred", INFERENCE_BAIT)
def test_declared_kind_wins_over_suggestive_repository_name(
    tmp_path, repo_name, formerly_inferred
):
    """The name carries no weight even when a Kind *is* declared.

    Every bait name is declared as ``prompt`` — a Kind the old heuristic could
    never produce. If any naming signal still leaked through, the written Kind
    would be *formerly_inferred* instead.
    """
    repo = tmp_path / repo_name
    repo.mkdir()
    _auto_generate_manifest(
        repo, f"https://github.com/acme/{repo_name}",
        registry_meta={"name": repo_name, "owner": "acme",
                       "kind": "prompt", "version": "1.0.0"},
    )
    written = Manifest.load(repo / "capability.yaml").kind
    assert written == "prompt", (
        f"{repo_name!r} leaked a naming signal: got {written!r}, "
        f"expected the declared 'prompt' (old heuristic gave "
        f"{formerly_inferred!r})"
    )


def test_bare_clone_fails_closed_before_any_side_effect(tmp_path, monkeypatch):
    """No manifest write and no network tag fetch before the refusal."""
    from capacium.commands import install as install_mod

    fetched = []
    monkeypatch.setattr(install_mod, "_fetch_remote_tags",
                        lambda url: fetched.append(url) or [])
    repo = tmp_path / "plain-repo"
    repo.mkdir()

    with pytest.raises(KindDeclarationRequired):
        _auto_generate_manifest(repo, "https://github.com/acme/plain-repo")

    assert fetched == [], "tag fetch ran before failing closed"
    assert list(repo.iterdir()) == [], "a side effect escaped the refusal"


def test_unrecognized_source_with_files_still_fails_closed(tmp_path):
    """Content that matches no recognized format declares nothing."""
    repo = tmp_path / "readme-only"
    repo.mkdir()
    (repo / "README.md").write_text("# just docs\n")
    (repo / "main.py").write_text("print('hi')\n")

    with pytest.raises(KindDeclarationRequired) as excinfo:
        _auto_generate_manifest(repo, "https://github.com/acme/readme-only")
    assert "recognized source format" in str(excinfo.value)
    assert not (repo / "capability.yaml").exists()


# ── 2b. Recognized source formats migrate with explicit evidence ─────────


def _write_root_skill(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "SKILL.md").write_text("# a skill\n")


def test_root_skill_md_migrates_with_source_format_evidence(tmp_path,
                                                            monkeypatch):
    """Agent Skills format is a declaration in another vocabulary."""
    import yaml
    from capacium.commands import install as install_mod
    monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])

    repo = tmp_path / "plain-name"
    _write_root_skill(repo)
    _auto_generate_manifest(repo, "https://github.com/acme/plain-name")

    data = yaml.safe_load((repo / "capability.yaml").read_text())
    assert data["kind"] == CapaciumKind.SKILL.value
    evidence = data["x_kind_migration"]
    assert evidence["source_format"] == "agent-skill-md-v1"
    assert evidence["migrated_kind"] == CapaciumKind.SKILL.value
    assert evidence["migration_reason"]


def test_multi_skill_layout_migrates_to_bundle_with_evidence(tmp_path,
                                                             monkeypatch):
    import yaml
    from capacium.commands import install as install_mod
    monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])

    repo = _make_multi_skill_repo(tmp_path, "layout-only")
    _auto_generate_manifest(repo, "https://github.com/acme/layout-only")

    data = yaml.safe_load((repo / "capability.yaml").read_text())
    assert data["kind"] == CapaciumKind.BUNDLE.value
    assert data["x_kind_migration"]["source_format"] == "agent-skills-bundle-v1"
    assert len(data["capabilities"]) == 2


@pytest.mark.parametrize("repo_name,formerly_inferred", INFERENCE_BAIT)
def test_source_format_kind_ignores_the_repository_name(tmp_path, repo_name,
                                                        formerly_inferred,
                                                        monkeypatch):
    """A root SKILL.md yields 'skill' no matter what the repo is called.

    Under the old heuristic these names produced mcp-server, bundle, tool,
    template, or workflow. Structure now decides, so every one of them is a
    skill.
    """
    import yaml
    from capacium.commands import install as install_mod
    monkeypatch.setattr(install_mod, "_fetch_remote_tags", lambda url: [])

    repo = tmp_path / repo_name
    _write_root_skill(repo)
    _auto_generate_manifest(repo, f"https://github.com/acme/{repo_name}")

    data = yaml.safe_load((repo / "capability.yaml").read_text())
    assert data["kind"] == CapaciumKind.SKILL.value, (
        f"{repo_name!r} leaked a naming signal: got {data['kind']!r}, "
        f"old heuristic gave {formerly_inferred!r}"
    )


def test_declared_kind_outranks_source_format(tmp_path):
    """An explicit declaration wins over structural format evidence."""
    import yaml

    repo = tmp_path / "declared-over-format"
    _write_root_skill(repo)
    _auto_generate_manifest(
        repo, "https://github.com/acme/declared-over-format",
        registry_meta={"name": "declared-over-format", "owner": "acme",
                       "kind": "prompt", "version": "1.0.0"},
    )
    data = yaml.safe_load((repo / "capability.yaml").read_text())
    assert data["kind"] == "prompt"
    assert "x_kind_migration" not in data


def test_source_format_migration_adapter_is_canonical():
    """Source-format migration lives in the canonical Kind authority."""
    from capacium.kinds import (
        migrate_source_format_kind, recognized_source_formats,
    )

    assert "agent-skill-md-v1" in recognized_source_formats()
    result = migrate_source_format_kind("agent-skill-md-v1")
    assert result.migrated_kind is CapaciumKind.SKILL
    assert result.source_format == "agent-skill-md-v1"
    assert result.warnings

    with pytest.raises(ValueError, match="not a recognized source format"):
        migrate_source_format_kind("invented-format-v9")


def test_refusal_message_is_actionable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(KindDeclarationRequired) as excinfo:
        _auto_generate_manifest(repo, "https://github.com/acme/repo")
    message = str(excinfo.value)
    assert "capability.yaml" in message
    assert "kind" in message
    assert "does not infer" in message
    for kind in ("skill", "bundle", "mcp-server"):
        assert kind in message, f"valid kind {kind} missing from guidance"


def test_existing_manifest_is_left_untouched(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "capability.yaml").write_text(
        "kind: skill\nname: existing\ndescription: original\n"
    )
    _auto_generate_manifest(repo, "https://github.com/x/y.git")
    assert "original" in (repo / "capability.yaml").read_text()


# ── 3. Explicit declarations are honoured and validated ──────────────────


@pytest.mark.parametrize("declared", sorted({k.value for k in CapaciumKind}))
def test_declared_kind_is_used_verbatim(tmp_path, declared):
    repo = tmp_path / "declared"
    repo.mkdir()
    _auto_generate_manifest(
        repo, "https://github.com/acme/declared",
        registry_meta={"name": "declared", "owner": "acme",
                       "kind": declared, "version": "1.0.0"},
    )
    assert Manifest.load(repo / "capability.yaml").kind == declared


def test_declared_kind_is_normalized(tmp_path):
    repo = tmp_path / "norm"
    repo.mkdir()
    _auto_generate_manifest(
        repo, "https://github.com/acme/norm",
        registry_meta={"name": "norm", "owner": "acme", "kind": "SKILL",
                       "version": "1.0.0"},
    )
    assert Manifest.load(repo / "capability.yaml").kind == "skill"


@pytest.mark.parametrize("bad", ["nonsense", "skil", "SKILL_TYPO"])
def test_unknown_declared_kind_is_rejected(tmp_path, bad):
    repo = tmp_path / "bad"
    repo.mkdir()
    with pytest.raises(ValueError, match="Unknown kind"):
        _auto_generate_manifest(
            repo, "https://github.com/acme/bad",
            registry_meta={"name": "bad", "owner": "acme", "kind": bad},
        )
    assert not (repo / "capability.yaml").exists()


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_registry_entry_without_kind_fails_closed(tmp_path, empty):
    repo = tmp_path / "nokind"
    repo.mkdir()
    with pytest.raises(KindDeclarationRequired):
        _auto_generate_manifest(
            repo, "https://github.com/acme/nokind",
            registry_meta={"name": "nokind", "owner": "acme", "kind": empty},
        )
    assert not (repo / "capability.yaml").exists()


# ── 4. Legacy Kinds only via the canonical versioned migration adapter ───


@pytest.mark.parametrize("legacy", ["operator", "checkpoint", "policy"])
def test_legacy_kind_goes_through_versioned_migration(tmp_path, legacy):
    repo = tmp_path / "legacy"
    repo.mkdir()
    if legacy == "policy":
        with pytest.raises(ValueError, match="external install-policy"):
            _auto_generate_manifest(
                repo, "https://github.com/acme/legacy",
                registry_meta={
                    "name": "legacy",
                    "owner": "acme",
                    "kind": legacy,
                    "version": "1.0.0",
                },
            )
        assert not (repo / "capability.yaml").exists()
        return
    _auto_generate_manifest(
        repo, "https://github.com/acme/legacy",
        registry_meta={"name": "legacy", "owner": "acme", "kind": legacy,
                       "version": "1.0.0"},
    )
    manifest = Manifest.load(repo / "capability.yaml")
    assert manifest.kind == CapaciumKind.WORKFLOW.value
    assert manifest.validate() == []


@pytest.mark.parametrize("legacy", ["operator", "checkpoint", "policy"])
def test_legacy_migration_records_source_format_evidence(tmp_path, legacy):
    """A migrated Kind must carry explicit source-format evidence."""
    import yaml

    repo = tmp_path / "legacy-ev"
    repo.mkdir()
    if legacy == "policy":
        with pytest.raises(ValueError, match="external install-policy"):
            _auto_generate_manifest(
                repo, "https://github.com/acme/legacy-ev",
                registry_meta={
                    "name": "legacy-ev",
                    "owner": "acme",
                    "kind": legacy,
                    "version": "1.0.0",
                },
            )
        assert not (repo / "capability.yaml").exists()
        return
    _auto_generate_manifest(
        repo, "https://github.com/acme/legacy-ev",
        registry_meta={"name": "legacy-ev", "owner": "acme", "kind": legacy,
                       "version": "1.0.0"},
    )
    data = yaml.safe_load((repo / "capability.yaml").read_text())
    evidence = data["x_kind_migration"]
    assert evidence["original_kind"] == legacy
    assert evidence["migrated_kind"] == CapaciumKind.WORKFLOW.value
    assert evidence["source_format"] == "registry-metadata-v1"
    assert evidence["migration_reason"]


def test_canonical_kind_records_no_migration_evidence(tmp_path):
    import yaml

    repo = tmp_path / "plain"
    repo.mkdir()
    _auto_generate_manifest(
        repo, "https://github.com/acme/plain",
        registry_meta={"name": "plain", "owner": "acme", "kind": "skill",
                       "version": "1.0.0"},
    )
    data = yaml.safe_load((repo / "capability.yaml").read_text())
    assert "x_kind_migration" not in data


def test_resolve_declared_kind_returns_migration_evidence():
    kind, migration = _resolve_declared_kind(
        "operator", origin="probe", source_format="probe-format-v1"
    )
    assert kind == CapaciumKind.WORKFLOW.value
    assert migration is not None
    assert migration.source_format == "probe-format-v1"
    assert migration.original_kind == "operator"


def test_resolve_declared_kind_canonical_has_no_evidence():
    kind, migration = _resolve_declared_kind(
        "skill", origin="probe", source_format="probe-format-v1"
    )
    assert kind == "skill" and migration is None


# ── 5. Structural layout never silently re-Kinds a declaration ───────────


def _make_multi_skill_repo(root: Path, name: str) -> Path:
    repo = root / name
    for member in ("alpha", "beta"):
        (repo / "skills" / member).mkdir(parents=True)
        (repo / "skills" / member / "SKILL.md").write_text("# x\n")
    return repo


def test_declared_bundle_attaches_discovered_members(tmp_path):
    repo = _make_multi_skill_repo(tmp_path, "multi")
    _auto_generate_manifest(
        repo, "https://github.com/acme/multi",
        registry_meta={"name": "multi", "owner": "acme", "kind": "bundle",
                       "version": "1.0.0"},
    )
    manifest = Manifest.load(repo / "capability.yaml")
    assert manifest.kind == "bundle"
    assert len(manifest.capabilities) == 2


def test_declared_skill_is_not_silently_promoted_to_bundle(tmp_path, capsys):
    """An explicit declaration outranks structural evidence."""
    repo = _make_multi_skill_repo(tmp_path, "multi-skill-decl")
    _auto_generate_manifest(
        repo, "https://github.com/acme/multi-skill-decl",
        registry_meta={"name": "multi-skill-decl", "owner": "acme",
                       "kind": "skill", "version": "1.0.0"},
    )
    manifest = Manifest.load(repo / "capability.yaml")
    assert manifest.kind == "skill", "declared Kind was silently overridden"
    assert "Declare kind: bundle" in capsys.readouterr().out


# ── 6. The init wizard exception is genuinely interactive ────────────────


def test_p01k_init_wizard_kind_is_interactive_only(monkeypatch, tmp_path):
    """Exact test proof for the commands/init.py KNOWN_EXCEPTIONS entry.

    The seed Kind must only ever pre-fill a prompt: the operator sees every
    active Kind, their answer overrides the seed, and the result is validated.
    """
    from capacium.commands import init as init_mod

    shown, answers = [], {
        "Capability name (kebab-case)": "chosen-cap",
        "Kind": "workflow",              # operator overrides the seed
    }

    def fake_prompt_with_default(label, default=""):
        shown.append((label, default))
        return answers.get(label, "")

    monkeypatch.setattr(init_mod, "_prompt_with_default", fake_prompt_with_default)
    monkeypatch.setattr(init_mod, "_prompt_required",
                        lambda label, default="": answers.get(label, "x"))
    monkeypatch.chdir(tmp_path)

    captured = {}
    real_validate = Manifest.validate

    def spy_validate(self):
        captured["kind"] = self.kind
        captured["errors"] = real_validate(self)
        return captured["errors"]

    monkeypatch.setattr(Manifest, "validate", spy_validate)
    init_mod.init_skill()

    kind_prompts = [d for label, d in shown if label == "Kind"]
    assert kind_prompts == [CapaciumKind.SKILL.value], (
        "the seed Kind must be offered as a prompt default, not applied silently"
    )
    assert captured["kind"] == "workflow", (
        "operator's answer must override the seed Kind"
    )
    assert captured["errors"] == []


def test_init_wizard_displays_every_active_kind(monkeypatch, tmp_path, capsys):
    from capacium.commands import init as init_mod

    monkeypatch.setattr(init_mod, "_prompt_with_default",
                        lambda label, default="": "")
    monkeypatch.setattr(init_mod, "_prompt_required",
                        lambda label, default="": "cap")
    monkeypatch.chdir(tmp_path)
    init_mod.init_skill()

    out = capsys.readouterr().out
    for kind in {k.value for k in CapaciumKind}:
        assert kind in out, f"wizard never showed the operator kind {kind!r}"


def test_init_wizard_rejects_an_invalid_operator_kind(monkeypatch, tmp_path):
    """A bad answer is caught by validation, so the seed never masks it."""
    from capacium.commands import init as init_mod

    answers = {"Kind": "nonsense"}
    monkeypatch.setattr(init_mod, "_prompt_with_default",
                        lambda label, default="": answers.get(label, ""))
    monkeypatch.setattr(init_mod, "_prompt_required",
                        lambda label, default="": "cap")
    monkeypatch.chdir(tmp_path)

    errors_seen = {}
    real_validate = Manifest.validate

    def spy_validate(self):
        errors_seen["errors"] = real_validate(self)
        return errors_seen["errors"]

    monkeypatch.setattr(Manifest, "validate", spy_validate)
    init_mod.init_skill()

    assert errors_seen["errors"], "invalid operator Kind passed validation"
    assert "Unknown kind" in errors_seen["errors"][0]
