#!/usr/bin/env bash
# Sign release checksums with Ed25519
set -euo pipefail

CHECKSUMS_FILE="${1:-SHA256SUMS}"
PRIVATE_KEY="${CAPACIUM_SIGNING_KEY:-}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "$PRIVATE_KEY" ]; then
    echo "CAPACIUM_SIGNING_KEY not set. Skipping signing." >&2
    exit 0
fi

if [ ! -f "$CHECKSUMS_FILE" ]; then
    echo "Checksums file not found: $CHECKSUMS_FILE" >&2
    exit 1
fi

cd "$REPO_DIR" || exit 1

python3 -c "
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path('$REPO_DIR') / 'src'))
from capacium.signing import sign

checksums_path = Path('$CHECKSUMS_FILE')
data = checksums_path.read_bytes()

try:
    privkey = base64.b64decode('$PRIVATE_KEY')
except Exception:
    print('Invalid base64 in CAPACIUM_SIGNING_KEY', file=sys.stderr)
    sys.exit(1)

signature = sign(privkey, data)
sig_path = checksums_path.with_suffix(checksums_path.suffix + '.sig')
sig_path.write_bytes(signature)
print(f'Signed {checksums_path} -> {sig_path}')
"

echo "Signed ${CHECKSUMS_FILE} → ${CHECKSUMS_FILE}.sig"
