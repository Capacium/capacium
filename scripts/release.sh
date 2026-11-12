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
#   --qualified-digests <path>: required for --dry-run; qualified-digests v1 bundle
#   JSON with sdist_sha256, wheel_sha256, source_tree and qualification_run.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

VERSION="${1:-}"
shift || true

DRY_RUN=""
QUALIFIED_DIGESTS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN="--dry-run"
            ;;
        --qualified-digests)
            QUALIFIED_DIGESTS="$2"
            shift
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
    # All query results are passed to the assembler as data (temp files),
    # never interpolated into Python source code.
    _listing() {
        local tmpdir
        tmpdir="$(mktemp -d)"
        trap 'rm -rf "$tmpdir"' RETURN

        # tags: git ls-remote (no auth needed), 30s timeout
        timeout 30 git ls-remote --tags origin 2>/dev/null | awk '{print $2}' | sort > "$tmpdir/tags" || {
            echo "ListingError: git ls-remote --tags origin failed (timeout or network)" >&2
            exit 2
        }

        # releases: Forgejo API (needs token), 30s timeout
        if [ -z "${FORGEJO_TOKEN:-}" ]; then
            echo "ListingError: FORGEJO_TOKEN is not set — cannot list releases" >&2
            exit 2
        fi
        curl -sSf --max-time 30 --connect-timeout 10 \
            -H "Authorization: token ${FORGEJO_TOKEN}" \
            "https://code.langevc.com/api/v1/repos/capacium/capacium/releases?per_page=100" \
            > "$tmpdir/releases_raw" || {
            echo "ListingError: Forgejo releases API query failed" >&2
            exit 2
        }
        python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps([{"id":r["id"],"tag_name":r["tag_name"],"name":r.get("name",""),"draft":r.get("draft",False),"prerelease":r.get("prerelease",False)} for r in d]))' < "$tmpdir/releases_raw" > "$tmpdir/releases" || {
            echo "ListingError: Forgejo releases API query failed" >&2
            exit 2
        }

        # mirror refs: git ls-remote GitHub mirror, 30s timeout
        timeout 30 git ls-remote https://github.com/Capacium/capacium.git 2>/dev/null | awk '{print $2}' | sort > "$tmpdir/mirror_refs" || {
            echo "ListingError: git ls-remote GitHub mirror failed (timeout or network)" >&2
            exit 2
        }

        # PyPI: JSON API is public, no token required, 30s timeout
        curl -sSf --max-time 30 --connect-timeout 10 \
            "https://pypi.org/pypi/capacium/json" \
            > "$tmpdir/pypi_raw" || {
            echo "ListingError: PyPI API query failed" >&2
            exit 2
        }
        python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"releases": sorted(d.get("releases",{}).keys())}))' < "$tmpdir/pypi_raw" > "$tmpdir/pypi" || {
            echo "ListingError: PyPI API query failed" >&2
            exit 2
        }

        # GHCR: anonymous pull token then tags/list, 30s timeout each
        curl -sSf --max-time 30 --connect-timeout 10 \
            "https://ghcr.io/token?scope=repository:capacium/cap:pull&service=ghcr.io" \
            > "$tmpdir/ghcr_token_raw" || {
            echo "ListingError: GHCR anonymous token request failed" >&2
            exit 2
        }
        local ghcr_token
        ghcr_token="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' < "$tmpdir/ghcr_token_raw")"
        if [ -z "$ghcr_token" ]; then
            echo "ListingError: GHCR anonymous token request returned empty token" >&2
            exit 2
        fi
        curl -sSf --max-time 30 --connect-timeout 10 \
            -H "Authorization: Bearer ${ghcr_token}" \
            "https://ghcr.io/v2/capacium/cap/tags/list" \
            > "$tmpdir/ghcr_raw" || {
            echo "ListingError: GHCR tags/list query failed" >&2
            exit 2
        }
        python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)))' < "$tmpdir/ghcr_raw" > "$tmpdir/ghcr" || {
            echo "ListingError: GHCR tags/list query failed" >&2
            exit 2
        }

        # Tap: git ls-remote on the tap repo, 30s timeout
        timeout 30 git ls-remote https://github.com/Capacium/homebrew-tap.git 2>/dev/null | awk '{print $2}' | sort > "$tmpdir/tap" || {
            echo "ListingError: git ls-remote Homebrew tap failed (timeout or network)" >&2
            exit 2
        }

        # Assemble the listing JSON. All data is passed as file paths
        # (argv), never interpolated into Python source code.
        python3 "$REPO_DIR/scripts/_listing_assembler.py" "$tmpdir"
    }

    echo -e "${GREEN}=== Dry-run gates for v${VERSION} ===${NC}"
    echo ""

    # ── Before snapshot: all six publication surfaces ──
    echo -e "${YELLOW}  Capturing before snapshot...${NC}"
    BEFORE="$(_listing)"

    # Gate 1: Title gate — measured, never a literal
    echo -e "${YELLOW}[dry-run gate 1/3] Title gate${NC}"
    RELEASE_NAME="Capacium ${TAG}"
    TITLE_GATE="$(python3 - "${RELEASE_NAME}" <<'TITLE_GATE_PY'
