#!/usr/bin/env bash
# Capacium Release Script — one command to rule them all
# Usage: ./scripts/release.sh <version> [--dry-run]
#
# Flow: bump → verify → commit → push → wait CI → tag → tarball → tap → brew → release
#
# --dry-run: runs the same gates as the Forgejo workflow_dispatch dry_run input:
#   title gate, changelog extraction, audience gate. Before and after listings
#   bracket the gates. The report is written by scripts/dry_run_report.py, the
#   single writer shared with the workflow. No tag, release, mirror push, PyPI
#   upload, GHCR push or tap commit is created.
#
#   Qualified digest comparison is in RELMODEL-007; it is out of scope here.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

VERSION="${1:-}"
shift || true

DRY_RUN=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN="--dry-run"
            ;;
        *)
            ;;
    esac
    shift
done
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TAP_DIR="/opt/homebrew/Library/Taps/capacium/homebrew-tap"
if [ "$DRY_RUN" != "--dry-run" ]; then
    if [ ! -d "$TAP_DIR" ]; then
        echo -e "${YELLOW}  Tap not found at ${TAP_DIR} — cloning...${NC}"
        git clone https://github.com/Capacium/homebrew-tap "$TAP_DIR"
    fi
    TAP_REMOTE=$(git -C "$TAP_DIR" remote get-url origin 2>/dev/null || echo "")
    if echo "$TAP_REMOTE" | grep -q "capacium/homebrew-tap$"; then
        git -C "$TAP_DIR" remote set-url origin https://github.com/Capacium/homebrew-tap
    fi
fi
GITHUB_REPO="Capacium/capacium"

if [ -z "$VERSION" ]; then
    echo -e "${RED}Usage: $0 <version> [--dry-run]${NC}"
    echo "Example: $0 0.10.9"
    exit 1
fi

VERSION="${VERSION#v}"
TAG="v${VERSION}"

echo -e "${GREEN}=== Capacium Release v${VERSION} ===${NC}"

# ── Step 1: Local verification ────────────────────────────────
ORIG_CWD="$PWD"
cd "$REPO_DIR"
if [ "$DRY_RUN" != "--dry-run" ]; then
    echo -e "${YELLOW}[1/8] Running ruff + pytest...${NC}"
    rm -rf build/lib/ dist/ *.egg-info
    ruff check src/ tests/ --fix || { echo -e "${RED}ruff failed${NC}"; exit 1; }
    python3 -m pytest tests/ -q --ignore=tests/test_publish.py --ignore=tests/test_signing.py --ignore=tests/test_integration_phase0.py || { echo -e "${RED}pytest failed${NC}"; exit 1; }
    echo -e "${GREEN}  Tests pass${NC}"
fi

# ── Dry-run: gates bracketed by before/after listings, report via shared writer ──
if [ "$DRY_RUN" = "--dry-run" ]; then
    echo ""

    # ── Listing function ──────────────────────────────────────────
    # Each surface is queried independently. A query that fails (non-2xx,
    # timeout, TLS error, missing token) exits non-zero with a named error
    # and is never stored as a report value.
    _listing() {
        local tags releases mirror_refs pypi ghcr tap

        # tags: git ls-remote (no auth needed)
        tags="$(git ls-remote --tags origin 2>/dev/null | awk '{print $2}' | sort)" || {
            echo "ListingError: git ls-remote --tags origin failed" >&2
            exit 2
        }

        # releases: Forgejo API (needs token)
        if [ -z "${FORGEJO_TOKEN:-}" ]; then
            echo "ListingError: FORGEJO_TOKEN is not set — cannot list releases" >&2
            exit 2
        fi
        releases="$(curl -sSf -H "Authorization: token ${FORGEJO_TOKEN}" \
            "https://code.langevc.com/api/v1/repos/capacium/capacium/releases?per_page=100" | \
            python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps([{"id":r["id"],"tag_name":r["tag_name"],"name":r.get("name",""),"draft":r.get("draft",False),"prerelease":r.get("prerelease",False)} for r in d]))')" || {
            echo "ListingError: Forgejo releases API query failed" >&2
            exit 2
        }

        # mirror refs: git ls-remote GitHub mirror
        mirror_refs="$(git ls-remote https://github.com/Capacium/capacium.git 2>/dev/null | awk '{print $2}' | sort)" || {
            echo "ListingError: git ls-remote GitHub mirror failed" >&2
            exit 2
        }

        # PyPI: JSON API is public, no token required
        pypi="$(curl -sSf "https://pypi.org/pypi/capacium/json" | \
            python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"releases": sorted(d.get("releases",{}).keys())}))')" || {
            echo "ListingError: PyPI API query failed" >&2
            exit 2
        }

        # GHCR: anonymous pull token then tags/list
        local ghcr_token
        ghcr_token="$(curl -sSf "https://ghcr.io/token?scope=repository:capacium/cap:pull&service=ghcr.io" | \
            python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))')" || {
            echo "ListingError: GHCR anonymous token request failed" >&2
            exit 2
        }
        ghcr="$(curl -sSf -H "Authorization: Bearer ${ghcr_token}" \
            "https://ghcr.io/v2/capacium/cap/tags/list" | \
            python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)))')" || {
            echo "ListingError: GHCR tags/list query failed" >&2
            exit 2
        }

        # Tap: git ls-remote on the tap repo
        tap="$(git ls-remote https://github.com/Capacium/homebrew-tap.git 2>/dev/null | awk '{print $2}' | sort)" || {
            echo "ListingError: git ls-remote Homebrew tap failed" >&2
            exit 2
        }

        python3 -c "
