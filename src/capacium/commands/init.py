import re
from pathlib import Path
from typing import Optional, List, Dict

from ..framework_detector import detect_active_frameworks, FRAMEWORK_DETECTORS
from ..utils.config import save_user_config, load_user_config, get_config_dir
from ..manifest import Manifest

VALID_TEMPLATES = {"skill", "mcp-server", "bundle"}

VALID_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
VALID_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
VALID_KINDS = {
    "skill",
    "tool",
    "prompt",
    "mcp-server",
    "template",
    "bundle",
    "workflow",
    "connector-pack",
}


def _validate_name(name: str) -> Optional[str]:
    if not name:
        return "name is required"
    if not VALID_NAME_RE.match(name):
        return f"invalid name '{name}': must be kebab-case (lowercase letters, numbers, hyphens)"
    return None


def _validate_kind(kind: str) -> Optional[str]:
    if not kind:
        return "kind is required"
    if kind not in VALID_KINDS:
        kinds_str = ", ".join(sorted(VALID_KINDS))
        return f"invalid kind '{kind}': must be one of {kinds_str}"
    return None


def _validate_version(version: str) -> Optional[str]:
    if not version:
        return "version is required"
    if not VALID_SEMVER_RE.match(version):
        return f"invalid version '{version}': must be valid semver (x.y.z)"
    return None


def init_capability(
    name: Optional[str] = None,
    kind: Optional[str] = None,
    version: Optional[str] = None,
    description: Optional[str] = None,
    frameworks: Optional[List[str]] = None,
    runtimes: Optional[Dict[str, str]] = None,
) -> bool:
    non_interactive = name is not None

    if non_interactive:
        err = _validate_name(name)
        if err:
            print(f"Error: {err}")
            return False
        kind = kind or "skill"
        err = _validate_kind(kind)
        if err:
            print(f"Error: {err}")
            return False
        version = version or "0.1.0"
        err = _validate_version(version)
        if err:
            print(f"Error: {err}")
            return False
        description = description or ""
        frameworks = frameworks or []
        runtimes = runtimes or {}
    else:
        print("\n  Capacium — Create capability.yaml\n" + "\u2500" * 36 + "\n")

        while True:
            name = input("  Name (kebab-case): ").strip()
            err = _validate_name(name)
            if err:
                print(f"  {err}")
                continue
            break

        print(f"\n  Kinds: {', '.join(sorted(VALID_KINDS))}")
        while True:
            kind = input("  Kind [skill]: ").strip() or "skill"
            err = _validate_kind(kind)
            if err:
                print(f"  {err}")
                continue
            break

        while True:
            version = input("  Version [0.1.0]: ").strip() or "0.1.0"
            err = _validate_version(version)
            if err:
                print(f"  {err}")
                continue
            break

        description = input("  Description (optional): ").strip()

        frameworks_raw = input(
            "  Frameworks (comma-separated, optional): "
        ).strip()
        if frameworks_raw:
            frameworks = [f.strip() for f in frameworks_raw.split(",") if f.strip()]
        else:
            frameworks = []

        runtimes_raw = input(
            "  Runtimes (name:version, comma-separated, optional): "
        ).strip()
        if runtimes_raw:
            runtimes = {}
            for pair in runtimes_raw.split(","):
                pair = pair.strip()
                if ":" in pair:
                    key, val = pair.split(":", 1)
                    runtimes[key.strip()] = val.strip()
        else:
            runtimes = {}

    manifest = Manifest(
        kind=kind,
        name=name,
        version=version,
        description=description,
        frameworks=frameworks,
        runtimes=runtimes,
    )

    output_path = Path.cwd() / "capability.yaml"

    if not non_interactive:
        print(f"\n  Will create: {output_path}\n")
        print(f"    kind: {kind}")
        print(f"    name: {name}")
        print(f"    version: {version}")
        if description:
            print(f"    description: {description}")
        if frameworks:
            print(f"    frameworks: {frameworks}")
        if runtimes:
            print(f"    runtimes: {runtimes}")
        print()

        confirm = input("  Create capability.yaml? [Y/n]: ").strip().lower()
        if confirm and confirm not in ("y", "yes", ""):
            print("  Aborted.")
            return False

    if output_path.exists():
        if non_interactive:
            print(f"Error: {output_path} already exists")
            return False
        overwrite = (
            input(f"  File {output_path} already exists. Overwrite? [y/N]: ")
            .strip()
            .lower()
        )
        if overwrite not in ("y", "yes"):
            print("  Aborted.")
            return False

    manifest.save(output_path)
    print(f"\n  Created {output_path}")
    return True


