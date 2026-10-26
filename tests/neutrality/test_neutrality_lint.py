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
        assert "commercial licensee" in result.stdout.lower()

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
        assert "commercial/pricing-tier enum" in result.stdout.lower()

    def test_CommercialTier_enum_rejected(self):
        content = """
CommercialTier = {"trial": 1, "paid": 2}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "CommercialTier enum must be rejected"
        assert "CommercialTier" in result.stdout
        assert "commercial/pricing-tier enum" in result.stdout.lower()

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
        content = f"\nfrom enum import Enum\n\nclass LicensePlan(Enum):\n    {evil_line}\n"
        result = _run_lint_on(content)
        assert result.returncode != 0, f"Commercial tier assignment must be rejected: {evil_line}"
        assert "commercial-tier" in result.stdout.lower()

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

    # ── Reviewer F2 gap probes — broadened rules ──

    def test_licencee_id_british_spelling_rejected(self):
        content = """
def check():
    return {"licencee_id": "cust_abc123"}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "licencee_id (British) must be rejected by broadened rule"
        assert "licencee_id" in result.stdout.lower()

    def test_LICENCE_TYPE_uppercase_rejected(self):
        content = """
LICENCE_TYPE = "commercial"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "LICENCE_TYPE (uppercase British) must be rejected by broadened rule"
        assert "LICENCE_TYPE" in result.stdout

    def test_v2_licences_british_path_rejected(self):
        content = '''
def fetch(token):
    return requests.get("/v2/licences/validate", headers={"Authorization": f"Bearer {token}"})
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, "/v2/licences (British) must be rejected by broadened rule"
        assert "/v2/licences" in result.stdout

    def test_license_key_rejected(self):
        content = """
config = {"license_key": "KEY-1234-ABCD"}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "license_key must be rejected by broadened rule"
        assert "license_key" in result.stdout.lower()

    def test_is_paid_rejected(self):
        content = """
def check(cap):
    return cap.is_paid
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "is_paid must be rejected by broadened rule"
        assert "is_paid" in result.stdout

    def test_TierEnum_rejected(self):
        content = """
class TierEnum(Enum):
    FREE = 0
    PAID = 1
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "TierEnum must be rejected by broadened rule"
        assert "TierEnum" in result.stdout

    def test_commercial_tier_variable_rejected(self):
        content = """
commercial_tier = "enterprise"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "commercial_tier variable must be rejected"
        assert "commercial_tier" in result.stdout.lower()

    def test_license_validate_function_rejected(self):
        content = """
def license_validate(token):
    return requests.post("/v2/licenses/validate", json={"token": token})
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "license_validate function must be rejected"
        assert "license_validate" in result.stdout.lower()

    def test_add_parser_license_rejected(self):
        content = '''
subparsers = parser.add_subparsers(dest="command")
license_parser = subparsers.add_parser("license", help="Manage commercial licenses")
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, "add_parser('license') must be rejected"
        assert "license" in result.stdout.lower()

    def test_issue_paid_capability_license_rejected(self):
        content = '''
def issue_paid_capability_license(capability_id, licensee):
    """Issue a paid commercial license for a capability."""
    return {"license": {"id": "lic-123", "tier": "enterprise"}}
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, "issue_paid_capability_license must be rejected"
        assert "issue_paid_capability_license" in result.stdout.lower()

    def test_issue_license_function_rejected(self):
        content = '''
def issue_license(capability_id, licensee, tier="standard"):
    return {"license": {"id": "lic-456", "tier": tier}}
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, "issue_license must be rejected"
        assert "issue_license" in result.stdout.lower()

    def test_tiers_dict_mapping_rejected(self):
        content = """
TIERS = {"free": 0, "trial": 1, "standard": 2, "enterprise": 3}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "TIERS dict mapping must be rejected"
        assert "commercial-tier" in result.stdout.lower()

    def test_commercial_tiers_list_rejected(self):
        content = """
COMMERCIAL_TIERS = ["free", "trial", "standard", "enterprise"]
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "COMMERCIAL_TIERS list must be rejected"
        assert "commercial-tier" in result.stdout.lower()

    def test_license_key_dataclass_rejected(self):
        content = """
@dataclass
class LicenseKey:
    id: str
    tier: str = "standard"

def issue_license(cap_id):
    return LicenseKey(id="lic-789", tier="enterprise")
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, "LicenseKey dataclass with issue_license must be rejected"
        assert "issue_license" in result.stdout.lower()

    # ── Fix C (R4-F1): regression cases for each evaded shape ──

    def test_argparse_choices_multiline_rejected(self):
        content = '''
