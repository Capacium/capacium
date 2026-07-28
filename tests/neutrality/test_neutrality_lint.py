"""Neutrality CI lint tests — positive and negative fixtures."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

LINT_SCRIPT = Path(__file__).resolve().parents[2] / "contrib" / "neutrality-lint.py"


def _run_lint_on(content: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, prefix="neut_lint_"
    ) as tmpf:
        tmpf.write(content)
        tmpf.flush()
        tmp_path = Path(tmpf.name)
    try:
        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT), str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=LINT_SCRIPT.parents[1],
        )
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


class TestNegativeFixtures:
    def test_process_kind_rejected(self):
        content = """
kinds = {"process": "a process kind in Core is forbidden"}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"
        assert "process Kind" in result.stdout

    def test_executeLocal_rejected(self):
        content = """
def do_thing():
    executeLocal("some_action")
"""
        result = _run_lint_on(content)
        assert result.returncode != 0
        assert "executeLocal" in result.stdout

    def test_premiumSupport_rejected(self):
        content = """
class SupportTier:
    premiumSupport = True
"""
        result = _run_lint_on(content)
        assert result.returncode != 0
        assert "premiumSupport" in result.stdout

    PERMITTED_REJECTED_CASES = [
        "PERMITTED = 'allowed'",
        "RESTRICTED = 'denied'",
        "PERMITTED_WITH_WARNING = 'warn'",
        "EntitlementDecision = namedtuple('EntitlementDecision', ['ok'])",
    ]

    @pytest.mark.parametrize("evil_line", PERMITTED_REJECTED_CASES)
    def test_authorization_constants_rejected(self, evil_line):
        content = f"\n{evil_line}\n"
        result = _run_lint_on(content)
        assert result.returncode != 0, f"Expected rejection of: {evil_line}"
        assert result.stdout != ""

    def test_entitlement_literals_rejected(self):
        content = """
def check_entitlement(user):
    pass
"""
        result = _run_lint_on(content)
        assert result.returncode != 0
        assert "entitlement" in result.stdout

    def test_entitlement_in_trust_module_rejected(self):
        content = """
class TrustResult:
    has_entitlement = False
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "Entitlement inside trust module must be rejected"

    def test_entitlement_via_alias_rejected(self):
        content = """
PermissionGrant = namedtuple('EntitlementDecision', ['ok'])

def check(policy):
    return policy.executeLocal("something")
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "Alias-isolated prohibited terms must be rejected"
        assert "EntitlementDecision" in result.stdout
        assert "executeLocal" in result.stdout

    ENTITLEMENT_CASING_VARIANTS = [
        "Entitlement = 'granted'",
        "ENTITLEMENT = 1",
        "EntitleMentDecision = True",
    ]

    @pytest.mark.parametrize("line", ENTITLEMENT_CASING_VARIANTS)
    def test_entitlement_casing_variants_rejected(self, line):
        content = f"\n{line}\n"
        result = _run_lint_on(content)
        assert result.returncode != 0, f"Casing variant must be rejected: {line}"
        assert "entitlement" in result.stdout.lower()

    def test_imported_entitlement_symbol_rejected(self):
        content = """
from other.module import EntitlementDecision as ED

result = ED(ok=True)
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "Imported entitlement symbol must be rejected"
        assert "EntitlementDecision" in result.stdout

    SKILLWEAVE_IMPORT_CASES = [
        "import skillweave\n",
        "import skillweave.core\n",
        "from skillweave import lifecycle\n",
        "from skillweave.core import Bundle\n",
    ]

    @pytest.mark.parametrize("import_line", SKILLWEAVE_IMPORT_CASES)
    def test_skillweave_dependency_rejected(self, import_line):
        result = _run_lint_on(import_line)
        assert result.returncode != 0, f"Expected rejection of: {import_line!r}"
        assert "PROHIBITED_DEPENDENCY" in result.stdout
        assert "SkillWeave" in result.stdout

    ELEMENTEER_IMPORT_CASES = [
        "import elementeer\n",
        "import elementeer.client\n",
        "from elementeer import wizard\n",
        "from elementeer.api import Client\n",
    ]

    @pytest.mark.parametrize("import_line", ELEMENTEER_IMPORT_CASES)
    def test_elementeer_dependency_rejected(self, import_line):
        result = _run_lint_on(import_line)
        assert result.returncode != 0, f"Expected rejection of: {import_line!r}"
        assert "PROHIBITED_DEPENDENCY" in result.stdout
        assert "Elementeer" in result.stdout


class TestPositiveFixtures:
    def test_clean_python_passes(self):
        content = """
def hello():
    return "capacium"
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, f"Clean file should pass: {result.stdout}"

    def test_known_benign_literals(self):
        content = """
# These look like prohibited terms but should NOT match
def process_item(item):
    pass

class Kind(Enum):
    SKILL = "skill"
    BUNDLE = "bundle"
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, f"Benign file should pass: {result.stdout}"

    def test_descriptive_docstring_passes(self):
        content = '"""Does NOT contain entitlement, permit, deny decisions."""\n'
        result = _run_lint_on(content)
        assert result.returncode == 0, f"Descriptive docstring should pass: {result.stdout}"

    def test_trust_boundary_docstring_passes(self):
        content = '''
class EvidenceVerificationResult:
    """Core boundary result.

    Contains ONLY verification facts. Does NOT contain:
    - permit/deny decisions
    - entitlement or authorization claims
    - commercial actions
    - lifecycle transitions
    """
    status: str = "VALID"
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, f"Trust boundary docstring should pass: {result.stdout}"

    def test_legacy_reference_docstring_passes(self):
        content = '''
class LegacyAdapter:
    """Reads R4 legacy evidence.

    Does NOT interpret entitlement decisions or commercial actions.
    Preserves opaque bytes for migration only.
    """
    pass
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, f"Legacy reference docstring should pass: {result.stdout}"

    def test_actual_core_passes(self):
        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=LINT_SCRIPT.parents[1],
        )
        assert result.returncode == 0, (
            f"Actual Core src/ must pass neutrality lint.\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


class TestCIPChecklist:
    def test_cip_changed_kind_requires_assessment(self):
        cip_path = (
            Path(__file__).resolve().parents[2] / "CIP-0001-NEUTRALITY-CHECKLIST.md"
        )
        assert cip_path.is_file(), (
            "CIP-0001-NEUTRALITY-CHECKLIST.md must exist (neutrality-impact template)"
        )
        content = cip_path.read_text()
        for required_term in (
            "neutrality",
            "Kind",
            "trust",
            "product",
            "SkillWeave",
            "Elementeer",
            "evidence",
        ):
            assert required_term.lower() in content.lower(), (
                f"CIP checklist must reference '{required_term}'"
            )