def init_config(
    registry_url: Optional[str] = None,
    trust_level: Optional[str] = None,
    auto_update: Optional[str] = None,
    frameworks: Optional[list] = None,
) -> bool:
    print("\n  Capacium Setup Wizard\n" + "\u2500" * 24 + "\n")

    config = {}
    existing = load_user_config()

    frameworks = frameworks or _prompt_frameworks()
    if frameworks:
        config["frameworks"] = frameworks

    if registry_url:
        config["registry"] = registry_url
    else:
        default_registry = existing.get("registry", "http://localhost:8000")
        config["registry"] = _prompt_with_default(
            "Registry URL", default_registry
        )

    if trust_level:
        config["trust_level"] = trust_level
    else:
        print("\n  Trust level filter for search results:")
        print("    any       \u2014 Show all capabilities")
        print("    audited+  \u2014 Only audited or verified")
        print("    verified+ \u2014 Only verified")
        print("    signed    \u2014 Only cryptographically signed")
        default_trust = existing.get("trust_level", "audited")
        config["trust_level"] = _prompt_with_default(
            "Trust level (any/audited/verified/signed)", default_trust
        ).strip() or default_trust

    if auto_update:
        config["auto_update"] = auto_update
    else:
        print("\n  Auto-update preference:")
        print("    on          \u2014 Automatically update capabilities")
        print("    notify-only \u2014 Notify when updates are available")
        print("    off         \u2014 Do nothing")
        default_update = existing.get("auto_update", "notify")
        config["auto_update"] = _prompt_with_default(
            "Auto-update (on/notify/off)", default_update
        ).strip() or default_update

    save_user_config(config)

    config_path = get_config_dir() / "config.yaml"
    print(f"\n\u2705 Configuration saved to {config_path}")
    print(f"   Registry:      {config.get('registry')}")
    print(f"   Trust level:   {config.get('trust_level')}")
    print(f"   Auto-update:   {config.get('auto_update')}")
    if config.get('frameworks'):
        print(f"   Frameworks:    {', '.join(config['frameworks'])}")
    print()
    return True


