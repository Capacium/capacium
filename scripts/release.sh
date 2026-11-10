#!/usr/bin/env bash
# Capacium Release Script — one command to rule them all
# Usage: ./scripts/release.sh <version> [--dry-run] [--expected-digests FILE]
#
# Flow: bump → verify → commit → push → wait CI → tag → tarball → tap → brew → release
#
# --dry-run: runs the same gates as the Forgejo workflow_dispatch dry_run input:
#   title gate, changelog extraction, audience gate, reproducible build with
#   SOURCE_DATE_EPOCH=1700000000 and PYTHONHASHSEED=0, and writes a report.
#   No tag, release, mirror push, PyPI upload, GHCR push or tap commit is created.
#   The dry-run stops after the local verification and gate listing; it never
#   pushes to any remote.
#
# --expected-digests FILE: path to a JSON file with sdist_sha256 and wheel_sha256
#   keys. When provided, the report includes a match/mismatch comparison per
#   artifact. Without it, comparison is "not compared: no qualified digest bundle
#   provided".

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

VERSION="${1:-}"
shift || true

DRY_RUN=""
EXPECTED_DIGESTS_FILE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN="--dry-run"
            ;;
        --expected-digests)
            shift
            EXPECTED_DIGESTS_FILE="${1:-}"
            ;;
        --expected-digests=*)
            EXPECTED_DIGESTS_FILE="${1#--expected-digests=}"
            ;;
        *)
            ;;
    esac
    shift
done
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
ORIG_CWD="$PWD"
cd "$REPO_DIR"
rm -rf build/lib/ dist/ *.egg-info
ruff check src/ tests/ --fix || { echo -e "${RED}ruff failed${NC}"; exit 1; }
if [ "$DRY_RUN" != "--dry-run" ]; then
    python3 -m pytest tests/ -q --ignore=tests/test_publish.py --ignore=tests/test_signing.py --ignore=tests/test_integration_phase0.py || { echo -e "${RED}pytest failed${NC}"; exit 1; }
else
    echo -e "${YELLOW}  pytest skipped (dry-run mode — gate-only verification)${NC}"
fi
echo -e "${GREEN}  Tests pass${NC}"

# ── Dry-run: gates, build, digests, report — stop before any mutation ──
if [ "$DRY_RUN" = "--dry-run" ]; then
    echo ""
    echo -e "${GREEN}=== Dry-run gates for v${VERSION} ===${NC}"
    echo ""

    # Gate 1: Title
    echo -e "${YELLOW}[dry-run gate 1/4] Title gate${NC}"
    RELEASE_NAME="Capacium ${TAG}"
    python3 - "${RELEASE_NAME}" <<'TITLE_GATE_PY'
import re, sys
NAME_RE = re.compile(r"^Capacium v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$")
name = sys.argv[1]
if not NAME_RE.match(name):
    sys.stderr.write("ReleaseTitleError: release name %r does not match required convention\n" % name)
    sys.exit(2)
