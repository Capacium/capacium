#!/usr/bin/env bash
# Capacium Release Script — one command to rule them all
# Usage: ./scripts/release.sh <version> [--dry-run]
#
# Flow: bump → verify → commit → push → wait CI → tag → tarball → tap → brew → release

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

VERSION="${1:-}"
DRY_RUN="${2:-}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TAP_DIR="/opt/homebrew/Library/Taps/capacium/homebrew-tap"
GITHUB_REPO="Capacium/capacium"

if [ -z "$VERSION" ]; then
    echo -e "${RED}Usage: $0 <version> [--dry-run]${NC}"
    echo "Example: $0 0.10.9"
    exit 1
fi

# Strip leading 'v' if present
VERSION="${VERSION#v}"
TAG="v${VERSION}"

echo -e "${GREEN}=== Capacium Release v${VERSION} ===${NC}"

# ── Step 1: Local verification ────────────────────────────────
echo -e "${YELLOW}[1/8] Running ruff + pytest...${NC}"
cd "$REPO_DIR"
ruff check src/ tests/ --fix || { echo -e "${RED}ruff failed${NC}"; exit 1; }
python -m pytest tests/ -q --ignore=tests/test_signing.py || { echo -e "${RED}pytest failed${NC}"; exit 1; }
echo -e "${GREEN}  Tests pass${NC}"

# ── Step 2: Bump versions ──────────────────────────────────────
echo -e "${YELLOW}[2/8] Bumping version to ${VERSION}...${NC}"

# pyproject.toml
sed -i '' "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml

# README.md
sed -i '' "s/@v[0-9]\+\.[0-9]\+\.[0-9]\+/@v${VERSION}/g" README.md
sed -i '' "s/cap:[0-9]\+\.[0-9]\+\.[0-9]\+/cap:${VERSION}/g" README.md
sed -i '' "s|capacium.git@v[0-9]\+\.[0-9]\+\.[0-9]\+|capacium.git@v${VERSION}|g" README.md
sed -i '' "s|ghcr.io/capacium/cap:[0-9]\+\.[0-9]\+\.[0-9]\+|ghcr.io/capacium/cap:${VERSION}|g" README.md

echo -e "${GREEN}  pyproject.toml → ${VERSION}${NC}"
echo -e "${GREEN}  README.md → ${VERSION}${NC}"

# ── Step 3: Commit version bump ────────────────────────────────
echo -e "${YELLOW}[3/8] Committing version bump...${NC}"
git add pyproject.toml README.md || true
if git diff --cached --quiet; then
    echo "  No changes to commit"
else
    git commit -m "chore: bump to v${VERSION}"
    echo -e "${GREEN}  Committed${NC}"
fi

# ── Step 4: Push and wait for CI ───────────────────────────────
echo -e "${YELLOW}[4/8] Pushing to main...${NC}"
git push origin main

echo "  Waiting for CI to pass..."
sleep 10
for i in $(seq 1 30); do
    CONCLUSION=$(gh run list --repo "$GITHUB_REPO" --branch=main --workflow=ci.yml --limit=1 --json conclusion --jq '.[0].conclusion' 2>/dev/null || echo "null")
    STATUS=$(gh run list --repo "$GITHUB_REPO" --branch=main --workflow=ci.yml --limit=1 --json status --jq '.[0].status' 2>/dev/null || echo "null")
    if [ "$CONCLUSION" = "success" ]; then
        echo -e "${GREEN}  CI passed${NC}"
        break
    elif [ "$CONCLUSION" = "failure" ]; then
        echo -e "${RED}  CI failed — aborting release${NC}"
        exit 1
    fi
    echo "  Waiting... (${i}/30) status=${STATUS} conclusion=${CONCLUSION}"
    sleep 15
done

# ── Step 5: Tag and push tag ───────────────────────────────────
echo -e "${YELLOW}[5/8] Creating tag ${TAG}...${NC}"
if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "  DRY RUN: would tag ${TAG}"
else
    git tag -d "$TAG" 2>/dev/null || true
    git tag "$TAG"
    git push origin "$TAG"
    echo -e "${GREEN}  Tagged ${TAG}${NC}"
fi

# ── Step 6: Build tarball and update Homebrew Tap ──────────────
echo -e "${YELLOW}[6/8] Updating Homebrew Tap...${NC}"

URL="https://github.com/${GITHUB_REPO}/archive/refs/tags/${TAG}.tar.gz"
TARBALL="/tmp/capacium-${TAG}.tar.gz"
curl -sSL "$URL" -o "$TARBALL"
SHA=$(shasum -a 256 "$TARBALL" | awk '{print $1}')
echo "  SHA256: $SHA"

if [ -d "$TAP_DIR" ]; then
    cd "$TAP_DIR"
    git pull --rebase origin main 2>/dev/null || true

    # Update url and sha256 in formula
    sed -i '' "s|url \".*capacium/archive/refs/tags/v[^\"]*\"|url \"${URL}\"|" Formula/capacium.rb
    sed -i '' "s|sha256 \"[a-f0-9]*\"|sha256 \"${SHA}\"|" Formula/capacium.rb

    if git diff --quiet; then
        echo "  Tap already up to date"
    else
        git add Formula/capacium.rb
        git commit -m "chore(capacium): bump to ${TAG}"
        git push origin main
        echo -e "${GREEN}  Tap updated${NC}"
    fi
else
    echo -e "${YELLOW}  Tap dir not found at ${TAP_DIR} — skipping (CI will handle it)${NC}"
fi

cd "$REPO_DIR"

# ── Step 7: Create GitHub Release ──────────────────────────────
echo -e "${YELLOW}[7/8] Creating GitHub Release...${NC}"
NOTES="## Capacium v${VERSION}

### What's Changed
- See [full changelog](https://github.com/${GITHUB_REPO}/commits/${TAG})

### Install
\`\`\`bash
brew update && brew upgrade capacium
cap -v  # → ${VERSION}
\`\`\`
"

if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "  DRY RUN: would create release ${TAG}"
else
    if gh release view "$TAG" --repo "$GITHUB_REPO" &>/dev/null; then
        gh release edit "$TAG" --repo "$GITHUB_REPO" --title "Capacium ${TAG}" --notes "$NOTES"
    else
        gh release create "$TAG" --repo "$GITHUB_REPO" --title "Capacium ${TAG}" --notes "$NOTES"
    fi
    echo -e "${GREEN}  Release created${NC}"
fi

# ── Step 8: Brew upgrade locally ───────────────────────────────
echo -e "${YELLOW}[8/8] Upgrading local Brew...${NC}"
brew update && brew upgrade capacium 2>/dev/null || brew reinstall capacium 2>/dev/null || true
echo -e "${GREEN}  Brew upgraded${NC}"

echo ""
echo -e "${GREEN}=== Release v${VERSION} complete! ===${NC}"
echo "  cap -v  # verify"
echo "  https://github.com/${GITHUB_REPO}/releases/tag/${TAG}"
