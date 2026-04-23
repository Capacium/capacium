import json
from pathlib import Path
from ..manifest import Manifest


def publish_capability(source_dir: Path) -> bool:
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"Error: path does not exist or is not a directory: {source_dir}")
        return False

    manifest = Manifest.detect_from_directory(source_dir)

    payload = {
        "name": manifest.name,
        "owner": manifest.owner or "global",
        "version": manifest.version,
        "kind": manifest.kind,
        "description": manifest.description,
        "frameworks": manifest.frameworks,
        "dependencies": manifest.dependencies,
    }

    print("PUBLISH NOT IMPLEMENTED: would send {")
    for key, value in payload.items():
        if value:
            encoded = json.dumps(value)
            print(f"  {key}: {encoded}")
    print("}")
    return True
