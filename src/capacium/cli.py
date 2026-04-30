import argparse
import sys
from pathlib import Path

from . import __version__


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
    install_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")
    install_parser.add_argument("--version", help="Specific version to install")
    install_parser.add_argument("--source", help="Source directory (defaults to current directory)")
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
        "--from-tarball",
        help="Install from a local .tar.gz file",
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

    search_parser = subparsers.add_parser("search", help="Search for capabilities")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--kind", help="Filter by kind")
    search_parser.add_argument("--registry", help="Remote registry URL to search")
    search_parser.add_argument("--category", help="Filter by category slug")
    search_parser.add_argument("--trust", help="Filter by trust state")
    search_parser.add_argument("--min-trust", help="Filter by minimum trust state")
    search_parser.add_argument("--tag", action="append", help="Filter by tag (repeatable)")
    search_parser.add_argument("--mcp-client", help="Filter by MCP client compatibility")
    search_parser.add_argument("--publisher", help="Filter by publisher ID")
    search_parser.add_argument("--sort", choices=["relevance", "name", "trust", "updated"], default="relevance")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")
    search_parser.add_argument("--limit", type=int, default=50, help="Max results")
    search_parser.add_argument("--framework", help="Filter by target framework (e.g. cursor, claude-code)")

    info_parser = subparsers.add_parser("info", help="Show detailed information about a capability")
    info_parser.add_argument("capability", help="Capability specification (owner/name)")
    info_parser.add_argument("--registry", help="Remote registry URL")

    init_parser = subparsers.add_parser("init", help="Initialize Capacium configuration or create a new capability")
    init_sub = init_parser.add_subparsers(dest="init_command", help="Init subcommand")
    init_sub.add_parser("skill", help="Create a new capability.yaml interactively")

    registry_parser = subparsers.add_parser("registry", help="Manage Capacium registries")
    registry_sub = registry_parser.add_subparsers(dest="registry_command", help="Registry subcommand")
    registry_sub.add_parser("login", help="Authenticate with an Exchange registry")
    registry_publish_parser = registry_sub.add_parser("publish", help="Publish a capability to a registry")
    registry_publish_parser.add_argument("path", nargs="?", default=".", help="Path to capability directory (default: current directory)")
    registry_publish_parser.add_argument("--registry", help="Target registry URL")
    registry_sub.add_parser("status", help="Show connected registry information")

    verify_parser = subparsers.add_parser("verify", help="Verify capability fingerprint")
    verify_parser.add_argument("capability", nargs="?", help="Capability to verify (omit for --all)")
    verify_parser.add_argument("--all", action="store_true", help="Verify all installed capabilities")

    lock_parser = subparsers.add_parser("lock", help="Generate capability.lock for an installed capability")
    lock_parser.add_argument("capability", help="Capability specification (owner/name)")
    lock_parser.add_argument("--update", action="store_true", help="Update existing lock file")

    package_parser = subparsers.add_parser("package", help="Package capability for distribution")
    package_parser.add_argument("path", help="Path to capability directory")
    package_parser.add_argument("--output", help="Output archive path (e.g. archive.tar.gz)")

    publish_parser = subparsers.add_parser("publish", help="Publish capability to the Exchange registry")
    publish_parser.add_argument("path", nargs="?", default=".", help="Path to capability directory (default: current directory)")
    publish_parser.add_argument("--registry", help="Target registry URL")
    publish_parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without publishing")

    marketplace_parser = subparsers.add_parser("marketplace", help="Start the marketplace web UI")
    marketplace_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    marketplace_parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    marketplace_parser.add_argument("--open", action="store_true", help="Open browser automatically")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check installed capabilities for missing host runtimes",
    )
    doctor_parser.add_argument(
        "capability",
        nargs="?",
        help="Optional capability spec (owner/name) to check; defaults to all",
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

    submit_parser = subparsers.add_parser("submit", help="Submit a GitHub repository for indexing on the Exchange")
    submit_parser.add_argument("github_url", help="GitHub repository URL (https://github.com/owner/repo)")
    submit_parser.add_argument("--registry", help="Target registry URL (defaults to configured Exchange)")

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

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    try:
        if args.command == "install":
            from .commands.install import install_capability
            source_dir = Path(args.source) if args.source else None
            cap_spec = args.capability
            if args.version:
                cap_spec = f"{args.capability}@{args.version}"
            success = install_capability(
                cap_spec,
                source_dir,
                no_lock=args.no_lock,
                skip_runtime_check=getattr(args, "skip_runtime_check", False),
                all_frameworks=getattr(args, "all_frameworks", False),
                offline=getattr(args, "offline", False),
                framework=getattr(args, "framework", None),
                force=getattr(args, "force", False),
                from_tarball=getattr(args, "from_tarball", None),
                yes=getattr(args, "yes", False),
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
            list_capabilities(kind=args.kind, framework=args.framework)
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
            )
            sys.exit(0)

        elif args.command == "info":
            from .commands.search import cap_info
            cap_info(args.capability, registry_url=args.registry)
            sys.exit(0)

        elif args.command == "init":
            if getattr(args, "init_command", None) == "skill":
                from .commands.init import init_skill
                success = init_skill()
                sys.exit(0 if success else 1)
            else:
                from .commands.init import init_config
                success = init_config()
                sys.exit(0 if success else 1)

        elif args.command == "registry":
            sub = getattr(args, "registry_command", None)
            if sub == "login":
                from .commands.registry_cmd import registry_login
                success = registry_login()
                sys.exit(0 if success else 1)
            elif sub == "publish":
                from .commands.registry_cmd import registry_publish
                registry_arg = getattr(args, "registry", None)
                success = registry_publish(Path(args.path), registry_url=registry_arg)
                sys.exit(0 if success else 1)
            elif sub == "status":
                from .commands.registry_cmd import registry_status
                success = registry_status()
                sys.exit(0 if success else 1)
            else:
                registry_parser.print_help()
                sys.exit(1)

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
            success = package_capability(Path(args.path), output=args.output)
            sys.exit(0 if success else 1)

        elif args.command == "publish":
            from .commands.publish import publish_capability
            registry_arg = args.registry
            if registry_arg and registry_arg.lower() == "false":
                registry_arg = None
            success = publish_capability(
                Path(args.path),
                registry_url=registry_arg,
                dry_run=args.dry_run,
            )
            sys.exit(0 if success else 1)

        elif args.command == "doctor":
            from .commands.doctor import doctor
            success = doctor(args.capability)
            sys.exit(0 if success else 1)

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
            if sub == "list":
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

        elif args.command == "submit":
            from .registry_client import RegistryClient, RegistryClientError
            client = RegistryClient()
            try:
                result = client.submit(args.github_url, registry_url=getattr(args, "registry", None))
                print(f"Submitted: {result.get('canonical_name', 'unknown')}")
                print(f"  Kind: {result.get('kind', 'unknown')}")
                print(f"  Trust: {result.get('trust_state', 'unknown')}")
                print(f"  URL: https://capacium.xyz/listings/{result.get('canonical_name', '')}")
                sys.exit(0)
            except RegistryClientError as e:
                msg = str(e)
                if "409" in msg:
                    print(f"Already registered: {msg}")
                else:
                    print(f"Submit failed: {msg}")
                sys.exit(1)

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