import re, sys
NAME_RE = re.compile(r"^Capacium v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$")
name = sys.argv[1]
if not NAME_RE.match(name):
    sys.stderr.write("ReleaseTitleError: release name %r does not match required convention\n" % name)
    sys.exit(2)
sys.stdout.write("passed\n")
TITLE_GATE_PY
)"
    echo -e "${GREEN}  Title gate: ${TITLE_GATE}${NC}"

    # Gate 2: Changelog extraction — measured, never a literal
    echo -e "${YELLOW}[dry-run gate 2/3] Changelog extraction${NC}"
    set +e
    NOTES="$(python3 scripts/extract_changelog_notes.py "$TAG" 2>&1)"
    NOTES_EXIT=$?
    set -e
    if [ $NOTES_EXIT -ne 0 ]; then
        echo -e "${RED}  Changelog extraction failed: ${NOTES}${NC}"
        exit 2
    fi
    NOTES_GATE="passed"
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
                "$AUDIENCE_GATE_SCRIPT" || {
                echo "AudienceGateError: fetched audience gate script is not valid Python" >&2
                exit 2
            }
            printf '%s\n' "$NOTES" > "$NOTES_FILE"
            python3 scripts/extract_tracker_prefixes.py > "$PREFIXES_FILE" || {
                echo "AudienceGateError: failed to extract ticket prefixes from .ops.yaml" >&2
                exit 2
            }
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

    # ── Qualified-digests v1: build and compare ────────────────
    # The bundle is REQUIRED for --dry-run. An empty/unset bundle is a
    # named error; it never produces a green exit with no comparison.
    SDIST_SHA256=""
    WHEEL_SHA256=""
    DIGEST_COMPARISON=""
    COMPARE_ERROR_NAME=""
    COMPARE_ERROR_TEXT=""
    if [ -z "${QUALIFIED_DIGESTS}" ]; then
        echo "QualifiedDigestBundleError: --qualified-digests bundle is required for --dry-run" >&2
        exit 2
    fi
    echo -e "${YELLOW}[dry-run digests] Building sdist and wheel with SOURCE_DATE_EPOCH=1700000000 PYTHONHASHSEED=0${NC}"
    SOURCE_TREE="$(git rev-parse HEAD)"
    # Build from a git archive of the source tree so the built content
    # matches the qualified source, not an uncommitted working tree.
    BUILD_DIR="$(mktemp -d)"
    trap 'rm -rf "$BUILD_DIR"' EXIT
    ARCHIVE_DIR="$BUILD_DIR/src"
    mkdir -p "$ARCHIVE_DIR"
    git archive "$SOURCE_TREE" | tar -x -C "$ARCHIVE_DIR" || {
        echo "BuildError: git archive of $SOURCE_TREE failed — build unavailable or broken" >&2
        exit 2
    }
    SOURCE_DATE_EPOCH=1700000000 PYTHONHASHSEED=0 \
        python3 -m build --sdist --wheel --outdir "$BUILD_DIR" "$ARCHIVE_DIR" > /dev/null 2>&1 || {
        echo "BuildError: python -m build failed — build unavailable or broken" >&2
        exit 2
    }
    SDIST_FILE="$(echo "$BUILD_DIR"/*.tar.gz)"
    WHEEL_FILE="$(echo "$BUILD_DIR"/*.whl)"
    if [ ! -f "$SDIST_FILE" ] || [ ! -f "$WHEEL_FILE" ]; then
        echo "BuildError: build completed but sdist or wheel not found" >&2
        exit 2
    fi
    SDIST_SHA256="$(shasum -a 256 "$SDIST_FILE" | awk '{print $1}')"
    WHEEL_SHA256="$(shasum -a 256 "$WHEEL_FILE" | awk '{print $1}')"
    echo -e "${GREEN}  sdist sha256: ${SDIST_SHA256}${NC}"
    echo -e "${GREEN}  wheel sha256: ${WHEEL_SHA256}${NC}"

    echo -e "${YELLOW}[dry-run digests] Comparing against qualified-digests bundle: ${QUALIFIED_DIGESTS}${NC}"
    # Capture the child stderr separately from stdout so the named
    # error survives into the report and the caller's exit message.
    COMPARE_STDERR="$(mktemp)"
    trap 'rm -rf "$BUILD_DIR" "$COMPARE_STDERR"' EXIT
    set +e
    DIGEST_COMPARISON="$(python3 scripts/qualified_digests.py compare \
        "$QUALIFIED_DIGESTS" \
        --sdist "$SDIST_SHA256" \
        --wheel "$WHEEL_SHA256" \
        --source-tree "$SOURCE_TREE" 2>"$COMPARE_STDERR")"
    COMPARE_EXIT=$?
    set -e
    if [ $COMPARE_EXIT -eq 0 ]; then
        DIGEST_COMPARISON="matched"
        echo -e "${GREEN}  Digest comparison: matched${NC}"
    else
        # Map the child exit to the distinct named error so the
        # operator sees BundleError / SourceTreeError / MismatchError.
        COMPARE_ERROR_TEXT="$(cat "$COMPARE_STDERR")"
        case "$COMPARE_ERROR_TEXT" in
            *QualifiedDigestBundleError*)  COMPARE_ERROR_NAME="QualifiedDigestBundleError" ;;
            *QualifiedDigestSourceTreeError*) COMPARE_ERROR_NAME="QualifiedDigestSourceTreeError" ;;
            *QualifiedDigestMismatchError*) COMPARE_ERROR_NAME="QualifiedDigestMismatchError" ;;
            *) COMPARE_ERROR_NAME="QualifiedDigestMismatchError" ;;
        esac
        DIGEST_COMPARISON="mismatch"
        echo -e "${RED}  Digest comparison: mismatch — ${COMPARE_ERROR_NAME}${NC}"
        echo "${COMPARE_ERROR_TEXT}" >&2
    fi

    # ── After snapshot: same six surfaces ──
    echo -e "${YELLOW}  Capturing after snapshot...${NC}"
    AFTER="$(_listing)"

    # Write report via the single shared writer
    echo -e "${GREEN}=== Dry-run report ===${NC}"
    REPORT_ARGS=(
        --tag "$TAG"
        --release-name "$RELEASE_NAME"
        --title-gate "$TITLE_GATE"
        --notes-gate "$NOTES_GATE"
        --audience-gate "$AUDIENCE_GATE"
        --before "$BEFORE"
        --after "$AFTER"
    )
    if [ -n "$SDIST_SHA256" ]; then
        REPORT_ARGS+=(--sdist-sha256 "$SDIST_SHA256")
    fi
    if [ -n "$WHEEL_SHA256" ]; then
        REPORT_ARGS+=(--wheel-sha256 "$WHEEL_SHA256")
    fi
    if [ -n "$DIGEST_COMPARISON" ]; then
        REPORT_ARGS+=(--digest-comparison "$DIGEST_COMPARISON")
    fi
    # Record the build provenance so the report can evidence that the
    # digests were built under the qualified inputs.
    REPORT_ARGS+=(--sde "1700000000")
    REPORT_ARGS+=(--pythonhashseed "0")
    python3 scripts/dry_run_report.py \
        "${REPORT_ARGS[@]}" \
        --output "$ORIG_CWD/dry-run-report.json"

    echo ""
    echo -e "${GREEN}=== Dry-run complete: no tag, release, mirror push, PyPI upload, GHCR push or tap commit was created ===${NC}"

    # Exit non-zero when any gate is 'not run' or 'failed', or digest comparison
    # is not 'matched'. The bundle is required — an empty QUALIFIED_DIGESTS is
    # already refused above, so we always have a comparison result here.
    if [ "$AUDIENCE_GATE" = "not run" ] || [ "$AUDIENCE_GATE" = "failed" ]; then
        exit 2
    fi
    if [ "$DIGEST_COMPARISON" != "matched" ]; then
        echo "${COMPARE_ERROR_NAME}: ${COMPARE_ERROR_TEXT}" >&2
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
