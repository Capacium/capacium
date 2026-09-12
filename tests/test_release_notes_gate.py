"""Release-notes quality and gate mechanics.

Locks the contract that replaced commit-log-generated release bodies:

* the release body is the CHANGELOG entry for the tag (extraction),
* a missing or empty entry fails before any release object exists,
* the external-audience gate rejects a body naming this repository's tracker,
* the release title is product-native ``Capacium vX.Y.Z``,
* neither release workflow generates notes from ``git log`` again.

These are static/deterministic checks plus direct unit tests of the committed
extractor; they do not invoke a forge or the network.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
EXTRACTOR = SCRIPTS_DIR / "extract_changelog_notes.py"
PREFIX_EXTRACTOR = SCRIPTS_DIR / "extract_tracker_prefixes.py"
OPS_YAML = REPO_ROOT / ".ops.yaml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
FORGEJO_WORKFLOW = REPO_ROOT / ".forgejo" / "workflows" / "forgejo-release.yml"
GITHUB_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

TITLE_RE = re.compile(r"^Capacium v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$")


def _load_extractor():
    spec = importlib.util.spec_from_file_location(
        "extract_changelog_notes", EXTRACTOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_prefix_extractor():
    spec = importlib.util.spec_from_file_location(
        "extract_tracker_prefixes", PREFIX_EXTRACTOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ops_engine_gate() -> Path | None:
    gate = Path(
        "/Users/andrelange/Documents/repositories/forgejo/langevc"
        "/ops-engine/scripts/release_notes_audience_gate.py"
    )
    return gate if gate.is_file() else None


def _workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_step_script(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class TestChangelogExtraction:
    def test_extracts_v1_1_1_section(self):
        extractor = _load_extractor()
        notes = extractor.extract_notes_for_tag("v1.1.1", CHANGELOG)
        assert notes.startswith("If you publish capabilities from a script")
        # The next version's heading is not part of this section.
        assert "CLI payloads, mirror preflight" not in notes
        assert "### Upgrade" in notes

    def test_extracts_bracketed_old_style_heading(self):
        extractor = _load_extractor()
        notes = extractor.extract_notes(
            "## [Capacium v0.7.3] - 2026-04-26\n\n### Fixed\n- thing\n",
            "0.7.3",
        )
        assert notes == "### Fixed\n- thing"

    def test_missing_section_raises(self):
        extractor = _load_extractor()
        with pytest.raises(extractor.MissingChangelogEntryError):
            extractor.extract_notes("## Capacium v1.0.0\n\nnotes\n", "9.9.9")

    def test_empty_section_raises(self):
        extractor = _load_extractor()
        with pytest.raises(extractor.MissingChangelogEntryError):
            extractor.extract_notes(
                "## Capacium v1.2.3\n\n## Capacium v1.2.2\n\nnotes\n", "1.2.3"
            )

    def test_cli_missing_section_exits_nonzero(self):
        result = _run_step_script(
            "python3 scripts/extract_changelog_notes.py v9.9.9"
        )
        assert result.returncode == 2
        assert "MissingChangelogEntryError" in result.stderr
        assert result.stdout == ""

    def test_cli_existing_section_exits_zero(self):
        result = _run_step_script(
            "python3 scripts/extract_changelog_notes.py v1.1.1"
        )
        assert result.returncode == 0
        assert result.stdout.startswith("If you publish capabilities")


class TestExtractorIsSyntacticallyValid:
    def test_extractor_parses_as_python(self):
        ast.parse(EXTRACTOR.read_text(encoding="utf-8"))


class TestExternalAudienceVocabulary:
    def test_ops_yaml_exists_and_declares_prefixes(self):
        assert OPS_YAML.is_file()
        text = OPS_YAML.read_text(encoding="utf-8")
        assert "tracker_prefixes:" in text

    def test_real_prefix_parser_reads_committed_ops_yaml(self):
        prefix_extractor = _load_prefix_extractor()
        prefixes = prefix_extractor.load_tracker_prefixes(
            OPS_YAML.read_text(encoding="utf-8")
        )
        assert prefixes
        assert "CAP" in prefixes
        assert "CI" in prefixes
        assert all(prefix_extractor._PREFIX_TOKEN_RE.fullmatch(p) for p in prefixes)

    def test_prefix_parser_handles_block_and_inline_forms(self):
        prefix_extractor = _load_prefix_extractor()
        block = "tracker_prefixes:\n  - CAP\n  - EX\n  - CI\n"
        assert prefix_extractor.load_tracker_prefixes(block) == ["CAP", "EX", "CI"]
        inline = "tracker_prefixes: [CAP, EX, CI]\n"
        assert prefix_extractor.load_tracker_prefixes(inline) == ["CAP", "EX", "CI"]

    def test_prefix_parser_fails_closed(self):
        prefix_extractor = _load_prefix_extractor()
        for bad in ("", "other_key: 1\n", "tracker_prefixes:\n"):
            with pytest.raises(prefix_extractor.MissingTrackerPrefixesError):
                prefix_extractor.load_tracker_prefixes(bad)

    def test_prefix_parser_cli_missing_ops_fails(self):
        result = _run_step_script(
            "python3 scripts/extract_tracker_prefixes.py --ops /nope.yaml"
        )
        assert result.returncode == 2
        assert "MissingTrackerPrefixesError" in result.stderr

    def test_prefix_parser_cli_writes_one_prefix_per_line(self):
        result = _run_step_script(
            "python3 scripts/extract_tracker_prefixes.py"
        )
        assert result.returncode == 0
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert "CAP" in lines
        assert all(
            re.fullmatch(r"[A-Z]{2,5}", ln) for ln in lines
        )

    def test_current_v1_1_1_notes_pass_the_gate(self, tmp_path):
        gate = _ops_engine_gate()
        if gate is None:
            pytest.skip("ops-engine canonical checkout not present")
        notes = _load_extractor().extract_notes_for_tag("v1.1.1", CHANGELOG)
        notes_file = tmp_path / "notes.md"
        notes_file.write_text(notes, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(gate), str(notes_file)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_committed_prefixes_feed_the_gate_and_reject(self, tmp_path):
        """The real .ops.yaml vocabulary, fed through the shared parser, makes
        the gate reject a body naming this repository's tracker."""
        gate = _ops_engine_gate()
        if gate is None:
            pytest.skip("ops-engine canonical checkout not present")
        prefix_extractor = _load_prefix_extractor()
        prefixes = prefix_extractor.load_tracker_prefixes(
            OPS_YAML.read_text(encoding="utf-8")
        )
        prefixes_file = tmp_path / "prefixes.txt"
        prefixes_file.write_text("\n".join(prefixes) + "\n", encoding="utf-8")
        notes_file = tmp_path / "bad.md"
        notes_file.write_text("This fixes CAP-123 end to end.\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(gate),
                "--ticket-prefixes",
                str(prefixes_file),
                str(notes_file),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "ReleaseNotesAudienceError" in result.stderr

    def test_a_body_naming_this_tracker_is_rejected(self, tmp_path):
        gate = _ops_engine_gate()
        if gate is None:
            pytest.skip("ops-engine canonical checkout not present")
        notes_file = tmp_path / "bad.md"
        notes_file.write_text("This fixes CAP-CI-003.\n", encoding="utf-8")
        prefixes_file = tmp_path / "prefixes.txt"
        prefixes_file.write_text("CAP\nCI\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(gate),
                "--ticket-prefixes",
                str(prefixes_file),
                str(notes_file),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "ReleaseNotesAudienceError" in result.stderr


class TestCanonicalTitle:
    def test_title_shape_is_product_native(self):
        assert TITLE_RE.match("Capacium v1.1.1")
        assert TITLE_RE.match("Capacium v1.1.2-rc1")
        assert not TITLE_RE.match("Capacium 1.1.1")
        assert not TITLE_RE.match("v1.1.1")
        assert not TITLE_RE.match("Capacium vv1.1.1")

    def test_forgejo_gate_uses_product_native_title(self):
        text = _workflow_text(FORGEJO_WORKFLOW)
        assert r"^Capacium v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$" in text
        assert 'RELEASE_NAME="Capacium ${TAG_NAME}"' in text

    def test_github_release_uses_canonical_title(self):
        workflow = yaml.safe_load(_workflow_text(GITHUB_WORKFLOW))
        steps = workflow["jobs"]["create-release"]["steps"]
        release = next(
            step for step in steps if step.get("name") == "Create GitHub Release"
        )
        assert release["with"]["name"] == "Capacium ${{ github.ref_name }}"


class TestNoCommitDumpGeneration:
    def test_forgejo_workflow_has_no_git_log_notes(self):
        text = _workflow_text(FORGEJO_WORKFLOW)
        assert "git log" not in text
        assert "What's Changed" not in text

    def test_github_workflow_has_no_git_log_notes(self):
        text = _workflow_text(GITHUB_WORKFLOW)
        assert "git log --oneline" not in text

    def test_both_workflows_use_the_shared_extractor(self):
        for path in (FORGEJO_WORKFLOW, GITHUB_WORKFLOW):
            assert "scripts/extract_changelog_notes.py" in _workflow_text(path)

    def test_both_workflows_use_the_shared_prefix_parser(self):
        for path in (FORGEJO_WORKFLOW, GITHUB_WORKFLOW):
            assert "scripts/extract_tracker_prefixes.py" in _workflow_text(path)

    def test_no_inline_duplicated_prefix_parser_remains(self):
        # The first version embedded its own .ops.yaml parser as a heredoc; that
        # drifted from the real block-list syntax. Both forges must call the one
        # committed parser instead of carrying a second copy.
        for path in (FORGEJO_WORKFLOW, GITHUB_WORKFLOW):
            assert "tracker_prefixes:" not in _workflow_text(path)


class TestForgejoIdempotentPath:
    def test_patch_writes_title_and_body(self):
        workflow = yaml.safe_load(_workflow_text(FORGEJO_WORKFLOW))
        step = next(
            step
            for step in workflow["jobs"]["release"]["steps"]
            if step.get("name") == "Create or re-assert the Forgejo release"
        )
        script = step["run"]
        # The 409/422 branch PATCHes both fields, not the title alone.
        patch_block = script.split("PATCH_PAYLOAD=", 1)[1]
        assert "--arg name " in patch_block
        assert "--arg body " in patch_block
        assert "{name: $name, body: $body}" in patch_block


class TestGateFetchIsProvenBeforeExecution:
    def test_forgejo_fetches_and_ast_checks_gate(self):
        text = _workflow_text(FORGEJO_WORKFLOW)
        assert "release_notes_audience_gate.py" in text
        assert "ast.parse" in text
        assert "--ticket-prefixes" in text
        assert ".ops.yaml" in text

    def test_github_fetches_ast_checks_and_runs_gate(self):
        text = _workflow_text(GITHUB_WORKFLOW)
        assert "release_notes_audience_gate.py" in text
        assert "ast.parse" in text
        assert "--ticket-prefixes" in text
        # The gate must run BEFORE the release is created, i.e. in the same
        # "Generate and gate release notes" step that precedes action-gh-release.
        workflow = yaml.safe_load(text)
        steps = workflow["jobs"]["create-release"]["steps"]
        names = [step.get("name", "") for step in steps]
        gate_idx = names.index("Generate and gate release notes")
        release_idx = names.index("Create GitHub Release")
        assert gate_idx < release_idx

    def test_no_hardcoded_credentials_in_release_workflows(self):
        for path in (FORGEJO_WORKFLOW, GITHUB_WORKFLOW):
            text = _workflow_text(path)
            # No token-shaped literal (a pasted credential) may appear; the
            # only acceptable sources are a workflow expression or an
            # environment variable populated from one.
            assert "ghp_" not in text
            assert "github_pat_" not in text
            for line in text.splitlines():
                if "Authorization:" in line and "token" in line.lower():
                    assert (
                        "${{" in line or "${GITHUB_TOKEN}" in line
                    ), line


class TestPostTagTruth:
    def test_full_changelog_links_to_main_not_tag(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        # The expanded entry is post-tag; the tag still holds the short entry,
        # so the "full changelog" link must resolve to main, never the tag blob.
        assert "blob/main/CHANGELOG.md" in text
        assert "blob/v1.1.1/CHANGELOG.md" not in text

    def test_editorial_correction_note_present(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        assert "Editorial note" in text
        assert "immutable" in text and "v1.1.1" in text
        assert "after the" in text

    def test_gate_mechanics_moved_to_unreleased(self):
        # The changelog-extraction and audience-gate tooling was not in the
        # v1.1.1 tag; it is future work, so it belongs under "Unreleased", not
        # inside the v1.1.1 entry.
        text = CHANGELOG.read_text(encoding="utf-8")
        unreleased = text.split("## Unreleased", 1)[1].split("## Capacium v1.1.1", 1)[0]
        assert "changelog" in unreleased.lower()
        assert "audience" in unreleased.lower()
        v1_1_1 = text.split("## Capacium v1.1.1", 1)[1].split("## Capacium v1.1.0", 1)[0]
        assert "External-audience gate" not in v1_1_1
        assert "from this changelog" not in v1_1_1

    def test_v1_1_1_entry_is_reader_facing(self):
        v1_1_1 = CHANGELOG.read_text(encoding="utf-8").split(
            "## Capacium v1.1.1", 1
        )[1].split("## Capacium v1.1.0", 1)[0]
        # No internal ticket identifiers of the form PREFIX-digits.
        assert not re.search(r"[A-Z]{2,5}-\d+", v1_1_1)
