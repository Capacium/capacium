import json
import os
from pathlib import Path

REGISTRIES_FILE = os.path.expanduser("~/.capacium/registries.json")


def _load_registries():
    path = Path(REGISTRIES_FILE)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_registries(data):
    Path(REGISTRIES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(REGISTRIES_FILE).write_text(json.dumps(data, indent=2))


def handle_registry(args):
    registries = _load_registries()

    if args.registry_action == "add":
        registries[args.name] = {"url": args.url, "default": False}
        _save_registries(registries)
        print(f"Registry '{args.name}' added: {args.url}")

    elif args.registry_action == "login":
        if args.name not in registries:
            print(f"Registry '{args.name}' not found. Add it first with: cap registry add {args.name} <url>")
            return
        url = registries[args.name]["url"]
        auth_url = f"{url}/v2/auth/oidc/login"
        print(f"Opening SSO login for {args.name}...")
        print(f"Visit: {auth_url}")
        print("After login, paste your token:")
        token = input().strip()
        token_path = Path(os.path.expanduser(f"~/.capacium/auth/{args.name}.token"))
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token)
        print(f"Logged in to '{args.name}'")

    elif args.registry_action == "logout":
        token_path = Path(os.path.expanduser(f"~/.capacium/auth/{args.name}.token"))
        if token_path.exists():
            token_path.unlink()
        print(f"Logged out of '{args.name}'")

    elif args.registry_action == "list":
        if not registries:
            print("No registries configured.")
            print("Add one with: cap registry add <name> <url>")
            return
        for name, info in registries.items():
            token_path = Path(os.path.expanduser(f"~/.capacium/auth/{name}.token"))
            logged_in = "✓ logged in" if token_path.exists() else "✗ not logged in"
            default = " (default)" if info.get("default") else ""
            print(f"  {name}: {info['url']} {logged_in}{default}")

    elif args.registry_action == "remove":
        if args.name in registries:
            del registries[args.name]
            _save_registries(registries)
            print(f"Registry '{args.name}' removed")
        else:
            print(f"Registry '{args.name}' not found")

    elif args.registry_action == "set-default":
        if args.name not in registries:
            print(f"Registry '{args.name}' not found")
            return
        for n in registries:
            registries[n]["default"] = (n == args.name)
        _save_registries(registries)
        print(f"'{args.name}' is now the default registry")


def add_registry_parser(subparsers):
    parser = subparsers.add_parser("registry", help="Manage private Capacium registries")
    sub = parser.add_subparsers(dest="registry_action")

    add_parser = sub.add_parser("add", help="Add a private registry")
    add_parser.add_argument("name", help="Registry name (e.g. acme)")
    add_parser.add_argument("url", help="Registry URL (e.g. https://skills.acme.com)")

    login_parser = sub.add_parser("login", help="Log in to a registry via SSO")
    login_parser.add_argument("name", help="Registry name")

    logout_parser = sub.add_parser("logout", help="Log out of a registry")
    logout_parser.add_argument("name", help="Registry name")

    sub.add_parser("list", help="List configured registries")

    remove_parser = sub.add_parser("remove", help="Remove a registry")
    remove_parser.add_argument("name", help="Registry name")

    set_default_parser = sub.add_parser("set-default", help="Set default registry")
    set_default_parser.add_argument("name", help="Registry name")