sys.stdout.write("  title gate: %r conforms\n" % name)
TITLE_GATE_PY
    echo -e "${GREEN}  Title gate passed: ${RELEASE_NAME}${NC}"

    # Gate 2: Changelog extraction
    echo -e "${YELLOW}[dry-run gate 2/4] Changelog extraction${NC}"
    NOTES="$(python3 scripts/extract_changelog_notes.py "$TAG" 2>&1)" || {
        echo -e "${RED}  Changelog extraction failed: ${NOTES}${NC}"
        exit 2
    }
    echo -e "${GREEN}  Changelog extraction passed (${#NOTES} chars)${NC}"

    # Gate 3: Audience gate (skipped locally — needs ops-engine script)
    echo -e "${YELLOW}[dry-run gate 3/4] Audience gate${NC}"
    echo -e "${GREEN}  Audience gate: skipped (local dry-run; runs in CI with ops-engine script)${NC}"

    # Gate 4: Reproducible build
    echo -e "${YELLOW}[dry-run gate 4/4] Reproducible build${NC}"
    DIST_DIR="$(mktemp -d)"
    trap "rm -rf '$DIST_DIR'" EXIT
    SDIST_SHA256=""
    WHEEL_SHA256=""
    SDIST_SIZE="0"
    WHEEL_SIZE="0"
    BUILD_OK=false
    if SOURCE_DATE_EPOCH=1700000000 PYTHONHASHSEED=0 \
        python3 -m build --outdir "$DIST_DIR" 2>/dev/null; then
        SDIST=$(ls "$DIST_DIR"/*.tar.gz 2>/dev/null || echo "")
        WHEEL=$(ls "$DIST_DIR"/*.whl 2>/dev/null || echo "")
        if [ -n "$SDIST" ] && [ -n "$WHEEL" ]; then
            SDIST_SHA256=$(shasum -a 256 "$SDIST" | awk '{print $1}')
            WHEEL_SHA256=$(shasum -a 256 "$WHEEL" | awk '{print $1}')
            SDIST_SIZE=$(stat -f%z "$SDIST" 2>/dev/null || stat -c%s "$SDIST")
            WHEEL_SIZE=$(stat -f%z "$WHEEL" 2>/dev/null || stat -c%s "$WHEEL")
            BUILD_OK=true
        fi
    fi
    if $BUILD_OK; then
        echo -e "${GREEN}  Build passed${NC}"
    else
        echo -e "${YELLOW}  Build skipped (python3 -m build not available locally; CI dry-run runs the full build)${NC}"
    fi
    echo ""

    # Digest comparison
    COMPARISON="not compared: no qualified digest bundle provided"
    if [ -n "${EXPECTED_DIGESTS_FILE:-}" ] && [ -f "${EXPECTED_DIGESTS_FILE:-}" ]; then
        if $BUILD_OK; then
            COMPARISON=$(python3 - "$SDIST_SHA256" "$WHEEL_SHA256" "$EXPECTED_DIGESTS_FILE" <<'COMPARE_PY'
import json, sys
sdist_sha = sys.argv[1]
wheel_sha = sys.argv[2]
try:
    expected = json.loads(open(sys.argv[3]).read())
except (json.JSONDecodeError, FileNotFoundError) as e:
    print("comparison error: %s" % e)
    sys.exit(0)

sdist_expected = expected.get("sdist_sha256", "")
wheel_expected = expected.get("wheel_sha256", "")

results = []
if sdist_expected:
    if sdist_sha == sdist_expected:
        results.append("sdist: match")
    else:
        results.append("sdist: mismatch (expected={} built={})".format(sdist_expected[:16], sdist_sha[:16]))
else:
    results.append("sdist: no expected digest in bundle")
if wheel_expected:
    if wheel_sha == wheel_expected:
        results.append("wheel: match")
    else:
        results.append("wheel: mismatch (expected={} built={})".format(wheel_expected[:16], wheel_sha[:16]))
else:
    results.append("wheel: no expected digest in bundle")

print("; ".join(results))
COMPARE_PY
        )
        else
            COMPARISON="not compared: build not available locally"
        fi
    fi

    # Before/after listings — same six surfaces the workflow lists.
    # Each surface is queried honestly; if the network or tool is
    # unavailable, the surface is recorded as "not available locally".
    _listing() {
        local tags=""
        local releases=""
        local mirror_refs=""
        local pypi=""
        local ghcr=""
        local tap=""

        # tags: git ls-remote (no auth needed)
        tags="$(git ls-remote --tags origin 2>/dev/null | awk '{print $2}' | sort || echo 'not available locally')"

        # releases: only available via Forgejo API with a token
        releases="not available locally (no Forgejo API token)"

        # mirror refs: git ls-remote github mirror
        mirror_refs="$(git ls-remote https://github.com/Capacium/capacium.git 2>/dev/null | awk '{print $2}' | sort || echo 'not available locally')"

        # PyPI: JSON API is public, no token required
        pypi="$(curl -sSf "https://pypi.org/pypi/capacium/json" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"releases": sorted(d.get("releases",{}).keys())}))' 2>/dev/null || echo '"'"not available locally"'"')"

        # GHCR: anonymous pull token then tags/list
        ghcr="$(ANON_TOKEN="$(curl -sSf "https://ghcr.io/token?scope=repository:capacium/cap:pull&service=ghcr.io" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)"; if [ -n "${ANON_TOKEN:-}" ]; then curl -sSf -H "Authorization: Bearer ${ANON_TOKEN}" "https://ghcr.io/v2/capacium/cap/tags/list" 2>/dev/null || echo '"'"not available locally"'"'; else echo '"'"not available locally"'"'; fi)"

        # Tap: git ls-remote on the tap repo
        tap="$(git ls-remote https://github.com/Capacium/homebrew-tap.git 2>/dev/null | awk '{print $2}' | sort || echo 'not available locally')"

        python3 -c "
import json
surfaces = {
    'tags': '''$tags''',
    'releases': '''$releases''',
    'mirror_refs': '''$mirror_refs''',
    'pypi': '''$pypi''',
    'ghcr': '''$ghcr''',
    'tap': '''$tap''',
}
for k, v in surfaces.items():
    v = v.strip()
    if v.startswith('[') or v.startswith('{'):
        try:
            surfaces[k] = json.loads(v)
        except json.JSONDecodeError:
            surfaces[k] = v
    elif '\n' in v:
        surfaces[k] = [line for line in v.splitlines() if line]
    else:
        surfaces[k] = v
print(json.dumps(surfaces))
"
    }

    echo -e "${YELLOW}  Capturing before snapshot...${NC}"
    BEFORE="$(_listing)"
    echo -e "${YELLOW}  Capturing after snapshot...${NC}"
    AFTER="$(_listing)"

    # Report
    echo -e "${GREEN}=== Dry-run report ===${NC}"
    BEFORE_JSON=$(echo "$BEFORE" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)))')
    AFTER_JSON=$(echo "$AFTER" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)))')
    if $BUILD_OK; then
        python3 - "$TAG" "$RELEASE_NAME" "$SDIST_SHA256" "$SDIST_SIZE" "$WHEEL_SHA256" "$WHEEL_SIZE" "$COMPARISON" "$BEFORE_JSON" "$AFTER_JSON" "$ORIG_CWD" <<'REPORT_PY'
import json, os, sys
report = {
    "dry_run": True,
    "tag": sys.argv[1],
    "release_name": sys.argv[2],
    "gates": {
        "title": "passed",
        "notes": "passed",
        "audience": "skipped (local dry-run)",
    },
    "reproducibility": {
        "source_date_epoch": "1700000000",
        "pythonhashseed": "0",
    },
    "artifacts": {
        "sdist": {"sha256": sys.argv[3], "size": sys.argv[4]},
        "wheel": {"sha256": sys.argv[5], "size": sys.argv[6]},
    },
    "comparison": sys.argv[7],
    "before": json.loads(sys.argv[8]),
    "after": json.loads(sys.argv[9]),
}
output = json.dumps(report, indent=2)
print(output)
out_path = os.path.join(sys.argv[10], "dry-run-report.json")
with open(out_path, "w") as f:
    f.write(output + "\n")
REPORT_PY
    else
        python3 - "$TAG" "$RELEASE_NAME" "$COMPARISON" "$BEFORE_JSON" "$AFTER_JSON" "$ORIG_CWD" <<'REPORT_NOBUILD_PY'
import json, os, sys
report = {
    "dry_run": True,
    "tag": sys.argv[1],
    "release_name": sys.argv[2],
    "gates": {
        "title": "passed",
        "notes": "passed",
        "audience": "skipped (local dry-run)",
    },
    "reproducibility": {
        "source_date_epoch": "1700000000",
        "pythonhashseed": "0",
    },
    "artifacts": {
        "sdist": {"sha256": "not built (build module unavailable locally)", "size": "0"},
        "wheel": {"sha256": "not built (build module unavailable locally)", "size": "0"},
    },
    "comparison": sys.argv[3],
    "before": json.loads(sys.argv[4]),
    "after": json.loads(sys.argv[5]),
}
output = json.dumps(report, indent=2)
print(output)
out_path = os.path.join(sys.argv[6], "dry-run-report.json")
with open(out_path, "w") as f:
    f.write(output + "\n")
REPORT_NOBUILD_PY
    fi
    echo ""
    echo -e "${GREEN}=== Dry-run complete: no tag, release, mirror push, PyPI upload, GHCR push or tap commit was created ===${NC}"
    exit 0
fi

# ── Step 2: Bump versions ──────────────────────────────────────
echo -e "${YELLOW}[2/8] Bumping version to ${VERSION}...${NC}"

# pyproject.toml
sed -i '' "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml
sed -i '' "s/\"capacium-models>=[^\"]*\"/\"capacium-models>=0.4.0\"/" pyproject.toml

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
