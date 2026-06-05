#!/usr/bin/env bash
# Generate SHA-256 checksums for all release artifacts
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version>" >&2
    exit 1
fi

CHECKSUMS_FILE="SHA256SUMS"

# Remove any existing checksums file for a clean slate
rm -f "$CHECKSUMS_FILE"

# Generate checksums for all release artifacts in dist/
if [ -d dist ]; then
    find dist/ -type f \( -name "capacium*" -o -name "cap-*" -o -name "*.tar.gz" -o -name "*.whl" -o -name "*.zip" \) | sort -r | while read -r file; do
        shasum -a 256 "$file" >> "$CHECKSUMS_FILE"
    done
fi

# Also checksum the tarball if present (from release.sh tarball step)
if [ -f "/tmp/capacium-v${VERSION}.tar.gz" ]; then
    shasum -a 256 "/tmp/capacium-v${VERSION}.tar.gz" >> "$CHECKSUMS_FILE"
fi

if [ -f "$CHECKSUMS_FILE" ] && [ -s "$CHECKSUMS_FILE" ]; then
    echo "Checksums written to $CHECKSUMS_FILE"
    cat "$CHECKSUMS_FILE"
else
    echo "No artifacts found in dist/ — checksums file not created" >&2
fi
