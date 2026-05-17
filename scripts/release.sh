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
if [ ! -d "$TAP_DIR" ]; then
    echo -e "${YELLOW}  Tap not found at ${TAP_DIR} — cloning...${NC}"
    git clone https://github.com/Capacium/homebrew-tap "$TAP_DIR"
fi
# Ensure remote points to the Capacium org (not the old capacium org redirect)
TAP_REMOTE=$(git -C "$TAP_DIR" remote get-url origin 2>/dev/null || echo "")
if echo "$TAP_REMOTE" | grep -q "capacium/homebrew-tap$"; then
    git -C "$TAP_DIR" remote set-url origin https://github.com/Capacium/homebrew-tap
fi
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
rm -rf build/lib/ dist/ *.egg-info
ruff check src/ tests/ --fix || { echo -e "${RED}ruff failed${NC}"; exit 1; }
python3 -m pytest tests/ -q --ignore=tests/test_publish.py --ignore=tests/test_signing.py || { echo -e "${RED}pytest failed${NC}"; exit 1; }
echo -e "${GREEN}  Tests pass${NC}"

# ── Step 2: Bump versions ──────────────────────────────────────
echo -e "${YELLOW}[2/8] Bumping version to ${VERSION}...${NC}"

# pyproject.toml
sed -i '' "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml

# README.md
sed -i '' -E "s/@v[0-9]+\.[0-9]+\.[0-9]+/@v${VERSION}/g" README.md
sed -i '' -E "s/cap:[0-9]+\.[0-9]+\.[0-9]+/cap:${VERSION}/g" README.md
sed -i '' -E "s|capacium\.git@v[0-9]+\.[0-9]+\.[0-9]+|capacium.git@v${VERSION}|g" README.md
sed -i '' -E "s|ghcr\.io/capacium/cap:[0-9]+\.[0-9]+\.[0-9]+|ghcr.io/capacium/cap:${VERSION}|g" README.md

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
sleep 5

# Use gh run watch for server-side polling (single API call, no rate-limit burn)
GH_WORKFLOW_ID=ci.yml
LATEST_RUN_ID=$(gh run list --repo "$GITHUB_REPO" --branch=main --workflow="$GH_WORKFLOW_ID" --limit=1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || echo "")
if [ -n "$LATEST_RUN_ID" ] && [ "$LATEST_RUN_ID" != "null" ]; then
    if gh run watch "$LATEST_RUN_ID" --repo "$GITHUB_REPO" --exit-status 2>/dev/null; then
        echo -e "${GREEN}  CI passed${NC}"
    else
        CONCLUSION=$(gh run view "$LATEST_RUN_ID" --repo "$GITHUB_REPO" --json conclusion --jq '.conclusion' 2>/dev/null || echo "unknown")
        if [ "$CONCLUSION" = "failure" ] || [ "$CONCLUSION" = "cancelled" ] || [ "$CONCLUSION" = "timed_out" ]; then
            echo -e "${RED}  CI failed (${CONCLUSION}) — aborting release${NC}"
            exit 1
        fi
        echo -e "${YELLOW}  CI watch exited unexpectedly (${CONCLUSION}), proceeding anyway...${NC}"
    fi
else
    echo -e "${YELLOW}  Could not find CI run — proceeding anyway${NC}"
fi

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

# Build release notes from commits since last tag
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -n "$LAST_TAG" ] && [ "$LAST_TAG" != "$TAG" ]; then
    COMMITS=$(git log "${LAST_TAG}..HEAD" --oneline --no-merges 2>/dev/null)
else
    COMMITS=$(git log --oneline --no-merges --max-count=10 2>/dev/null)
fi
CHANGES=""
while IFS= read -r line; do
    [ -n "$line" ] && CHANGES="${CHANGES}- ${line}\n"
done <<< "$COMMITS"

NOTES="## Capacium v${VERSION}

### What's Changed
${CHANGES:-See [full changelog](https://github.com/${GITHUB_REPO}/commits/${TAG})}

### Install
\`\`\`bash
brew update && brew upgrade capacium
cap -v  # → ${VERSION}
\`\`\`
"

RELEASE_TITLE="Capacium v${VERSION}"

if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "  DRY RUN: would create release ${TAG}"
else
    if gh release view "$TAG" --repo "$GITHUB_REPO" &>/dev/null; then
        gh release edit "$TAG" --repo "$GITHUB_REPO" --title "$RELEASE_TITLE" --notes "$NOTES"
    else
        gh release create "$TAG" --repo "$GITHUB_REPO" --title "$RELEASE_TITLE" --notes "$NOTES"
    fi
    echo -e "${GREEN}  Release created${NC}"
fi

# ── Step 7b: Verify release title matches naming convention ─────
echo -e "${YELLOW}[7b/8] Verifying release title...${NC}"
RELEASE_NAME=$(gh release view "$TAG" --repo "$GITHUB_REPO" --json name --jq '.name' 2>/dev/null || echo "")
if [ "$RELEASE_NAME" != "$RELEASE_TITLE" ]; then
    echo -e "${RED}  Release title mismatch: expected '${RELEASE_TITLE}', got '${RELEASE_NAME}'${NC}"
    echo -e "${RED}  Fixing...${NC}"
    gh release edit "$TAG" --repo "$GITHUB_REPO" --title "$RELEASE_TITLE" 2>/dev/null || {
        echo -e "${RED}  Failed to fix title — manual intervention required${NC}"
        echo "  gh release edit ${TAG} --repo ${GITHUB_REPO} --title '${RELEASE_TITLE}'"
        exit 1
    }
fi
echo -e "${GREEN}  Title verified: ${RELEASE_TITLE}${NC}"

# ── Step 8: Brew upgrade locally ───────────────────────────────
echo -e "${YELLOW}[8/8] Upgrading local Brew...${NC}"
brew update && brew upgrade capacium 2>/dev/null || brew reinstall capacium 2>/dev/null || true
echo -e "${GREEN}  Brew upgraded${NC}"

echo ""
echo -e "${GREEN}=== Release v${VERSION} complete! ===${NC}"
echo "  cap -v  # verify"
echo "  https://github.com/${GITHUB_REPO}/releases/tag/${TAG}"