import json
surfaces = {
    'tags': [line for line in '''$tags'''.splitlines() if line],
    'releases': json.loads('''$releases'''),
    'mirror_refs': [line for line in '''$mirror_refs'''.splitlines() if line],
    'pypi': json.loads('''$pypi'''),
    'ghcr': json.loads('''$ghcr'''),
    'tap': [line for line in '''$tap'''.splitlines() if line],
}
print(json.dumps(surfaces))
"
    }

    echo -e "${GREEN}=== Dry-run gates for v${VERSION} ===${NC}"
    echo ""

    # ── Before snapshot: all six publication surfaces ──
    echo -e "${YELLOW}  Capturing before snapshot...${NC}"
    BEFORE="$(_listing)"

    # Gate 1: Title gate
    echo -e "${YELLOW}[dry-run gate 1/3] Title gate${NC}"
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
    TITLE_GATE="passed"
    echo -e "${GREEN}  Title gate: ${TITLE_GATE}${NC}"

    # Gate 2: Changelog extraction
    echo -e "${YELLOW}[dry-run gate 2/3] Changelog extraction${NC}"
    NOTES_GATE="passed"
    NOTES="$(python3 scripts/extract_changelog_notes.py "$TAG" 2>&1)" || {
        echo -e "${RED}  Changelog extraction failed: ${NOTES}${NC}"
        exit 2
    }
    echo -e "${GREEN}  Changelog extraction passed (${#NOTES} chars)${NC}"

    # Gate 3: Audience gate — measured, never a literal 'passed' when it did
    # not run. When FORGEJO_TOKEN or GITHUB_TOKEN is set the gate executes;
    # otherwise it is recorded as 'not run' and the dry-run exits non-zero.
    echo -e "${YELLOW}[dry-run gate 3/3] Audience gate${NC}"
    AUDIENCE_GATE="not run"
    if [ -n "${FORGEJO_TOKEN:-}" ] || [ -n "${GITHUB_TOKEN:-}" ]; then
        AUDIENCE_GATE_SCRIPT="$(mktemp)"
        PREFIXES_FILE="$(mktemp)"
        NOTES_FILE="$(mktemp)"
        trap 'rm -f "$AUDIENCE_GATE_SCRIPT" "$PREFIXES_FILE" "$NOTES_FILE"' EXIT
        if curl -fsSL \
            "https://raw.githubusercontent.com/LangeVC/ops-engine/v3.4.2/scripts/release_notes_audience_gate.py" \
            -o "$AUDIENCE_GATE_SCRIPT" 2>/dev/null; then
            python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" \
                "$AUDIENCE_GATE_SCRIPT" || true
            printf '%s\n' "$NOTES" > "$NOTES_FILE"
            python3 scripts/extract_tracker_prefixes.py > "$PREFIXES_FILE" 2>/dev/null || true
            if python3 "$AUDIENCE_GATE_SCRIPT" \
                --ticket-prefixes "$PREFIXES_FILE" \
                "$NOTES_FILE" 2>/dev/null; then
                AUDIENCE_GATE="passed"
            else
                AUDIENCE_GATE="failed"
            fi
        fi
    fi
    echo -e "${GREEN}  Audience gate: ${AUDIENCE_GATE}${NC}"

    # ── After snapshot: same six surfaces ──
    echo -e "${YELLOW}  Capturing after snapshot...${NC}"
    AFTER="$(_listing)"

    # Write report via the single shared writer
    echo -e "${GREEN}=== Dry-run report ===${NC}"
    python3 scripts/dry_run_report.py \
        --tag "$TAG" \
        --release-name "$RELEASE_NAME" \
        --title-gate "$TITLE_GATE" \
        --notes-gate "$NOTES_GATE" \
        --audience-gate "$AUDIENCE_GATE" \
        --before "$BEFORE" \
        --after "$AFTER" \
        --output "$ORIG_CWD/dry-run-report.json"

    echo ""
    echo -e "${GREEN}=== Dry-run complete: no tag, release, mirror push, PyPI upload, GHCR push or tap commit was created ===${NC}"

    # Exit non-zero when any gate is 'not run' or 'failed'
    if [ "$AUDIENCE_GATE" = "not run" ] || [ "$AUDIENCE_GATE" = "failed" ]; then
        exit 2
    fi
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
