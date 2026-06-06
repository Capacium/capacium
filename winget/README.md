# Winget Manifest

Submit to microsoft/winget-pkgs:

1. Fork https://github.com/microsoft/winget-pkgs
2. Copy `winget/manifests/c/Capacium/Capacium/0.14.0/` to your fork's `manifests/c/Capacium/Capacium/0.14.0/`
3. Replace `PLACEHOLDER` SHA256 with actual Windows binary SHA256 (from GitHub Release)
4. Create PR to microsoft/winget-pkgs
5. Once merged: `winget install Capacium.Capacium`