def init_skill() -> bool:
    print("\n  Capacium \u2014 New Capability Wizard\n" + "\u2500" * 32 + "\n")

    manifest = Manifest()

    manifest.name = _prompt_required("Capability name (kebab-case)", "my-capability")

    print("\n  Available kinds: skill, bundle, tool, prompt, template, workflow, mcp-server, connector-pack")
    default_kind = "skill"
    manifest.kind = _prompt_with_default("Kind", default_kind).strip() or default_kind

    manifest.version = _prompt_with_default("Version", "1.0.0").strip() or "1.0.0"

    manifest.description = _prompt_with_default("Description", "").strip()

    manifest.owner = _prompt_with_default("Owner (GitHub org/user)", "").strip()

    frameworks_input = _prompt_with_default(
        "Frameworks (comma-separated: opencode, claude-code, cursor, etc.)",
        ""
    ).strip()
    if frameworks_input:
        manifest.frameworks = [f.strip() for f in frameworks_input.split(",") if f.strip()]

    runtimes_str = _prompt_with_default(
        "Runtimes (syntax: name:version, comma-separated. e.g. uv:>=0.4.0, node:>=20)",
        ""
    ).strip()
    if runtimes_str:
        manifest.runtimes = {}
        for pair in runtimes_str.split(","):
            pair = pair.strip()
            if ":" in pair:
                key, val = pair.split(":", 1)
                manifest.runtimes[key.strip()] = val.strip()

    deps_str = _prompt_with_default(
        "Dependencies (syntax: name:version, comma-separated. e.g. owner/utils:>=1.0.0)",
        ""
    ).strip()
    if deps_str:
        manifest.dependencies = {}
        for pair in deps_str.split(","):
            pair = pair.strip()
            if ":" in pair:
                key, val = pair.split(":", 1)
                manifest.dependencies[key.strip()] = val.strip()

    manifest.repository = _prompt_with_default("Repository URL", "").strip()
    manifest.homepage = _prompt_with_default("Homepage URL", "").strip()
    manifest.license = _prompt_with_default("License", "Apache-2.0").strip()
    manifest.author = _prompt_with_default("Author", "").strip()

    output_path = Path.cwd() / "capability.yaml"
    print("\n  About to create:\n")
    print(f"    {output_path}")
    print()

    if manifest.name:
        print(f"    kind: {manifest.kind}")
        print(f"    name: {manifest.name}")
        print(f"    version: {manifest.version}")
        if manifest.description:
            print(f"    description: {manifest.description}")
        if manifest.owner:
            print(f"    owner: {manifest.owner}")
        if manifest.frameworks:
            print(f"    frameworks: {manifest.frameworks}")
        if manifest.runtimes:
            print(f"    runtimes: {manifest.runtimes}")
        if manifest.dependencies:
            print(f"    dependencies: {manifest.dependencies}")
    print()

    confirm = _prompt_with_default("Create capability.yaml? (Y/n)", "y").strip().lower()
    if confirm and confirm not in ("y", "yes", ""):
        print("Aborted.")
        return False

    if output_path.exists():
        overwrite = _prompt_with_default(
            f"File {output_path} already exists. Overwrite? (y/N)", "n"
        ).strip().lower()
        if overwrite not in ("y", "yes"):
            print("Aborted.")
            return False

    manifest.save(output_path)
    print(f"\n\u2705 Created {output_path}")

    errors = manifest.validate()
    if errors:
        print("\n\u26a0\ufe0f  Validation warnings:")
        for e in errors:
            print(f"   \u2022 {e}")
    else:
        print("\n\u2705 Manifest validated successfully.")

    print("\n  Next steps:")
    print("    $ cap validate")
    print("    $ cap package .")
    print("    $ cap registry publish")
    print()
    return True


def _prompt_required(prompt_text: str, default: str) -> str:
    while True:
        value = input(f"  {prompt_text} [{default}]: ").strip()
        if not value:
            value = default
        if value:
            return value
        print("  This field is required.")


def _prompt_with_default(prompt_text: str, default: str) -> str:
    default_display = f" ({default})" if default else ""
    value = input(f"  {prompt_text}{default_display}: ").strip()
    if not value and default:
        return default
    return value


