import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .commands.registry import add_registry_parser


def main():
    parser = argparse.ArgumentParser(
        prog="cap",
        description="Capacium - Capability Packaging System for AI agent capabilities",
        epilog="For more information, visit https://github.com/Capacium/capacium"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    install_parser = subparsers.add_parser("install", help="Install a capability")
    install_parser.add_argument("capability", nargs="?", help="Capability specification (owner/name[@version] or name[@version]). Optional when --from-tarball is used.")
    install_parser.add_argument("--version", help="Specific version to install")
    install_parser.add_argument("--source", help="Source directory (defaults to current directory)")
    install_parser.add_argument(
        "--project",
        help="Project root for project-scoped clients (cursor): writes go to "
             "<project>/.cursor/ instead of being skipped. Never implicit cwd.",
    )
    install_parser.add_argument("--no-lock", action="store_true", help="Bypass lock file enforcement")
    install_parser.add_argument(
        "--skip-runtime-check",
        action="store_true",
        help="Skip the pre-flight runtime check (advanced)",
    )
    install_parser.add_argument(
        "--all-frameworks",
        action="store_true",
        help="Create symlinks in all detected framework directories",
    )
    install_parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip all network calls (use cached packages only)",
    )
    install_parser.add_argument(
        "--framework",
        help="Restrict installation to a specific framework (e.g. claude-code, opencode)",
    )
    install_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip all interactive prompts",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Force installation even if a different owner is detected",
    )
    install_parser.add_argument(
        "--prune",
        action="store_true",
        help="After a successful install, prune safe superseded versions",
    )
    install_parser.add_argument(
        "--from-tarball",
        help="Install from a local .tar.gz file",
    )
    install_parser.add_argument(
        "--token",
        help="GitHub token for private repositories (or set GITHUB_TOKEN)",
    )
    install_parser.add_argument(
        "--registry",
        help="Private registry base URL (e.g. https://registry.acme.com). Overrides default Exchange URL.",
    )
    install_parser.add_argument(
        "--policy",
        help="Path to a policy.yaml (kind: policy) that must be satisfied before install. "
             "Exit code 3 = policy violation.",
    )

    update_parser = subparsers.add_parser("update", help="Update a capability")
    update_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")
    update_parser.add_argument("--force", action="store_true", help="Force adapter reconciliation even when content is unchanged")
    update_parser.add_argument(
        "--skip-runtime-check",
        action="store_true",
        help="Skip the pre-flight runtime check (advanced)",
    )

    remove_parser = subparsers.add_parser("remove", help="Remove a capability")
    remove_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")
    remove_parser.add_argument("--force", action="store_true", help="Force removal including sub-capabilities with dependents")

    list_parser = subparsers.add_parser("list", help="List installed capabilities")
    list_parser.add_argument("--kind", help="Filter by kind (skill, bundle, tool, prompt, template, workflow, mcp-server)")
    list_parser.add_argument("--framework", help="Filter by framework (opencode, claude-code, cursor, etc.)")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")
    list_parser.add_argument("--details", action="store_true", help="Show per-adapter installation status")

    search_parser = subparsers.add_parser("search", help="Search for capabilities")
    search_parser.add_argument("query", nargs="?", default="", help="Search query (omit to browse all)")
    search_parser.add_argument("--kind", help="Filter by kind")
    search_parser.add_argument("--registry", help="Remote registry URL to search")
    search_parser.add_argument("--category", help="Filter by category slug")
    search_parser.add_argument("--trust", help="Filter by trust state")
    search_parser.add_argument("--min-trust", help="Filter by minimum trust state")
    search_parser.add_argument("--tag", action="append", help="Filter by tag (repeatable)")
    search_parser.add_argument("--mcp-client", help="Filter by MCP client compatibility")
    search_parser.add_argument("--publisher", help="Filter by publisher ID")
    search_parser.add_argument("--sort", choices=["stars", "trust", "score", "name", "updated"], default="stars")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")
    search_parser.add_argument("--min-stars", type=int, help="Filter by minimum GitHub stars")
    search_parser.add_argument("--limit", type=int, default=50, help="Max results")
    search_parser.add_argument("--framework", help="Filter by target framework (e.g. cursor, claude-code)")

    browse_parser = subparsers.add_parser("browse", help="Interactive terminal UI for browsing capabilities")
    browse_parser.add_argument("--sort", choices=["stars", "score", "name", "updated"], default="stars")
    browse_parser.add_argument("--min-stars", type=int, help="Filter by minimum GitHub stars")
    browse_parser.add_argument("--kind", help="Filter by kind")

    info_parser = subparsers.add_parser("info", help="Show detailed information about a capability")
    info_parser.add_argument("capability", help="Capability specification (owner/name)")
    info_parser.add_argument("--registry", help="Remote registry URL")
    info_parser.add_argument("--json", action="store_true", help="Output as JSON")

    compare_parser = subparsers.add_parser("compare", help="Compare two capabilities side-by-side")
    compare_parser.add_argument("a", help="First capability (owner/name)")
    compare_parser.add_argument("b", help="Second capability (owner/name)")
    compare_parser.add_argument("--registry", help="Remote registry URL")
    compare_parser.add_argument("--json", action="store_true", help="Output as JSON")

    update_parser = subparsers.add_parser("update-index", help="Update the local search index from the Exchange")
    update_parser.add_argument("--full", action="store_true", help="Full index rebuild")
    update_parser.add_argument("--registry", help="Remote registry URL")

    init_parser = subparsers.add_parser("init", help="Create a new capability.yaml")
    init_parser.add_argument("--name", help="Capability name (kebab-case)")
    init_parser.add_argument(
        "--kind",
        help="Capability kind (skill, tool, prompt, mcp-server, template, bundle, workflow, connector-pack, resource)",
    )
    init_parser.add_argument("--version", help="Capability version (semver, e.g. 0.1.0)")
    init_parser.add_argument("--description", help="Capability description")
    init_parser.add_argument(
        "--frameworks",
        help="Comma-separated frameworks (e.g. opencode,claude-code)",
    )
    init_parser.add_argument(
        "--runtimes",
        help="Comma-separated runtimes (e.g. uv:>=0.4.0,node:>=20)",
    )
    init_parser.add_argument(
        "--template",
        choices=["skill", "mcp-server", "bundle", "resource"],
        help="Scaffold from template: skill | mcp-server | bundle | resource. Creates capability.yaml + SKILL.md + README.md.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files when using --template",
    )

    add_registry_parser(subparsers)

    verify_parser = subparsers.add_parser("verify", help="Verify capability fingerprint")
    verify_parser.add_argument("capability", nargs="?", help="Capability to verify (omit for --all)")
    verify_parser.add_argument("--all", action="store_true", help="Verify all installed capabilities")

    lock_parser = subparsers.add_parser("lock", help="Generate capability.lock for an installed capability")
    lock_parser.add_argument("capability", help="Capability specification (owner/name)")
    lock_parser.add_argument("--update", action="store_true", help="Update existing lock file")

    package_parser = subparsers.add_parser("package", help="Package capability for distribution")
    package_parser.add_argument("--manifest", help="Path to capability.yaml (default: capability.yaml in current directory)")
    package_parser.add_argument("--output-dir", default="./dist/", help="Output directory (default: ./dist/)")

    publish_parser = subparsers.add_parser("publish", help="Publish a capability to the Exchange registry")
    publish_parser.add_argument("package_path", help="Path to .tar.gz, capability.yaml, or directory containing capability.yaml")
    publish_parser.add_argument("--token", help="API token for the Exchange registry (or set CAPACIUM_API_TOKEN)")
    publish_parser.add_argument(
        "--registry",
        help="Target registry URL (default: https://api.capacium.xyz). Use for non-default or self-hosted registries.",
    )

    marketplace_parser = subparsers.add_parser("marketplace", help="Open the Capacium marketplace in your browser")
    marketplace_parser.add_argument(
        "--search",
        metavar="QUERY",
        default=None,
        help="Pre-fill the search box, e.g. --search 'pdf parser'",
    )
    marketplace_parser.add_argument(
        "--url",
        action="store_true",
        help="Print the URL instead of opening a browser",
    )
    # Legacy flags kept for backwards-compat (ignored by new handler)
    marketplace_parser.add_argument("--host", default="0.0.0.0", help=argparse.SUPPRESS)
    marketplace_parser.add_argument("--port", type=int, default=8000, help=argparse.SUPPRESS)
    marketplace_parser.add_argument("--open", action="store_true", help=argparse.SUPPRESS)

    # SPEC-002: cap validate
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate capability.yaml against the v1.0 specification",
    )
    validate_parser.add_argument(
        "path",
        nargs="?",
        default="capability.yaml",
        help="Path to capability.yaml or directory containing one (default: ./capability.yaml)",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Also check recommended fields (canonical_source_url, license, tags, frameworks)",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Output validation result as JSON",
    )
    validate_parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip remote JSON Schema download (use cached schema if available)",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check installed capabilities for missing host runtimes",
    )
    doctor_parser.add_argument(
        "capability",
        nargs="?",
        help="Optional capability spec (owner/name) to check; defaults to all",
    )
    doctor_parser.add_argument(
        "--deep", action="store_true",
        help="Run deep checks: symlinks, config integrity, MCP handshakes, drift detection",
    )

    repair_parser = subparsers.add_parser(
        "repair",
        help="Detect and fix stale/orphaned MCP server entries in framework configs",
    )
    repair_parser.add_argument(
        "capability",
        nargs="?",
        help="Optional capability spec (owner/name) to check; defaults to all",
    )
    repair_parser.add_argument(
        "--dry-run", action="store_true",
        help="List issues without making changes",
    )
    repair_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompts and repair all detected issues",
    )
    repair_parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON (for programmatic use)",
    )

    gc_parser = subparsers.add_parser(
        "gc",
        help="Prune superseded package versions and empty package stubs",
    )
    gc_parser.add_argument(
        "--keep",
        type=int,
        default=None,
        help="Versions to retain per package (default: config keep_versions or 1)",
    )
    gc_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List reclaimable versions and bytes without changing anything",
    )

    runtimes_parser = subparsers.add_parser(
        "runtimes",
        help="Inspect or print install hints for known host runtimes",
    )
    runtimes_sub = runtimes_parser.add_subparsers(
        dest="runtimes_command", help="Runtime subcommand"
    )
    runtimes_sub.add_parser("list", help="List known runtimes and their detection state")
    runtimes_install_parser = runtimes_sub.add_parser(
        "install",
        help="Print the install command for a runtime (does NOT execute it)",
    )
    runtimes_install_parser.add_argument("name", help="Runtime name (e.g. uv, node, python)")

    config_parser = subparsers.add_parser("config", help="View and manage Capacium configuration")
    config_sub = config_parser.add_subparsers(dest="config_command", help="Config subcommand")
    config_sub.add_parser("list", help="List all configuration values")
    config_set_parser = config_sub.add_parser("set", help="Set a configuration value")
    config_set_parser.add_argument("key", help="Configuration key")
    config_set_parser.add_argument("value", help="Configuration value (valid JSON)")
    config_get_parser = config_sub.add_parser("get", help="Get a configuration value")
    config_get_parser.add_argument("key", help="Configuration key")
    config_fp_parser = config_sub.add_parser(
        "fingerprint",
        help="Hash all client configs + skills dirs (pre/post gate for agent runs)",
    )
    config_fp_parser.add_argument("--json", action="store_true", help="Per-surface hashes as JSON")

    submit_parser = subparsers.add_parser("submit", help="Submit a GitHub repository for indexing on the Exchange")
    submit_parser.add_argument("github_url", help="GitHub repository URL (https://github.com/owner/repo)")
    submit_parser.add_argument("--registry", help="Target registry URL (defaults to configured Exchange)")

    hold_parser = subparsers.add_parser("hold", help="Protect a locally patched capability from update overwrites")
    hold_parser.add_argument("capability", nargs="?", help="Capability (owner/name); omit with --list")
    hold_parser.add_argument("--reason", help="Why the package is held (e.g. pending upstream PR)")
    hold_parser.add_argument("--list", action="store_true", help="List all holds")

    unhold_parser = subparsers.add_parser("unhold", help="Release a hold set with 'cap hold'")
    unhold_parser.add_argument("capability", help="Capability (owner/name)")

    block_parser = subparsers.add_parser("block", help="Mark a capability as blocked by an upstream defect (honest status)")
    block_parser.add_argument("capability", help="Capability (owner/name)")
    block_parser.add_argument("--reason", required=True, help="Why the capability cannot work (upstream defect)")
    block_parser.add_argument("--issue", help="Tracking link (upstream issue/republish)")

    unblock_parser = subparsers.add_parser("unblock", help="Clear a blocked status set with 'cap block'")
    unblock_parser.add_argument("capability", help="Capability (owner/name)")

    submit_tarball_parser = subparsers.add_parser("submit-tarball", help="Upload a capability tarball to the Exchange")
    submit_tarball_parser.add_argument("tarball_path", help="Path to .tar.gz file")

    key_parser = subparsers.add_parser("key", help="Manage Ed25519 signing keys")
    key_sub = key_parser.add_subparsers(dest="key_command", help="Key subcommand")
    key_gen_parser = key_sub.add_parser("generate", help="Generate a new Ed25519 keypair")
    key_gen_parser.add_argument("name", help="Key name")
    key_sub.add_parser("list", help="List available keys")
    key_export_parser = key_sub.add_parser("export", help="Export public key as PEM")
    key_export_parser.add_argument("name", help="Key name")
    key_import_parser = key_sub.add_parser("import", help="Import a key from a PEM file")
    key_import_parser.add_argument("name", help="Key name")
    key_import_parser.add_argument("pem_file", help="Path to PEM file")
    # P0-003: cap key show [--public] <name> — human-friendly alias for export
    key_show_parser = key_sub.add_parser("show", help="Show a key (public PEM by default)")
    key_show_parser.add_argument("name", help="Key name")
    key_show_parser.add_argument("--public", action="store_true", default=True,
                                 help="Show public key as PEM (default)")

    sign_parser = subparsers.add_parser("sign", help="Sign a capability with an Ed25519 key")
    sign_parser.add_argument("capability", help="Capability specification (owner/name[@version])")
    sign_parser.add_argument("key_name", help="Name of the signing key")

    # CAP-011: Framework adaptation
    adapt_parser = subparsers.add_parser(
        "adapt",
        help="Adapt a capability to a target framework format (MCP, A2A, AWS, etc.)",
    )
    adapt_parser.add_argument(
        "capability",
        nargs="?",
        help="Capability canonical name (owner/name) or local path",
    )
    adapt_parser.add_argument(
        "--target",
        required=False,
        help="Target framework: mcp-server, a2a-agent, aws-agentcore, opencode, claude-desktop",
    )
    adapt_parser.add_argument(
        "--output",
        help="Write output to file instead of stdout",
    )
    adapt_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    adapt_parser.add_argument(
        "--registry",
        help="Registry URL to fetch capability metadata from",
    )
    adapt_parser.add_argument(
        "--list-targets",
        action="store_true",
        help="List available adaptation targets",
    )
    # Legacy args kept for backward compat
    adapt_parser.add_argument("path", nargs="?", default=".", help=argparse.SUPPRESS)
    adapt_parser.add_argument("--transport", default=None, help=argparse.SUPPRESS)
    adapt_parser.add_argument("--command", dest="adapt_command", default=None, help=argparse.SUPPRESS)
    adapt_parser.add_argument("--args", dest="adapt_args", default=None, help=argparse.SUPPRESS)

    subparsers.add_parser("version", help="Print Capacium version")

    # Export subcommands
    export_a2a_parser = subparsers.add_parser("export-a2a", help="Export capability as A2A Agent Card")
    export_a2a_parser.add_argument("capability", help="Capability canonical name (owner/name)")
    export_a2a_parser.add_argument("--output", help="Write to file instead of stdout")

    export_aws_parser = subparsers.add_parser("export-aws", help="Export capability as AWS AgentCore Registry descriptor")
    export_aws_parser.add_argument("capability", help="Capability canonical name (owner/name)")
    export_aws_parser.add_argument("--output", help="Write to file instead of stdout")

    export_mcp_parser = subparsers.add_parser("export-mcp", help="Export capability as MCP server descriptor")
    export_mcp_parser.add_argument("capability", help="Capability canonical name (owner/name)")
    export_mcp_parser.add_argument("--output", help="Write to file instead of stdout")

    export_parser = subparsers.add_parser("export", help="Generic capability export")
    export_parser.add_argument("capability", help="Capability canonical name (owner/name)")
    export_parser.add_argument("--target", required=True, help="Export target (mcp-server, a2a-agent, aws-agentcore, opencode)")
    export_parser.add_argument("--output", help="Write to file instead of stdout")

    license_parser = subparsers.add_parser("license", help="Manage license keys for paid capabilities")
    license_sub = license_parser.add_subparsers(dest="license_command", help="License subcommand")

    license_issue_parser = license_sub.add_parser("issue", help="Issue a new license")
    license_issue_parser.add_argument("capability", help="Capability identifier (owner/name)")
    license_issue_parser.add_argument("--publisher", required=True, help="Publisher identifier")
    license_issue_parser.add_argument("--licensee", required=True, help="Licensee identifier")
    license_issue_parser.add_argument("--type", choices=["free", "trial", "standard", "enterprise"], default="free", help="License type")
    license_issue_parser.add_argument("--duration", type=int, help="Duration in days")
    license_issue_parser.add_argument("--max-uses", type=int, help="Maximum uses")
    license_issue_parser.add_argument("--registry", help="Registry URL")

    license_validate_parser = license_sub.add_parser("validate", help="Validate a license token")
    license_validate_parser.add_argument("token", help="License token to validate")
    license_validate_parser.add_argument("--capability", required=True, help="Capability identifier")
    license_validate_parser.add_argument("--registry", help="Registry URL")

    license_revoke_parser = license_sub.add_parser("revoke", help="Revoke a license")
    license_revoke_parser.add_argument("license_id", help="License ID to revoke")
    license_revoke_parser.add_argument("--reason", default="", help="Revocation reason")
    license_revoke_parser.add_argument("--registry", help="Registry URL")

    license_list_parser = license_sub.add_parser("list", help="List licenses")
    license_list_parser.add_argument("--licensee", help="Filter by licensee ID")
    license_list_parser.add_argument("--capability", help="Filter by capability ID")
    license_list_parser.add_argument("--registry", help="Registry URL")

    mcp_parser = subparsers.add_parser("mcp", help="Capacium MCP server for AI agents")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", help="MCP subcommand")
    mcp_start_parser = mcp_sub.add_parser("start", help="Start the MCP server")
    mcp_start_parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "stream"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    mcp_start_parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for SSE/stream transport (default: 9999 sse, 9998 stream)",
    )
    mcp_start_parser.add_argument(
        "--exchange-url",
        default="",
        help="Exchange API base URL",
    )

    # P1-003: cap skills-mcp — manage the Capacium skills MCP wrapper
    skills_mcp_parser = subparsers.add_parser(
        "skills-mcp",
        help="Manage the Capacium skills MCP wrapper (exposes installed skills to Claude Desktop)",
    )
    skills_mcp_sub = skills_mcp_parser.add_subparsers(
        dest="skills_mcp_command", help="skills-mcp subcommand"
    )
    skills_mcp_start_parser = skills_mcp_sub.add_parser(
        "start",
        help="Start the MCP stdio server (passes control to capacium-skills-mcp process)",
    )
    skills_mcp_start_parser.add_argument(
        "--cap-home",
        default=None,
        metavar="DIR",
        help="Capacium package cache directory (default: ~/.capacium/packages)",
    )
    skills_mcp_status_parser = skills_mcp_sub.add_parser(
        "status",
        help="Show MCP wrapper registration status and installed skills",
    )
    skills_mcp_status_parser.add_argument(
        "--cap-home",
        default=None,
        metavar="DIR",
        help="Capacium package cache directory (default: ~/.capacium/packages)",
    )
    skills_mcp_list_parser = skills_mcp_sub.add_parser(
        "list",
        help="List installed skills (name, version, description)",
    )
    skills_mcp_list_parser.add_argument(
        "--cap-home",
        default=None,
        metavar="DIR",
        help="Capacium package cache directory (default: ~/.capacium/packages)",
    )
    skills_mcp_list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    # V3 guard: sandboxed runs must not see the real account home.
    from .commands.sandbox import sandbox_guard
    sandbox_guard()

    try:
        if args.command == "install":
            from .commands.install import install_capability
            source_dir = Path(args.source) if args.source else None
            cap_spec = args.capability or ""
            if args.version:
                cap_spec = f"{args.capability}@{args.version}" if args.capability else f"@{args.version}"

            # W50-002: policy-as-code enforcement — fetch capability info BEFORE install
            policy_path = getattr(args, "policy", None)
            if policy_path and cap_spec:
                try:
                    from .commands.policy import enforce_policy
                    from .commands._resolve import resolve_capability_info
                    registry_url = getattr(args, "registry", None)
                    cap_info = resolve_capability_info(cap_spec, registry_url=registry_url)
                    if cap_info:
                        enforce_policy(cap_info, policy_path)
                    # enforce_policy sys.exit(3) on violation; continues if compliant
                except SystemExit:
                    raise
                except Exception as _pol_err:
                    import sys as _sys
                    print(f"[cap] Policy check failed: {_pol_err}", file=_sys.stderr)
                    _sys.exit(3)

            success = install_capability(
                cap_spec,
                source_dir,
                no_lock=args.no_lock,
                skip_runtime_check=getattr(args, "skip_runtime_check", False),
                all_frameworks=getattr(args, "all_frameworks", False),
                offline=getattr(args, "offline", False),
                framework=getattr(args, "framework", None),
                force=getattr(args, "force", False),
                prune=getattr(args, "prune", False),
                from_tarball=getattr(args, "from_tarball", None),
                yes=getattr(args, "yes", False),
                github_token=getattr(args, "token", None) or os.environ.get("GITHUB_TOKEN"),
                registry_url=getattr(args, "registry", None),
                project=getattr(args, "project", None),
            )
            sys.exit(0 if success else 1)

        elif args.command == "update":
            from .commands.update import update_capability
            success = update_capability(
                args.capability,
                force=getattr(args, "force", False),
                skip_runtime_check=getattr(args, "skip_runtime_check", False),
            )
            sys.exit(0 if success else 1)

        elif args.command == "remove":
            from .commands.remove import remove_capability
            success = remove_capability(args.capability, force=args.force)
            sys.exit(0 if success else 1)

        elif args.command == "list":
            from .commands.list_capabilities import list_capabilities
            list_capabilities(kind=args.kind, framework=args.framework, json_output=args.json, details=args.details)
            sys.exit(0)

        elif args.command == "search":
            from .commands.search import search_capabilities
            search_capabilities(
                args.query, kind=args.kind, registry_url=args.registry,
                category=args.category, trust=args.trust,
                min_trust=getattr(args, 'min_trust', None),
                tag=args.tag, mcp_client=getattr(args, 'mcp_client', None),
                publisher=args.publisher, sort=args.sort,
                json_output=args.json, limit=args.limit,
                framework=getattr(args, 'framework', None),
                min_stars=getattr(args, 'min_stars', None),
            )
            sys.exit(0)

        elif args.command == "browse":
            from .commands.browse import browse_capabilities
            browse_capabilities(
                sort=getattr(args, "sort", "stars"),
                min_stars=getattr(args, "min_stars", None),
                kind=getattr(args, "kind", None),
            )
            sys.exit(0)

        elif args.command == "info":
            from .commands.info import cap_info
            cap_info(
                args.capability,
                registry_url=args.registry,
                json_output=getattr(args, "json", False),
            )
            sys.exit(0)

        elif args.command == "compare":
            from .commands.compare import compare_cmd
            sys.exit(compare_cmd(args))

        elif args.command == "update-index":
            from .sync import update_cmd
            sys.exit(update_cmd(args))

        elif args.command == "init":
            template = getattr(args, "template", None)

            if template:
                # --template path: scaffold capability.yaml + SKILL.md + README.md
                from .commands.init import init_from_template
                success = init_from_template(
                    template=template,
                    name=getattr(args, "name", None),
                    version=getattr(args, "version", None) or "0.1.0",
                    description=getattr(args, "description", None) or "",
                    force=getattr(args, "force", False),
                )
                sys.exit(0 if success else 1)

            from .commands.init import init_capability

            frameworks_list = None
            if getattr(args, "frameworks", None):
                frameworks_list = [
                    f.strip() for f in args.frameworks.split(",") if f.strip()
                ]
            runtimes_dict = None
            if getattr(args, "runtimes", None):
                runtimes_dict = {}
                for pair in args.runtimes.split(","):
                    pair = pair.strip()
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        runtimes_dict[k.strip()] = v.strip()
            success = init_capability(
                name=getattr(args, "name", None),
                kind=getattr(args, "kind", None),
                version=getattr(args, "version", None),
                description=getattr(args, "description", None),
                frameworks=frameworks_list,
                runtimes=runtimes_dict,
            )
            sys.exit(0 if success else 1)

        elif args.command == "registry":
            if hasattr(args, 'registry_action') and args.registry_action:
                from .commands.registry import handle_registry
                handle_registry(args)
                sys.exit(0)
            else:
                from .commands.registry_cmd import registry_status
                success = registry_status()
                sys.exit(0 if success else 1)

        elif args.command == "verify":
            from .commands.verify import verify_capability
            if args.all:
                success = verify_capability(verify_all=True)
            elif args.capability:
                success = verify_capability(args.capability)
            else:
                print("Error: specify a capability or --all")
                sys.exit(1)
            sys.exit(0 if success else 2)

        elif args.command == "lock":
            from .commands.lock import lock_capability
            success = lock_capability(args.capability, update=args.update)
            sys.exit(0 if success else 1)

        elif args.command == "package":
            from .commands.package import package_capability
            manifest_path = Path(args.manifest) if args.manifest else Path("capability.yaml")
            output_dir = Path(args.output_dir) if args.output_dir else Path("dist")
            success = package_capability(manifest_path, output_dir)
            sys.exit(0 if success else 1)

        elif args.command == "publish":
            from .commands.publish import publish_capability
            token = args.token or os.environ.get("CAPACIUM_API_TOKEN")
            registry_arg = args.registry
            if registry_arg and registry_arg.lower() == "false":
                registry_arg = None
            success = publish_capability(
                Path(args.package_path),
                registry_url=registry_arg,
                token=token,
            )
            sys.exit(0 if success else 1)

        elif args.command == "validate":
            from .commands.validate import cmd_validate
            sys.exit(cmd_validate(args))

        elif args.command == "doctor":
            from .commands.doctor import doctor
            success = doctor(args.capability, deep=args.deep)
            sys.exit(0 if success else 1)

        elif args.command == "repair":
            from .commands.repair import repair
            success = repair(args)
            sys.exit(0 if success else 1)

        elif args.command == "gc":
            from .commands.gc import garbage_collect

            garbage_collect(keep=args.keep, dry_run=args.dry_run)
            sys.exit(0)

        elif args.command == "runtimes":
            from .commands.runtimes_cmd import list_runtimes, show_install_hint
            sub = getattr(args, "runtimes_command", None) or "list"
            if sub == "list":
                list_runtimes()
                sys.exit(0)
            elif sub == "install":
                success = show_install_hint(args.name)
                sys.exit(0 if success else 1)
            else:
                runtimes_parser.print_help()
                sys.exit(1)

        elif args.command == "config":
            from .utils.config import ConfigManager
            import json as _json
            sub = getattr(args, "config_command", None) or "list"
            if sub == "fingerprint":
                from .commands.sandbox import config_fingerprint
                config_fingerprint(json_output=getattr(args, "json", False))
                sys.exit(0)
            elif sub == "list":
                for key, value in ConfigManager.list_all().items():
                    print(f"  {key}: {_json.dumps(value)}")
                sys.exit(0)
            elif sub == "get":
                value = ConfigManager.get(args.key)
                if value is None:
                    print(f"  {args.key}: (not set)")
                else:
                    print(f"  {args.key}: {_json.dumps(value)}")
                sys.exit(0)
            elif sub == "set":
                try:
                    parsed = _json.loads(args.value)
                except _json.JSONDecodeError:
                    print("Error: value must be valid JSON")
                    sys.exit(1)
                ConfigManager.set_value(args.key, parsed)
                print(f"  {args.key} = {_json.dumps(parsed)}")
                sys.exit(0)
            else:
                config_parser.print_help()
                sys.exit(1)

        elif args.command == "hold":
            from .commands.hold import hold_capability, list_holds
            if getattr(args, "list", False) or not args.capability:
                sys.exit(0 if list_holds() else 1)
            ok = hold_capability(args.capability, reason=getattr(args, "reason", None))
            sys.exit(0 if ok else 1)

        elif args.command == "unhold":
            from .commands.hold import unhold_capability
            sys.exit(0 if unhold_capability(args.capability) else 1)

        elif args.command == "block":
            from .commands.block_status import block_capability
            ok = block_capability(args.capability, reason=args.reason,
                                  issue=getattr(args, "issue", None))
            sys.exit(0 if ok else 1)

        elif args.command == "unblock":
            from .commands.block_status import unblock_capability
            sys.exit(0 if unblock_capability(args.capability) else 1)

        elif args.command == "submit":
            from .registry_client import RegistryClientError
            from .commands.submit import submit_repository
            try:
                ok = submit_repository(
                    args.github_url,
                    registry_url=getattr(args, "registry", None),
                )
                sys.exit(0 if ok else 1)
            except RegistryClientError as e:
                msg = str(e)
                if "409" in msg:
                    print(f"Already registered: {msg}")
                else:
                    print(f"Submit failed: {msg}")
                sys.exit(1)

        elif args.command == "submit-tarball":
            from .registry_client import RegistryClient, RegistryClientError
            client = RegistryClient()
            try:
                result = client.submit_tarball(args.tarball_path)
                print(f"Uploaded: {result.get('canonical_name', 'unknown')}")
                print(f"  Kind: {result.get('kind', 'unknown')}")
                print(f"  Trust: {result.get('trust_state', 'unknown')}")
                sys.exit(0)
            except RegistryClientError as e:
                msg = str(e)
                if "409" in msg:
                    print(f"Already registered: {msg}")
                else:
                    print(f"Upload failed: {msg}")
                sys.exit(1)

        elif args.command == "marketplace":
            from .commands.marketplace import open_marketplace
            success = open_marketplace(
                search_query=getattr(args, "search", None),
                url_only=getattr(args, "url", False),
            )
            sys.exit(0 if success else 1)

        elif args.command == "key":
            from .commands.key import key_generate, key_list, key_export, key_import
            sub = getattr(args, "key_command", None) or "list"
            if sub == "generate":
                success = key_generate(args.name)
                sys.exit(0 if success else 1)
            elif sub == "list":
                success = key_list()
                sys.exit(0 if success else 1)
            elif sub == "export":
                success = key_export(args.name)
                sys.exit(0 if success else 1)
            elif sub == "import":
                success = key_import(args.name, args.pem_file)
                sys.exit(0 if success else 1)
            elif sub == "show":
                # P0-003: alias for export (--public is default and only mode for now)
                success = key_export(args.name)
                sys.exit(0 if success else 1)
            else:
                key_parser.print_help()
                sys.exit(1)

        elif args.command == "sign":
            from .commands.sign import sign_capability
            success = sign_capability(args.capability, args.key_name)
            sys.exit(0 if success else 1)

        elif args.command == "adapt":
            if args.list_targets:
                from .adapters.capability_adapter import list_adapters
                for t in list_adapters():
                    print(f"  {t}")
                sys.exit(0)
            cap = args.capability or args.path
            if cap == "." or not cap:
                print("Error: capability canonical name required (e.g. owner/name)")
                sys.exit(1)
            from .commands.adapt import adapt_capability
            success = adapt_capability(
                canonical=cap,
                target=args.target,
                registry_url=args.registry,
                json_output=args.json,
            )
            sys.exit(0 if success else 1)

        elif args.command == "export-a2a":
            from .commands.export import export_a2a
            success = export_a2a(args.capability, output=args.output)
            sys.exit(0 if success else 1)

        elif args.command == "export-aws":
            from .commands.export import export_aws
            success = export_aws(args.capability, output=args.output)
            sys.exit(0 if success else 1)

        elif args.command == "export-mcp":
            from .commands.export import export_mcp
            success = export_mcp(args.capability, output=args.output)
            sys.exit(0 if success else 1)

        elif args.command == "export":
            from .commands.export import export_generic
            success = export_generic(args.capability, args.target, output=args.output)
            sys.exit(0 if success else 1)

        elif args.command == "license":
            from .commands.license import (
                license_issue, license_validate, license_revoke, license_list,
            )
            sub = getattr(args, "license_command", None)
            if sub == "issue":
                success = license_issue(
                    args.capability, args.publisher, args.licensee,
                    license_type=args.type,
                    duration_days=args.duration,
                    max_uses=args.max_uses,
                    registry_url=args.registry,
                )
            elif sub == "validate":
                success = license_validate(
                    args.token, args.capability,
                    registry_url=args.registry,
                )
            elif sub == "revoke":
                success = license_revoke(
                    args.license_id, reason=args.reason,
                    registry_url=args.registry,
                )
            elif sub == "list":
                success = license_list(
                    licensee_id=args.licensee,
                    capability_id=args.capability,
                    registry_url=args.registry,
                )
            else:
                print("Error: specify a license subcommand (issue, validate, revoke, list)")
                sys.exit(1)
            sys.exit(0 if success else 1)

        elif args.command == "version":
            print(f"cap {__version__}")
            sys.exit(0)

        elif args.command == "mcp":
            try:
                from capacium_crawler.mcp_server import main as mcp_main
            except ImportError:
                print("Error: capacium-crawler package not installed.")
                print("  Install with: pip install capacium-crawler")
                sys.exit(1)
            sub = getattr(args, "mcp_command", None) or "start"
            if sub == "start":
                import_argv = ["capacium-mcp"]
                if getattr(args, "transport", "stdio") != "stdio":
                    import_argv.append(f"--transport={args.transport}")
                if getattr(args, "port", 0):
                    import_argv.append(f"--port={args.port}")
                if getattr(args, "exchange_url", ""):
                    import_argv.append(f"--exchange-url={args.exchange_url}")
                sys.argv = import_argv
                mcp_main()
            else:
                mcp_parser.print_help()
                sys.exit(1)

        elif args.command == "skills-mcp":
            # P1-003: skills MCP wrapper management
            from .commands.skills_mcp import (
                skills_mcp_start,
                skills_mcp_status,
                skills_mcp_list,
            )
            from pathlib import Path as _Path
            sub = getattr(args, "skills_mcp_command", None)
            cap_home_arg = getattr(args, "cap_home", None)
            cap_home_path = _Path(cap_home_arg).expanduser() if cap_home_arg else None

            if sub == "start":
                skills_mcp_start(cap_home=cap_home_path)
                # skills_mcp_start uses os.execv — control does not return here
                sys.exit(0)
            elif sub == "status":
                success = skills_mcp_status(cap_home=cap_home_path)
                sys.exit(0 if success else 1)
            elif sub == "list":
                success = skills_mcp_list(
                    cap_home=cap_home_path,
                    json_output=getattr(args, "json", False),
                )
                sys.exit(0 if success else 1)
            else:
                skills_mcp_parser.print_help()
                sys.exit(1)

        else:
            parser.print_help()
            sys.exit(1)

    except ImportError as e:
        print(f"Error: Command module not available: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
