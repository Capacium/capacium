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


# ── CAP117F-CORE-001 criterion 5: negative controls for commercial license boundary ──


class TestCommercialLicenseNegativeControls:
    """Criterion 5: each prohibited commercial pattern injected into a temporary
    Core file must produce a non-zero exit and a stable diagnostic naming the
    violated boundary."""

    def test_licensee_id_rejected(self):
        content = """
def check_access():
    return {"licensee_id": "cust_abc123"}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "licensee_id must be rejected"
        assert "licensee_id" in result.stdout.lower()
        assert "commercial license identifier" in result.stdout.lower()

    def test_license_type_rejected(self):
        content = """
LICENSE_TYPE_MAP = {"pro": "commercial"}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "license_type must be rejected"
        assert "license_type" in result.stdout.lower()
        assert "commercial license type" in result.stdout.lower()

    def test_v2_licenses_path_rejected(self):
        content = '''
def fetch_license(token):
    return requests.get("/v2/licenses/validate", headers={"Authorization": f"Bearer {token}"})
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, "/v2/licenses must be rejected"
        assert "/v2/licenses" in result.stdout
        assert "commercial" in result.stdout.lower()

    def test_paid_license_rejected(self):
        content = """
class CapabilityLicense:
    status = "paid_license"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "paid_license must be rejected"
        assert "paid_license" in result.stdout
        assert "paid-license" in result.stdout.lower()

    def test_LicenseTier_enum_rejected(self):
        content = """
class LicenseTier(Enum):
    FREE = "free"
    PRO = "pro"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "LicenseTier enum must be rejected"
        assert "LicenseTier" in result.stdout
        assert "commercial license-tier" in result.stdout.lower()

    def test_CommercialTier_enum_rejected(self):
        content = """
CommercialTier = {"trial": 1, "paid": 2}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "CommercialTier enum must be rejected"
        assert "CommercialTier" in result.stdout
        assert "commercial-tier classification" in result.stdout.lower()

    def test_PricingTier_enum_rejected(self):
        content = """
class PricingTier(IntEnum):
    FREE = 0
    STANDARD = 1
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "PricingTier enum must be rejected"
        assert "PricingTier" in result.stdout
        assert "pricing-tier" in result.stdout.lower()

    COMMERCIAL_TIER_ASSIGNMENTS = [
        "FREE = 'free'",
        "TRIAL = 'trial'",
        "STANDARD = 'standard'",
        "ENTERPRISE = 'enterprise'",
    ]

    @pytest.mark.parametrize("evil_line", COMMERCIAL_TIER_ASSIGNMENTS)
    def test_commercial_tier_enum_member_rejected(self, evil_line):
        content = f"\nclass LicensePlan:\n    {evil_line}\n"
        result = _run_lint_on(content)
        assert result.returncode != 0, f"Commercial tier assignment must be rejected: {evil_line}"
        assert "commercial-tier enum member" in result.stdout.lower()
        assert evil_line.split()[0] in result.stdout

    def test_licensee_id_in_dataclass_rejected(self):
        content = """
@dataclass
class LicenseRecord:
    licensee_id: str
    license_type: str
    tier: str = "paid_license"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "Combined commercial fields must be rejected"
        assert "licensee_id" in result.stdout.lower()
        assert "license_type" in result.stdout.lower()
        assert "paid_license" in result.stdout.lower()

    def test_v2_licenses_in_router_mount_rejected(self):
        content = '''
app.mount("/v2/licenses", license_router)
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, "Router mount of /v2/licenses must be rejected"
        assert "/v2/licenses" in result.stdout


# ── CAP117F-CORE-001 criterion 6: positive controls ──


class TestLicenseBoundaryPositiveControls:
    """Criterion 6: SPDX identifiers, manifest package-licence fields, dependency
    licence metadata, copyright notices and the repository LICENSE file remain
    accepted by the neutrality lint."""

    def test_spdx_mit_passes(self):
        content = '''
"""MIT-licensed utility module."""
license = "MIT"
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, f"SPDX MIT must pass: {result.stdout}"

    def test_spdx_apache2_passes(self):
        content = '''
"""Apache-2.0 licensed."""
LICENSE_ID = "Apache-2.0"
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, f"SPDX Apache-2.0 must pass: {result.stdout}"

    def test_spdx_bsd_passes(self):
        content = """
LICENSE = "BSD-3-Clause"
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, f"SPDX BSD-3-Clause must pass: {result.stdout}"

    SPDX_IDENTIFIERS = [
        "MIT",
        "Apache-2.0",
        "BSD-3-Clause",
        "BSD-2-Clause",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-3.0-only",
        "AGPL-3.0-only",
        "MPL-2.0",
        "ISC",
        "Unlicense",
        "CC0-1.0",
    ]

    @pytest.mark.parametrize("spdx_id", SPDX_IDENTIFIERS)
    def test_all_common_spdx_identifiers_pass(self, spdx_id):
        content = f'\nlicense = "{spdx_id}"\n'
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"SPDX identifier '{spdx_id}' must pass: {result.stdout}"
        )

    def test_manifest_package_license_field_passes(self):
        content = '''
@dataclass
class Manifest:
    """Capacium capability manifest."""
    kind: str = ""
    name: str = ""
    license: str = ""  # package-level SPDX identifier
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"Manifest license field must pass: {result.stdout}"
        )

    def test_dependency_license_metadata_passes(self):
        content = """
dep = {
    "name": "requests",
    "version": "2.31.0",
    "license": "Apache-2.0",
    "license_text": "...",
    "license_url": "https://...",
}
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"Dependency license metadata must pass: {result.stdout}"
        )

    def test_copyright_notice_passes(self):
        content = '''
# Copyright (c) 2026 Capacium Contributors
# SPDX-License-Identifier: Apache-2.0
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"Copyright notice must pass: {result.stdout}"
        )

    def test_license_file_reference_passes(self):
        content = '''
"""See LICENSE file at repository root for full license text."""
LICENSE_PATH = Path(__file__).parent.parent / "LICENSE"
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"LICENSE file reference must pass: {result.stdout}"
        )

    def test_license_in_registry_detail_passes(self):
        content = """
detail = {
    "license": r.get("license", ""),
    "license_url": r.get("license_url"),
}
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"Registry license detail fields must pass: {result.stdout}"
        )

    def test_spdx_validation_message_passes(self):
        content = '''
raise ManifestError("Add SPDX identifier e.g. license: MIT")
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"SPDX validation message must pass: {result.stdout}"
        )

    def test_license_init_prompt_passes(self):
        content = '''
manifest.license = _prompt_with_default("License", "Apache-2.0").strip()
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            f"License init prompt must pass: {result.stdout}"
        )

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