def init_from_template(
    template: str,
    name: Optional[str] = None,
    version: str = "0.1.0",
    description: str = "",
    force: bool = False,
) -> bool:
    """Non-interactive init from a template: skill | mcp-server | bundle.

    Creates capability.yaml + SKILL.md + README.md in the current directory.
    When `name` is provided, runs fully non-interactive (< 60 seconds).
    """
    if template not in VALID_TEMPLATES:
        print(f"Error: unknown template '{template}'. Choose: {', '.join(sorted(VALID_TEMPLATES))}")
        return False

    # Resolve name — prompt only if not supplied
    if not name:
        print(f"\n  Template: {template}")
        print(f"  Examples: my-{template}, company-{template}, awesome-tool\n")
        while True:
            name = input(f"  Name (kebab-case) [my-{template}]: ").strip() or f"my-{template}"
            err = _validate_name(name)
            if err:
                print(f"  {err}")
                continue
            break
    else:
        err = _validate_name(name)
        if err:
            print(f"Error: {err}")
            return False

    err = _validate_version(version)
    if err:
        print(f"Error: {err}")
        return False

    output_dir = Path.cwd()
    cap_yaml = output_dir / "capability.yaml"
    skill_md = output_dir / "SKILL.md"
    readme_md = output_dir / "README.md"

    existing = [f for f in [cap_yaml, skill_md] if f.exists()]
    if existing and not force:
        print(f"Error: files already exist: {', '.join(f.name for f in existing)}")
        print("  Use --force to overwrite.")
        return False

    # Build manifest
    kind = template
    manifest = Manifest(
        kind=kind,
        name=name,
        version=version,
        description=description or f"A {kind} capability",
        frameworks=[],
        runtimes={},
    )

    # For mcp-server template: add mcp_meta section hint via description extension
    # (full mcp_meta support depends on Manifest model capabilities)
    if template == "mcp-server":
        try:
            manifest.mcp = {
                "transport": "stdio",
                "command": "python",
                "args": ["server.py"],
            }
        except AttributeError:
            pass  # mcp field not in current Manifest model; captured in SKILL.md instead

    manifest.save(cap_yaml)
    print(f"✅ Created {cap_yaml}")

    # SKILL.md stub
    _write_skill_md(skill_md, name, kind, version, description)
    print(f"✅ Created {skill_md}")

    # README.md stub (non-destructive)
    if not readme_md.exists() or force:
        _write_readme(readme_md, name, kind, description)
        print(f"✅ Created {readme_md}")

    print("\n  Next steps:")
    print("    $ cap validate")
    print("    $ cap package .")
    print("    $ cap publish .")
    print()
    return True


def _write_skill_md(path: Path, name: str, kind: str, version: str, description: str) -> None:
    """Write a SKILL.md stub with YAML frontmatter."""
    if kind == "mcp-server":
        body = (
            "## Usage\n\n"
            "Start the server:\n"
            "```bash\npython server.py\n```\n\n"
            "## Tools\n\n"
            "<!-- List the tools this MCP server exposes -->\n\n"
            "## Configuration\n\n"
            "<!-- Document transport / command / args -->\n"
        )
    elif kind == "bundle":
        body = (
            "## Included capabilities\n\n"
            "<!-- List sub-capabilities in this bundle -->\n\n"
            "## Installation\n\n"
            "```bash\ncap install {name}\n```\n"
        ).format(name=name)
    else:
        body = (
            "## Usage\n\n"
            "<!-- Describe how to use this skill -->\n\n"
            "## Examples\n\n"
            "<!-- Provide usage examples -->\n"
        )

    content = (
        f"---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"kind: {kind}\n"
        f"description: {description or f'A {kind} capability'}\n"
        f"author: \"\"\n"
        f"tags: []\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"{description or f'A {kind} capability.'}\n\n"
        f"{body}"
    )
    path.write_text(content)


def _write_readme(path: Path, name: str, kind: str, description: str) -> None:
    """Write a README.md stub."""
    content = (
        f"# {name}\n\n"
        f"{description or f'A {kind} capability for Capacium.'}\n\n"
        f"## Installation\n\n"
        f"```bash\ncap install {name}\n```\n\n"
        f"## Usage\n\n"
        f"<!-- Add usage instructions here -->\n\n"
        f"## License\n\n"
        f"Apache-2.0\n"
    )
    path.write_text(content)


def _prompt_frameworks() -> list:
    print("\n  Detecting frameworks...")
    detected = sorted(detect_active_frameworks())
    if detected:
        print(f"  Detected: {', '.join(detected)}")
        use_detected = input("  Use detected frameworks? (Y/n): ").strip().lower()
        if use_detected in ("", "y", "yes"):
            return detected

    print("\n  Available frameworks:")
    for i, fw in enumerate(sorted(FRAMEWORK_DETECTORS.keys()), 1):
        print(f"    {i}. {fw}")
    print("    0. None (agnostic)")
    print()
    choice = input("  Select frameworks (comma-separated numbers): ").strip()
    if not choice or choice == "0":
        return []

    all_fws = sorted(FRAMEWORK_DETECTORS.keys())
    selected = []
    for part in choice.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(all_fws):
                selected.append(all_fws[idx])
        except ValueError:
            pass
    return selected
