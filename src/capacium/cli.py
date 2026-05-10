import argparse
import os
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
    install_parser.add_argument(
        "--token",
        help="GitHub token for private repositories (or set GITHUB_TOKEN)",
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
        help="Capability kind (skill, tool, prompt, mcp-server, template, bundle, workflow, connector-pack)",
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
    package_parser.add_argument("--manifest", help="Path to capability.yaml (default: capability.yaml in current directory)")
    package_parser.add_argument("--output-dir", default="./dist/", help="Output directory (default: ./dist/)")

    publish_parser = subparsers.add_parser("publish", help="Publish a capability to the Exchange registry")
    publish_parser.add_argument("package_path", help="Path to .tar.gz, capability.yaml, or directory containing capability.yaml")
    publish_parser.add_argument("--token", help="API token for the Exchange registry (or set CAPACIUM_API_TOKEN)")
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

    subparsers.add_parser("version", help="Print Capacium version")

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
                github_token=getattr(args, "token", None) or os.environ.get("GITHUB_TOKEN"),
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
            print("Capacium Marketplace: https://capacium.xyz")
            print("Run locally:")
            print("  cd src/capacium/marketplace && npm run dev")
            sys.exit(0)

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
