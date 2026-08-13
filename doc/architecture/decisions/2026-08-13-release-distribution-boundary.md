# Release/Verify Split — Forgejo Gates and Tags, GitHub Distributes

- **Status:** Accepted
- **Date:** 2026-08-13
- **Author:** Capacium Core Team
- **CIP:** CAP-CI-001 / CAP-CI-002 / CAP-CI-003

## Context

Three CI tickets share one unresolved root: the division of labour between
Forgejo (canonical) and GitHub (read-only mirror) during a release is never
pinned down. Forgejo runs `validate-release-tag.yml`; the mirror publishes
the ref to GitHub; GitHub runs the distribution workflows (`publish`,
`release`, `binaries`, `docker`, `bump-tap`). Nobody defined who waits on
whom.

The concrete symptoms:

1. **CAP-CI-001** — `validate-release-tag.yml` (`on: push: tags: ["v*.*.*"]`)
   and `mirror.yml` (`on: push: tags: ["v*"]`) fire on the *same* event and
   run **in parallel**. The mirror does not wait for the gate, so a tag whose
   `pyproject.toml` version does not match still reaches GitHub seconds later,
   where the distribution workflows kick off against the wrong commit. `v0.17.0`
   did exactly this (tag → `284d31d`, `pyproject` still `0.16.0`), producing a
   PyPI `400 File already exists`, a failed Release, and a Homebrew Tap bump
   that faithfully shipped a 0.16.0-identifying build.

2. **CAP-CI-002** — three image names disagree. `docker.yml` pushes
   `ghcr.io/capacium/capacium/cap:<tag>` (`IMAGE_NAME = github.repository`,
   with `/cap` appended), the README documents `ghcr.io/capacium/cap:<version>`
   (two segments, no `v` on the tag), and `release.yml`'s `publish-docker`
   job pushes `ghcr.io/capacium/capacium/cap` with a `type=semver` tag that
   drops the `v`. The validation gate compares the README string against
   itself, never against what is actually pushed.

3. **CAP-CI-003** — `release.yml` duplicates four steps that also live as
   standalone workflows (`binaries.yml`, `docker.yml`, `bump-tap.yml`,
   `publish.yml`), and its `update-winget` job is the *only* owner of winget
   yet is `skipped` on every run because it hangs off the full build+test
   matrix, which is permanently red on Windows.

None of these is decidable by moving code around. Each ACA either adopts
"mirror waits for validation" or "mirror self-validates"; "short image name"
or "long image name"; "`release.yml` as single entry point" or "`release.yml`
sheds its duplicates". Those are architecture decisions, which is why this ADR
comes first.

## Decision

### 1. Forgejo owns gate + tag; GitHub owns distribution.

- **Forgejo** (canonical) is the only place a `v*.*.*` tag is *validated* and
  the only place the mirror is *allowed to proceed*. The tag-validation check
  (`validate-release-tag`) is the **single gate** a release ref must pass
  before it is mirrored.
- **GitHub** (mirror) is the **single distribution surface**. Every
  distribution step (PyPI, ghcr.io, Homebrew tap, GH Release, standalone
  binaries, winget) runs only on the GitHub mirror, guarded by
  `github.server_url == 'https://github.com'`. No distribution step may
  manufacture a tag, create a release, or decide which commit a tag points at.

### 2. The mirror runs *after* the gate, in the same workflow.

Forgejo Actions has no repo-crossing `needs:`. The two options are (a) fold
validation and mirror into one workflow with a `needs:` edge, or (b) have the
mirror re-check the same conditions itself. **We choose (a): one workflow,
`validate-release-tag.yml`, with a `mirror` job that `needs:` the `validate`
job.** This keeps the check authored once (no drift between two copies of the
same condition) and makes "the gate is green before the ref moves" structural
rather than coincidental.

`mirror.yml` stays as the branch/workflow-dispatch mirror (it mirrors every
push, including feature branches and manually requested refs). It stops
triggering on `v*` tags; **tag mirroring is owned by the `mirror` job inside
`validate-release-tag.yml` only.**

### 3. The image name is `ghcr.io/capacium/cap`, tags without a leading `v`.

- **Name:** `ghcr.io/capacium/cap` — two segments (`repository_owner` +
  `cap`). This is the name the README already documents and the name users
  already type. A rename now breaks every `docker pull` in the field;
  keeping the short name avoids that break.