def build_parser():
    p.add_argument(
        "--type",
        choices=["free", "trial", "standard", "enterprise"],
    )
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "argparse choices with tier values (multiline) must be rejected"
        )
        assert "commercial-tier" in result.stdout.lower()

    def test_argparse_choices_single_line_rejected(self):
        content = '''
p.add_argument("--type", choices=["free","trial","standard","enterprise"])
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "argparse choices with tier values (single-line) must be rejected"
        )
        assert "commercial-tier" in result.stdout.lower()

    def test_tiers_tuple_rejected(self):
        content = '''
TIERS = ("free", "trial", "standard", "enterprise")
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "TIERS tuple with tier values must be rejected"
        )
        assert "commercial-tier" in result.stdout.lower()

    def test_commercial_tiers_tuple_rejected(self):
        content = '''
COMMERCIAL_TIERS = ("free", "trial", "standard", "enterprise")
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "COMMERCIAL_TIERS tuple must be rejected"
        )
        assert "commercial-tier" in result.stdout.lower()

    def test_valid_tiers_tuple_rejected(self):
        content = '''
VALID_TIERS = ("free", "trial", "standard", "enterprise")
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "VALID_TIERS tuple must be rejected"
        )
        assert "commercial-tier" in result.stdout.lower()

    def test_tier_enum_lowercase_members_rejected(self):
        content = """
from enum import Enum

class Tier(Enum):
    free = "free"
    trial = "trial"
    standard = "standard"
    enterprise = "enterprise"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Tier Enum with lowercase commercial members must be rejected"
        )
        assert "commercial-tier enum" in result.stdout.lower()

    def test_plan_tier_enum_lowercase_members_rejected(self):
        content = """
from enum import Enum

class PlanTier(Enum):
    free = "free"
    trial = "trial"
    standard = "standard"
    enterprise = "enterprise"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "PlanTier Enum with lowercase commercial members must be rejected"
        )
        assert "commercial-tier enum" in result.stdout.lower()

    def test_license_issue_function_rejected(self):
        content = '''
def license_issue(capability_id, licensee, tier="standard"):
    """Issue a commercial license."""
    return {"license_key": "KEY-123", "tier": tier}
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "license_issue function must be rejected"
        )
        assert "license_issue" in result.stdout.lower()

    def test_license_revoke_function_rejected(self):
        content = '''
def license_revoke(license_id):
    """Revoke a commercial license."""
    return {"status": "revoked"}
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "license_revoke function must be rejected"
        )
        assert "license_revoke" in result.stdout.lower()

    def test_license_list_function_rejected(self):
        content = '''
def license_list(licensee_id=None):
    """List commercial licenses for a licensee."""
    return [{"id": "lic-001", "tier": "standard"}]
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "license_list function must be rejected"
        )
        assert "license_list" in result.stdout.lower()

    def test_add_parser_licence_british_rejected(self):
        content = '''
subparsers = parser.add_subparsers(dest="command")
licence_parser = subparsers.add_parser("licence", help="Manage commercial licences")
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "add_parser('licence') British spelling must be rejected"
        )
        assert "licence" in result.stdout.lower()

    def test_composite_reintroduction_rejected(self):
        content = """
from enum import Enum
from dataclasses import dataclass

class PlanTier(Enum):
    free = "free"
    trial = "trial"
    standard = "standard"
    enterprise = "enterprise"

TIER_MAP = {
    PlanTier.free: 0,
    PlanTier.trial: 1,
    PlanTier.standard: 2,
    PlanTier.enterprise: 3,
}

@dataclass
class Customer:
    licensee_id: str
    tier: PlanTier = PlanTier.free

def license_issue(cap_id, customer):
    return {"license_key": "KEY-001", "tier": customer.tier}

def license_revoke(license_id):
    return {"status": "revoked"}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Composite reintroduction must be rejected"
        )
        assert len(result.stdout) > 0, (
            "Composite reintroduction must produce lint errors, got empty stdout"
        )

    def test_tier_map_dict_rejected(self):
        content = """
