import json
import tarfile
from pathlib import Path
from typing import Optional
from ..fingerprint import compute_fingerprint
from ..manifest import Manifest


def package_capability(path: Path, output: Optional[str] = None) -> bool:
    if not path.exists() or not path.is_dir():
        print(f"Error: path does not exist or is not a directory: {path}")
        return False

    manifest = Manifest.detect_from_directory(path)
    fingerprint = compute_fingerprint(path)

    if output:
        output_path = Path(output)
    else:
        output_path = path.parent / f"{manifest.name}-{manifest.version}.cap"

    try:
        with tarfile.open(output_path, "w:gz") as tar:
            for file_path in path.rglob("*"):
                if any(p.startswith(".") for p in file_path.parts):
                    if file_path.name in (".git", "__pycache__"):
                        continue
                rel_path = file_path.relative_to(path)
                tar.add(file_path, arcname=rel_path)

            metadata = manifest.to_dict()
            metadata["fingerprint"] = fingerprint
            metadata_bytes = json.dumps(metadata, indent=2).encode("utf-8")
            info = tarfile.TarInfo(name=".capacium-meta.json")
            info.size = len(metadata_bytes)
            tar.addfile(info, fileobj=__import__("io").BytesIO(metadata_bytes))

        print(f"Packaged {manifest.id}@{manifest.version}")
        print(f"  fingerprint: {fingerprint[:8]}...")
        print(f"  output: {output_path}")
        return True

    except Exception as e:
        print(f"Error packaging capability: {e}")
        return False
