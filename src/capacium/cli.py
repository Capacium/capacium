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

    update_parser = subparsers.add_parser("update", help="Update a capability")
    update_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")

    remove_parser = subparsers.add_parser("remove", help="Remove a capability")
    remove_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")
    remove_parser.add_argument("--force", action="store_true", help="Force removal including sub-capabilities with dependents")

    list_parser = subparsers.add_parser("list", help="List installed capabilities")
    list_parser.add_argument("--kind", help="Filter by kind (skill, bundle, tool, prompt, template, workflow, mcp-server)")

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

    verify_parser = subparsers.add_parser("verify", help="Verify capability fingerprint")
    verify_parser.add_argument("capability", nargs="?", help="Capability to verify (omit for --all)")
    verify_parser.add_argument("--all", action="store_true", help="Verify all installed capabilities")

    lock_parser = subparsers.add_parser("lock", help="Generate capability.lock for an installed capability")
    lock_parser.add_argument("capability", help="Capability specification (owner/name)")
    lock_parser.add_argument("--update", action="store_true", help="Update existing lock file")

    package_parser = subparsers.add_parser("package", help="Package capability for distribution")
    package_parser.add_argument("path", help="Path to capability directory")
    package_parser.add_argument("--output", help="Output archive path (e.g. archive.tar.gz)")

    publish_parser = subparsers.add_parser("publish", help="Publish capability to a registry (stub)")
    publish_parser.add_argument("path", nargs="?", default=".", help="Path to capability directory (default: current directory)")
    publish_parser.add_argument("--registry", help="Target registry URL")

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

    # V2 Platform Commands (info, claim, exchange, trust, crawl) have been extracted to Capacium V3 Platform Services.

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
            )
            sys.exit(0 if success else 1)

        elif args.command == "update":
            from .commands.update import update_capability
            success = update_capability(args.capability)
            sys.exit(0 if success else 1)

        elif args.command == "remove":
            from .commands.remove import remove_capability
            success = remove_capability(args.capability, force=args.force)
            sys.exit(0 if success else 1)

        elif args.command == "list":
            from .commands.list_capabilities import list_capabilities
            list_capabilities(kind=args.kind)
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
            )
            sys.exit(0)

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
            success = publish_capability(Path(args.path))
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

# Platform subcommands (marketplace, info, claim, exchange, trust, crawl)
        # have been extracted to Capacium V3 Platform Services.

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

