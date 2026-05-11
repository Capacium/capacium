import tarfile
from pathlib import Path
from ..manifest import Manifest


def package_capability(manifest_path: Path, output_dir: Path) -> bool:
    manifest_path = manifest_path.resolve()

    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}")
        return False

    manifest = Manifest.load(manifest_path)

    if not manifest.name:
        print("Error: manifest missing required field 'name'")
        return False
    if not manifest.kind:
        print("Error: manifest missing required field 'kind'")
        return False
    if not manifest.version:
        print("Error: manifest missing required field 'version'")
        return False

    owner = manifest.owner or "local"
    filename = f"{owner}-{manifest.name}-{manifest.version}.tar.gz"

    base_dir = manifest_path.parent

    files = [manifest_path]

    for name in ("SKILL.md", "README.md"):
        p = base_dir / name
        if p.exists():
            files.append(p)

    assets_dir = base_dir / "assets"
    if assets_dir.exists() and assets_dir.is_dir():
        files.append(assets_dir)

    if manifest.kind == "mcp-server":
        for py_file in sorted(base_dir.rglob("*.py")):
            if "__pycache__" not in py_file.parts and py_file not in files:
                files.append(py_file)

    _collect_entrypoint_files(base_dir, manifest, files)
    _collect_mcp_arg_files(base_dir, manifest, files)
    _collect_package_manager_files(base_dir, files)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if output_path.exists():
        print(f"Warning: {output_path} already exists and will be overwritten")

    try:
        with tarfile.open(output_path, "w:gz") as tar:
            for file_path in files:
                arcname = file_path.relative_to(base_dir)
                tar.add(file_path, arcname=str(arcname))

        print(f"Packaged {filename}")
        print(f"  output: {output_path}")
        return True

    except Exception as e:
        print(f"Error packaging capability: {e}")
        return False


def _collect_entrypoint_files(base_dir: Path, manifest: Manifest, files: list) -> None:
    entrypoint = getattr(manifest, "entrypoint", None) or ""
    if not entrypoint:
        return
    ep_path = base_dir / entrypoint
    if not ep_path.exists():
        return
    if ep_path.is_dir():
        for item in sorted(ep_path.rglob("*")):
            if "__pycache__" not in item.parts and "node_modules" not in item.parts:
                if item.is_file() and item not in files:
                    files.append(item)
    else:
        if ep_path not in files:
            files.append(ep_path)


def _collect_mcp_arg_files(base_dir: Path, manifest: Manifest, files: list) -> None:
    mcp = getattr(manifest, "mcp", None) or {}
    if not isinstance(mcp, dict):
        return
    args = mcp.get("args") or []
    if not isinstance(args, list):
        return
    for arg in args:
        if not isinstance(arg, str):
            continue
        p = base_dir / arg
        if not p.exists():
            continue
        if p.is_dir():
            for item in sorted(p.rglob("*")):
                if "__pycache__" not in item.parts and "node_modules" not in item.parts:
                    if item.is_file() and item not in files:
                        files.append(item)
        else:
            if p not in files:
                files.append(p)


def _collect_package_manager_files(base_dir: Path, files: list) -> None:
    for name in ("package.json", "package-lock.json", "pyproject.toml", "requirements.txt"):
        p = base_dir / name
        if p.exists() and p not in files:
            files.append(p)
