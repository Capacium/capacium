"""cap validate — Validate capability.yaml against the v1.0 spec (SPEC-002).

Usage:
    cap validate
    cap validate capability.yaml
    cap validate path/to/capability.yaml --strict
    cap validate capability.yaml --json
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCHEMA_URL = "https://capacium.xyz/spec/v1.0/schema.json"
SCHEMA_CACHE_PATH = Path.home() / ".capacium" / "cache" / "spec-v1.0-schema.json"

VALID_KINDS = {
    "skill", "mcp-server", "bundle", "tool", "prompt",
    "template", "workflow", "connector-pack",
    "operator", "checkpoint", "policy",
}

TRUST_STATES = ["discovered", "audited", "verified", "signed"]

SEMVER_RE = re.compile(
    r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
    r'(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?'
    r'(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'
)
NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-z0-9][a-z0-9-]*$')


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _fetch_schema() -> Optional[Dict[str, Any]]:
    """Fetch JSON Schema from cache or capacium.xyz."""
    if SCHEMA_CACHE_PATH.exists():
        try:
            return json.loads(SCHEMA_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        req = urllib.request.Request(
            SCHEMA_URL,
            headers={"User-Agent": "cap-cli/2 (validate)"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            schema_text = r.read().decode("utf-8")
        SCHEMA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_CACHE_PATH.write_text(schema_text, encoding="utf-8")
        return json.loads(schema_text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Semantic checks
# ---------------------------------------------------------------------------

def _semantic_checks(data: Dict[str, Any], strict: bool) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    name = data.get("name", "")
    version = data.get("version", "")
    kind = data.get("kind", "")

    if name and not NAME_RE.match(name):
        errors.append(
            f"  name '{name}' must match 'owner/capability-name'\n"
            f"    Fix: use lowercase alphanumeric+hyphen for the capability name part"
        )

    if version:
        if not SEMVER_RE.match(str(version)):
            errors.append(
                f"  version '{version}' is not valid semver\n"
                f"    Fix: use MAJOR.MINOR.PATCH format, e.g. 1.0.0"
            )
        elif str(version) == "0.0.0":
            warnings.append("  version '0.0.0' — update to a real release version")

    # Kind-specific
    if kind == "mcp-server" and "mcp_meta" not in data:
        warnings.append(
            "  kind 'mcp-server' missing 'mcp_meta' block\n"
            "    Add: mcp_meta.transport, mcp_meta.tools list"
        )

    if kind == "bundle" and "bundle_meta" not in data:
        warnings.append(
            "  kind 'bundle' missing 'bundle_meta' block\n"
            "    Add: bundle_meta.capabilities list"
        )

    if kind == "operator" and "operator_meta" not in data:
        errors.append(
            "  kind 'operator' requires 'operator_meta' block\n"
            "    Add: operator_meta.role, operator_meta.sla_hours, operator_meta.approval_modes"
        )

    if kind == "checkpoint" and "checkpoint_meta" not in data:
        errors.append(
            "  kind 'checkpoint' requires 'checkpoint_meta' block\n"
            "    Add: checkpoint_meta.fallback (approve|reject|escalate)"
        )

    if kind == "policy" and "policy_meta" not in data:
        errors.append(
            "  kind 'policy' requires 'policy_meta' block\n"
            "    Add: policy_meta.minimum_trust_state (discovered|audited|verified|signed)"
        )

    # Description
    desc = data.get("description", "")
    if desc and len(desc) > 200:
        warnings.append(
            f"  description is {len(desc)} chars (recommended ≤ 200)\n"
            f"    Move extended text to 'long_description' field"
        )

    # Strict: recommended fields
    if strict:
        if not data.get("canonical_source_url"):
            warnings.append(
                "  [--strict] no 'canonical_source_url'\n"
                "    Add your GitHub/GitLab repo URL for publisher trust verification"
            )
        if not data.get("license"):
            warnings.append(
                "  [--strict] no 'license' field\n"
                "    Add SPDX identifier e.g. license: MIT"
            )
        if not data.get("tags"):
            warnings.append(
                "  [--strict] no 'tags'\n"
                "    Add descriptive tags to improve discoverability"
            )
        if not data.get("frameworks"):
            warnings.append(
                "  [--strict] no 'frameworks'\n"
                "    Specify target frameworks e.g. [claude-code, cursor]"
            )

    return errors, warnings


# ---------------------------------------------------------------------------
# Core validate function
# ---------------------------------------------------------------------------

def validate_capability(
    path: str,
    strict: bool = False,
    offline: bool = False,
) -> Dict[str, Any]:
    """Validate a capability.yaml file against the v1.0 spec.

    Returns:
        dict: {
            valid (bool), errors (list[str]), warnings (list[str]),
            name (str), kind (str), version (str)
        }
    """
    p = Path(path)
    if not p.exists():
        return {
            "valid": False,
            "errors": [f"File not found: {path}"],
            "warnings": [],
            "name": "", "kind": "", "version": "",
        }

    if not _HAS_YAML:
        return {
            "valid": False,
            "errors": [
                "PyYAML not installed",
                "Fix: pip install pyyaml",
            ],
            "warnings": [],
            "name": "", "kind": "", "version": "",
        }

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {
            "valid": False,
            "errors": [f"YAML parse error: {e}"],
            "warnings": [],
            "name": "", "kind": "", "version": "",
        }

    if not isinstance(data, dict):
        return {
            "valid": False,
            "errors": ["capability.yaml must be a mapping (dict), not a list or scalar"],
            "warnings": [],
            "name": "", "kind": "", "version": "",
        }

    errors: List[str] = []
    warnings: List[str] = []

    # Required fields
    for field in ("name", "version", "kind", "description"):
        if field not in data or not data.get(field):
            errors.append(
                f"  Required field missing or empty: '{field}'\n"
                f"    Fix: add {field}: <value> to capability.yaml"
            )

    # JSON Schema
    if not offline and not errors and _HAS_JSONSCHEMA:
        schema = _fetch_schema()
        if schema:
            validator = jsonschema.Draft202012Validator(schema)
            for err in validator.iter_errors(data):
                path_str = ".".join(str(p) for p in err.path) or "root"
                errors.append(f"  Schema validation: {err.message} (at {path_str})")

    # Semantic checks
    sem_errors, sem_warnings = _semantic_checks(data, strict)
    errors.extend(sem_errors)
    warnings.extend(sem_warnings)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "name": data.get("name", ""),
        "kind": data.get("kind", ""),
        "version": data.get("version", ""),
    }


# ---------------------------------------------------------------------------
# CLI formatting
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""


def _print_result(result: Dict[str, Any], path: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, indent=2))
        return

    color = _supports_color()
    GREEN  = "\033[32m" if color else ""
    RED    = "\033[31m" if color else ""
    YELLOW = "\033[33m" if color else ""
    RESET  = "\033[0m"  if color else ""
    DIM    = "\033[2m"  if color else ""

    if result["valid"]:
        print(f"{GREEN}✅  {path} is valid{RESET} (capability.yaml v1.0)")
        if result.get("name"):
            print(f"    Name:    {DIM}{result['name']}{RESET}")
        if result.get("kind"):
            print(f"    Kind:    {DIM}{result['kind']}{RESET}")
        if result.get("version"):
            print(f"    Version: {DIM}{result['version']}{RESET}")
        if not result.get("warnings"):
            print(f"    Issues:  {DIM}None{RESET}")
    else:
        print(f"{RED}❌  {path} is INVALID{RESET}")
        for err in result["errors"]:
            print(f"{RED}{err}{RESET}")

    if result.get("warnings"):
        print(f"    {YELLOW}Warnings ({len(result['warnings'])}):{RESET}")
        for w in result["warnings"]:
            print(f"{YELLOW}{w}{RESET}")


# ---------------------------------------------------------------------------
# Entry point called from cli.py
# ---------------------------------------------------------------------------

def cmd_validate(args) -> int:
    """Handle `cap validate` subcommand. Returns exit code."""
    path = args.path or "capability.yaml"

    # If a directory, look for capability.yaml inside it
    p = Path(path)
    if p.is_dir():
        path = str(p / "capability.yaml")

    result = validate_capability(
        path,
        strict=getattr(args, "strict", False),
        offline=getattr(args, "offline", False),
    )

    _print_result(result, path, json_mode=getattr(args, "json", False))

    return 0 if result["valid"] else 1
