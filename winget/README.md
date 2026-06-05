# Winget Manifest — Submission Guide

This directory contains the winget manifest for **Capacium** (`Capacium.Capacium`).

## Structure

```
winget/
└── manifests/
    └── c/
        └── Capacium/
            └── Capacium/
                └── 0.10.10/
                    └── Capacium.Capacium.yaml
```

Per winget's [repository layout convention](https://github.com/microsoft/winget-pkgs/tree/master/manifests), manifests are organized as:

```
manifests/<first-letter>/<publisher>/<package>/<version>/<publisher>.<package>.yaml
```

## Submitting to microsoft/winget-pkgs

### 1. Fork the winget-pkgs repo

```bash
gh repo fork microsoft/winget-pkgs --clone
cd winget-pkgs
```

### 2. Copy the manifest

```bash
cp -r /path/to/capacium/winget/manifests/c/Capacium \
  manifests/c/Capacium
```

### 3. Validate locally

```bash
winget validate manifests/c/Capacium/Capacium/0.10.10/Capacium.Capacium.yaml
```

### 4. Submit the PR

```bash
git checkout -b capacium-0.10.10
git add manifests/c/Capacium/
git commit -m "Add Capacium.Capacium 0.10.10"
git push origin capacium-0.10.10
gh pr create --repo microsoft/winget-pkgs \
  --title "New package: Capacium.Capacium 0.10.10" \
  --body "Capability Packaging System for AI agent capabilities"
```

### 5. What happens next

- A bot validates the manifest structure and SHA256
- Moderators review and merge
- Once merged, users can run: `winget install Capacium.Capacium`

## Updating the manifest for new releases

When releasing a new version of Capacium:

1. Create a new version directory: `winget/manifests/c/Capacium/Capacium/<new-version>/`
2. Copy and update the manifest with:
   - New `PackageVersion`
   - New `InstallerUrl` pointing to the correct tag
   - New `InstallerSha256` computed from the tarball:
     ```bash
     curl -sL "https://github.com/Capacium/capacium/archive/refs/tags/vX.Y.Z.tar.gz" \
       -o /tmp/cap.tar.gz && shasum -a 256 /tmp/cap.tar.gz
     ```
3. Submit to winget-pkgs following the steps above.

## Notes

- Capacium is a Python CLI distributed via pipx. The winget manifest points to the GitHub Release tarball with a `NestedInstallerType: portable` entry.
- For pipx installation, users should run: `pipx install capacium`
