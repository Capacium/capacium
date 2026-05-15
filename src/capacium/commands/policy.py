"""cap install --policy — Policy-as-code enforcement for capability installation (W50-002).

A policy.yaml with kind: policy defines rules that cap install enforces BEFORE
writing anything to disk. The install is blocked if any rule is violated.

Policy rules (all optional, additive):
    minimum_trust_state:  "discovered" | "audited" | "verified" | "signed"
    allowed_publishers:   ["acme-corp", "trusted-org"]   # empty = allow all
    blocked_kinds:        ["workflow", "connector-pack"]  # empty = block none
    blocked_capabilities: ["owner/bad-skill"]             # explicit deny list
    require_license:      true                            # must have license field
    max_quality_score:    null                            # (reserved, not enforced)
    min_quality_score:    60                              # minimum quality score

Usage:
    cap install owner/name --policy ./policy.yaml
    cap install owner/name --policy org-policy://acme-corp   # future: remote policy

Exit codes (from cmd_install delegation):
    0 = installed
    1 = install error
    3 = policy violation (distinct code so CI can distinguish policy blocks from errors)

Integration:
    Called from commands/install.py via check_policy_compliance().
    The --policy flag is added to the install_parser in cli.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# ---------------------------------------------------------------------------
# Trust state ordering
# ---------------------------------------------------------------------------

TRUST_ORDER = ["discovered", "audited", "verified", "signed"]


def _trust_rank(state: str) -> int:
    try:
        return TRUST_ORDER.index(state)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------

def load_policy(path: str) -> Dict[str, Any]:
    """Load and validate a policy.yaml file.

    Returns:
        dict with policy rules (all keys optional).
    Raises:
        SystemExit(3) on load failure.
    """
    p = Path(path)
    if not p.exists():
        print(f"[cap] Policy file not found: {path}", file=sys.stderr)
        sys.exit(3)

    if not _HAS_YAML:
        print("[cap] PyYAML not installed. Cannot load policy file.", file=sys.stderr)
        print("      Fix: pip install pyyaml", file=sys.stderr)
        sys.exit(3)

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[cap] Policy YAML parse error: {e}", file=sys.stderr)
        sys.exit(3)

    if not isinstance(data, dict):
        print("[cap] Policy file must be a YAML mapping.", file=sys.stderr)
        sys.exit(3)

    kind = data.get("kind", "")
    if kind and kind != "policy":
        print(f"[cap] Warning: policy file has kind '{kind}' (expected 'policy'). Proceeding.", file=sys.stderr)

    policy_meta = data.get("policy_meta", data)  # support both bare and capability.yaml format
    return policy_meta


# ---------------------------------------------------------------------------
# Policy enforcement
# ---------------------------------------------------------------------------

class PolicyViolation(Exception):
    """Raised when a capability violates a policy rule."""
    def __init__(self, rule: str, message: str):
        self.rule = rule
        self.message = message
        super().__init__(f"[policy:{rule}] {message}")


def check_policy_compliance(
    capability_info: Dict[str, Any],
    policy: Dict[str, Any],
    color: bool = True,
) -> List[PolicyViolation]:
    """Check a capability against all policy rules.

    Args:
        capability_info: dict from Exchange /v2/capabilities/{owner}/{name}
        policy:          loaded policy_meta dict
        color:           whether to use ANSI color in messages

    Returns:
        List of PolicyViolation objects (empty = compliant).
    """
    violations: List[PolicyViolation] = []
    name = capability_info.get("canonical_name", "unknown/unknown")
    kind = capability_info.get("kind", "skill")
    trust_state = capability_info.get("trust_state", "discovered")
    publisher = (capability_info.get("publisher") or {}).get("slug", "")
    quality = float(capability_info.get("quality_score") or 0)
    license_field = capability_info.get("github_license") or capability_info.get("license")

    # ── minimum_trust_state ──────────────────────────────────────────────────
    min_trust = policy.get("minimum_trust_state")
    if min_trust:
        if _trust_rank(trust_state) < _trust_rank(min_trust):
            violations.append(PolicyViolation(
                "minimum_trust_state",
                f"'{name}' has trust_state '{trust_state}' but policy requires >= '{min_trust}'",
            ))

    # ── allowed_publishers ───────────────────────────────────────────────────
    allowed_publishers: List[str] = policy.get("allowed_publishers") or []
    if allowed_publishers and publisher not in allowed_publishers:
        violations.append(PolicyViolation(
            "allowed_publishers",
            f"'{name}' is published by '{publisher}' which is not in allowed_publishers: {allowed_publishers}",
        ))

    # ── blocked_kinds ────────────────────────────────────────────────────────
    blocked_kinds: List[str] = policy.get("blocked_kinds") or []
    if kind in blocked_kinds:
        violations.append(PolicyViolation(
            "blocked_kinds",
            f"'{name}' has kind '{kind}' which is blocked by policy",
        ))

    # ── blocked_capabilities ─────────────────────────────────────────────────
    blocked_caps: List[str] = policy.get("blocked_capabilities") or []
    if name in blocked_caps:
        violations.append(PolicyViolation(
            "blocked_capabilities",
            f"'{name}' is on the blocked_capabilities list",
        ))

    # ── min_quality_score ────────────────────────────────────────────────────
    min_quality = policy.get("min_quality_score")
    if min_quality is not None:
        if quality < float(min_quality):
            violations.append(PolicyViolation(
                "min_quality_score",
                f"'{name}' has quality score {quality:.0f} but policy requires >= {min_quality}",
            ))

    # ── require_license ──────────────────────────────────────────────────────
    if policy.get("require_license"):
        if not license_field:
            violations.append(PolicyViolation(
                "require_license",
                f"'{name}' has no license field but policy requires one",
            ))

    return violations


def print_policy_violations(violations: List[PolicyViolation], color: bool = True) -> None:
    """Print policy violations to stderr in a human-readable format."""
    RED   = "\033[31m" if color else ""
    RESET = "\033[0m"  if color else ""
    BOLD  = "\033[1m"  if color else ""

    print(f"\n{RED}{BOLD}🚫 Installation blocked by policy ({len(violations)} violation{'s' if len(violations) != 1 else ''}):{RESET}", file=sys.stderr)
    for v in violations:
        print(f"{RED}  [{v.rule}] {v.message}{RESET}", file=sys.stderr)
    print(f"\n{RED}  Fix: update the capability or adjust your policy.yaml{RESET}", file=sys.stderr)
    print(f"{RED}  Exit code 3 = policy violation (distinguishable from install error){RESET}\n", file=sys.stderr)


# ---------------------------------------------------------------------------
# Integration point for commands/install.py
# ---------------------------------------------------------------------------

def enforce_policy(
    capability_info: Dict[str, Any],
    policy_path: str,
) -> None:
    """Load policy from path and check capability. Exits with code 3 on violation.

    Called from cmd_install when --policy flag is provided.
    """
    import os
    color = sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""
    policy = load_policy(policy_path)
    violations = check_policy_compliance(capability_info, policy, color=color)
    if violations:
        print_policy_violations(violations, color=color)
        sys.exit(3)