- **Tag spelling:** the numeric version, **without** the leading `v`
  (`0.17.1`, not `v0.17.1`), matching the README today and the
  `docker/metadata-action` `type=semver,pattern={{version}}` default.
- `docker.yml` sets `IMAGE_NAME: ${{ github.repository_owner }}` and the
  metadata image to `${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}/cap`, so the
  three segments collapse to two and the pushed name equals the documented
  name.
- The obsolete `ghcr.io/capacium/capacium/cap` namespace and any `v`-prefixed
  tags are **not** mirrored or repaired; the change is recorded in the release
  notes for the version that first ships under the short name.

### 4. `docker.yml` is the single owner of the ghcr image.

`release.yml`'s `publish-docker` job is removed. `docker.yml` already builds
and pushes on its own guard on `v*` tags; it is now the only place the image
is produced, and the only place the image name/tag scheme is defined. This
kills the CAP-CI-002 third-name source (the semver tag that dropped the `v`)
and the CAP-CI-003 docker duplicate in one move.

### 5. Distribution steps have exactly one owning workflow.

| Step | Owner workflow | Removed from `release.yml` |
|------|----------------|-----------------------------|
| PyPI | `publish.yml` | (already absent, 2026-06-12) |
| Standalone binaries + deb/rpm | `binaries.yml` | `build-binaries` |
| ghcr image | `docker.yml` | `publish-docker` |
| Homebrew tap | `bump-tap.yml` | `update-homebrew` |
| winget | `release.yml` (runs last, no duplicate) | — |
| GH Release object | `release.yml` (single `create-release`) | — |

`release.yml` shrinks to the one thing it owns that nothing else does:
`build` (the 3×3 test matrix, used to **gate** the GH Release) → `create-release`
(assembles the GH Release from the artifacts produced by `binaries.yml`) →
`update-winget`. Its distribution jobs and their per-job duplication are gone.

### 6. Downstream distribution does not depend on the full test matrix.

- The GH Release (`create-release`) and winget run off `binaries.yml` success,
  **not** off the 3×3 `build` matrix. A Windows test failure must block only
  Windows-owned artefacts (the Windows binary already ships from
  `binaries.yml`), not the Linux/macOS distribution and not the winget/Release
  step.
- The `build` matrix remains, but as a **quality gate** on the ref, not as a
  `needs:` input to the distribution steps. If Linux/macOS tests are green and
  Windows is red, distribution proceeds and the Windows test failure is
  surfaced as a *visible* failing check, not a silently-skipped distribution
  job.

### 7. Validation checks the thing it claims to check.

`validate-release-tag.yml` compares the README against the *documented image
name and version scheme decided here* (`ghcr.io/capacium/cap:<version>`, no
`v`), i.e. the name `docker.yml` actually produces under this ADR — not against
an arbitrary self-consistent string. It verifies **two** things: (a)
`pyproject.toml` version == tag version, and (b) the README's install examples
reference exactly `@v<version>` and `ghcr.io/capacium/cap:<version>`.

## Consequences

- **CAP-CI-001** becomes mechanically true: a ref reaches GitHub only after
  `validate` is green, because the mirror is a `needs:`-gated job in the same
  workflow. Verified by a *provoked* test tag, not by reading the workflow.
- **CAP-CI-002** collapses three names into one. Verified by a real
  `docker pull ghcr.io/capacium/cap:<version>` after the next release.
- **CAP-CI-003** removes four duplicated distribution jobs, gives winget the
  single live owner (`release.yml`'s `update-winget`), and decouples
  distribution from the Windows-red test matrix. Verified by a release where
  `winget` runs rather than `skipped`.
- **Image-name migration surface:** any published `ghcr.io/capacium/capacium/cap`
  images become orphaned; no `latest` is rewritten onto them. The release notes
  for the first short-name release must state the new pull command. The
  README's `docker run` example changes if it still names the long form or a
  `v`-tag.
- **One gate, one mirror path for tags.** `mirror.yml` no longer mirrors `v*`
  tags; the tag mirror lives in `validate-release-tag.yml`'s `mirror` job. A
  maintainer must not re-add a `v*` trigger to `mirror.yml` without re-deciding
  this ADR.
- **No self-approval / no tag / no merge.** This ADR fixes the boundary, not
  the release. Tagging and merging remain operator decisions; nothing in the
  three tickets performs them.
