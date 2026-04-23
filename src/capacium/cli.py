import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="cap",
        description="Capacium - Capability Packaging System for AI agent capabilities",
        epilog="For more information, visit https://github.com/typelicious/capacium"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version="%(prog)s 0.1.0"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    install_parser = subparsers.add_parser("install", help="Install a capability")
    install_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")
    install_parser.add_argument("--version", help="Specific version to install")
    install_parser.add_argument("--source", help="Source directory (defaults to current directory)")
    install_parser.add_argument("--no-lock", action="store_true", help="Bypass lock file enforcement")

    update_parser = subparsers.add_parser("update", help="Update a capability")
    update_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")

    remove_parser = subparsers.add_parser("remove", help="Remove a capability")
    remove_parser.add_argument("capability", help="Capability specification (owner/name[@version] or name[@version])")
    remove_parser.add_argument("--force", action="store_true", help="Force removal including sub-capabilities with dependents")

    list_parser = subparsers.add_parser("list", help="List installed capabilities")
    list_parser.add_argument("--kind", help="Filter by kind (skill, bundle, tool, prompt, template, workflow)")

    search_parser = subparsers.add_parser("search", help="Search for capabilities")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--kind", help="Filter by kind")
    search_parser.add_argument("--registry", help="Remote registry URL to search")

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
            success = install_capability(cap_spec, source_dir, no_lock=args.no_lock)
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
            search_capabilities(args.query, kind=args.kind, registry_url=args.registry)
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