TIER_MAP = {"free": 0, "trial": 1, "standard": 2, "enterprise": 3}
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "TIER_MAP dict with tier values must be rejected"
        )
        assert "commercial-tier" in result.stdout.lower()

    # ── Fix D (R5-F1): decisive probe regression — keyword-form add_parser
    #     with TIER_VALUES indirection must be rejected ──

    def test_decisive_keyword_form_add_parser_rejected(self):
        """Faithful reintroduction of the deleted command surface using
        keyword-form add_parser(name="license") and TIER_VALUES indirection
        must be rejected (R5-F1)."""
        content = '''
import argparse

TIER_VALUES = ["free", "trial", "standard", "enterprise"]

def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    license_parser = subparsers.add_parser(
        name="license",
        help="Manage license keys for paid capabilities",
    )
    license_sub = license_parser.add_subparsers(dest="license_command")

    issue_parser = license_sub.add_parser("issue")
    issue_parser.add_argument("--publisher")
    issue_parser.add_argument("--holder")
    issue_parser.add_argument(
        "--type", choices=TIER_VALUES, default="free"
    )

    validate_parser = license_sub.add_parser("validate")
    validate_parser.add_argument("license_id")

    revoke_parser = license_sub.add_parser("revoke")
    revoke_parser.add_argument("license_id")

    list_parser = license_sub.add_parser("list")
    list_parser.add_argument("--licensee")

    return parser

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "license":
        if args.license_command == "issue":
            return {"issued": True, "tier": args.type}
        elif args.license_command == "validate":
            return {"valid": True}
        elif args.license_command == "revoke":
            return {"revoked": True}
        elif args.license_command == "list":
            return {"licenses": []}

if __name__ == "__main__":
    main()
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Decisive probe (keyword-form add_parser + TIER_VALUES indirection) "
            "must be rejected"
        )
        # Should catch at least: tier value set, license registration, choices
        assert len(result.stdout) > 0, "Must produce lint errors"

    # ── Fix D (R5-F3): false-positive regression — each previously rejected
    #     neutral shape must now pass ──

    def test_fp_choices_standard_hardened_passes(self):
        content = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--mode", choices=["standard", "hardened"])
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "choices=[standard, hardened] must pass (not tier dominance)"
        )

    def test_fp_choices_freeform_fixed_passes(self):
        content = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--layout", choices=["freeform", "fixed"])
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "choices=[freeform, fixed] must pass (not tier values)"
        )

    def test_fp_choices_freebsd_linux_passes(self):
        content = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--platform", choices=["freebsd", "linux", "darwin"])
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "choices=[freebsd, linux, darwin] must pass (not tier values)"
        )

    def test_fp_tiers_paranoid_standard_passes(self):
        content = '''
TIERS = ["paranoid", "standard", "open"]
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "TIERS=[paranoid, standard, open] must pass (not tier dominance)"
        )

    def test_fp_standard_constant_passes(self):
        content = """
STANDARD = "baseline"
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "STANDARD = 'baseline' outside Enum body must pass"
        )

    def test_fp_choices_standard_isolated_passes(self):
        content = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--mode", choices=["standard", "isolated"])
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "choices=[standard, isolated] must pass (not tier dominance)"
        )

    def test_fp_spdx_license_command_passes(self):
        content = '''
import argparse
p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd")
sub.add_parser("license", help="List SPDX license identifiers")
'''
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "add_parser('license', help='...SPDX...') must pass"
        )

    # ── Fix D (R5-F2): Enum functional API forms must be caught ──

    def test_enum_functional_list_rejected(self):
        content = """
from enum import Enum
Plan = Enum("Plan", ["FREE", "TRIAL", "STANDARD", "ENTERPRISE"])
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Enum functional API list form must be rejected"
        )

    def test_enum_functional_mapping_rejected(self):
        content = """
from enum import Enum
Plan = Enum("Plan", {"FREE": "free", "TRIAL": "trial", "STANDARD": "standard", "ENTERPRISE": "enterprise"})
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Enum functional API mapping form must be rejected"
        )

    def test_enum_functional_names_string_rejected(self):
        content = '''
from enum import Enum
Tier = Enum("Tier", "FREE TRIAL STANDARD ENTERPRISE")
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Enum functional API space-separated names form must be rejected"
        )

    # ── Fix D: Uppercase tier assignment only in Enum body ──

    def test_uppercase_tier_in_enum_body_rejected(self):
        content = """
from enum import Enum

class LicensePlan(Enum):
    FREE = "free"
    TRIAL = "trial"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"
"""
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "Uppercase tier members in Enum body must be rejected"
        )

    # ── Fix D: choices through same-file constant indirection ──

    def test_choices_via_constant_indirection_rejected(self):
        content = '''
TIER_VALUES = ["free", "trial", "standard", "enterprise"]
import argparse
p = argparse.ArgumentParser()
p.add_argument("--type", choices=TIER_VALUES)
'''
        result = _run_lint_on(content)
        assert result.returncode != 0, (
            "choices=TIER_VALUES with constant indirection must be rejected"
        )

    # ── Fix D: benign enum with non-tier members passes ──

    def test_benign_enum_non_tier_members_passes(self):
        content = """
from enum import Enum

class Tier(Enum):
    BASIC = "basic"
    PRO = "pro"
    ULTRA = "ultra"
"""
        result = _run_lint_on(content)
        assert result.returncode == 0, (
            "Enum with non-tier members must pass"
        )


# ── CAP117F-CORE-001 criterion 6: positive controls ──


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
