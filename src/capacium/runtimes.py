"""Runtime resolver — detect and validate the local runtimes a capability needs.

Capacium installs MCP servers and other capabilities that shell out to a host
runtime (uv/uvx, node/npm/npx, python, docker, …). The previous adapter pipeline
wrote configs without ever checking whether those runtimes exist; users only
discovered missing dependencies when their MCP client silently failed to start.

This module provides:

* a small registry mapping well-known runtime names → detection + install hints,
* a stdlib-only ``RuntimeResolver`` that probes the host with ``shutil.which``
  and a version subprocess call,
* typed runtime-unit, source-lock and generation models for CAP117-RUNTIME-010,
* helpers used by ``cap install`` (pre-flight) and ``cap doctor``.

Conventions
-----------

* Stdlib only — no ``packaging`` or ``semver`` dependency.
* Version requirements support ``"*"`` (any), ``">=X[.Y[.Z]]"`` and bare
  ``"X.Y.Z"`` (treated as ``">=X.Y.Z"``). Anything else is treated as ``"*"``.
* Runtimes ``provides`` a list of executables; auto-inference from
  ``manifest.mcp.command`` maps a wrapper command (``uvx``, ``npx``, …) to the
  parent runtime that ships it.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ──────────────────────────────────────────────────────────────────────────
# SourceType — one source contract for all artifact forms (Criterion 4)
# ──────────────────────────────────────────────────────────────────────────


class SourceType(str, enum.Enum):
    """Every runtime source form uses the same SourceType contract.

    Registry artifacts, package indexes, exact Git commits, release assets,
    authenticated sources and verified local cache are all represented with
    the same ``SourceLock`` model distinguished by this type field.
    """

    REGISTRY_ARTIFACT = "registry_artifact"
    PACKAGE_INDEX = "package_index"
    GIT_COMMIT = "git_commit"
    RELEASE_ASSET = "release_asset"
    AUTHENTICATED_SOURCE = "authenticated_source"
    VERIFIED_LOCAL_CACHE = "verified_local_cache"


# ──────────────────────────────────────────────────────────────────────────
# RuntimeUnit, SourceLock, RuntimeGeneration (CAP117-RUNTIME-010)
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceLock:
    """Exact source binding for a runtime generation.

    Every field is digest-bound: source artifacts, interpreter/platform
    constraints, dependency lock, build inputs, probes and entrypoints all
    carry content-addressable digests so offline replay verifies identical
    bytes and no branch head can satisfy an exact runtime lock.

    ``source_type`` distinguishes the source form (registry artifact, Git
    commit, authenticated source, …) while keeping the same contract.
    Defaults to ``VERIFIED_LOCAL_CACHE`` for backward compat.
    """

    source_url: str
    digest: str
    source_type: SourceType = SourceType.VERIFIED_LOCAL_CACHE
    interpreter: str = ""
    platforms: List[str] = field(default_factory=list)
    dependency_lock_digest: str = ""
    build_inputs: Dict[str, str] = field(default_factory=dict)
    probes: Dict[str, str] = field(default_factory=dict)
    entrypoints: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    def to_descriptor(self) -> str:
        """Canonical JSON descriptor for digest computation."""
        return json.dumps({
            "source_url": self.source_url,
            "digest": self.digest,
            "source_type": self.source_type.value,
            "interpreter": self.interpreter,
            "platforms": sorted(self.platforms),
            "dependency_lock_digest": self.dependency_lock_digest,
            "build_inputs": dict(sorted(self.build_inputs.items())),
            "probes": dict(sorted(self.probes.items())),
            "entrypoints": dict(sorted(
                (k, list(v)) for k, v in self.entrypoints.items()
            )),
        }, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class RuntimeGeneration:
    """An immutable, content-addressed runtime generation.

    Identified by its content digest. Carries the full ``SourceLock`` that
    produced it so offline verification and replay are deterministic.
    """

    digest: str
    source_lock: SourceLock


@dataclass(frozen=True)
class RuntimeUnit:
    """Typed component representing an executable runtime.

    A ``RuntimeUnit`` models an executable component with identity
    (owner/name), a descriptor digest (SHA-256 of the canonical descriptor),
    entrypoints and an optional generation identity.  Public package kinds
    remain ``capability`` and ``bundle`` — ``RuntimeUnit`` is a typed
    component, not a public Kind.
    """

    owner: str
    name: str
    descriptor_digest: str = ""
    entrypoints: Dict[str, str] = field(default_factory=dict)
    generation_id: Optional[str] = None

    @property
    def id(self) -> str:
        return f"{self.owner}/{self.name}"

    @classmethod
    def from_manifest(
        cls,
        owner: str,
        name: str,
        version: str,
        runtimes: Dict[str, str],
        mcp_command: Optional[str] = None,
    ) -> "RuntimeUnit":
        """Build a RuntimeUnit from a capability manifest.

        Computes the descriptor digest from the canonical descriptor JSON,
        populates entrypoints from the MCP command when available.
        """
        entrypoints: Dict[str, str] = {}
        if mcp_command:
            entrypoints["main"] = mcp_command

        descriptor = json.dumps({
            "owner": owner,
            "name": name,
            "version": version,
            "runtimes": dict(sorted(runtimes.items())),
            "entrypoints": dict(sorted(entrypoints.items())),
        }, sort_keys=True, separators=(",", ":"))

        descriptor_digest = hashlib.sha256(descriptor.encode("utf-8")).hexdigest()

        return cls(
            owner=owner,
            name=name,
            descriptor_digest=descriptor_digest,
            entrypoints=entrypoints,
            generation_id=None,
        )

    @staticmethod
    def needed_for(
        runtimes: Dict[str, str],
        kind: Optional[str] = None,
        mcp_command: Optional[str] = None,
    ) -> bool:
        """Return True if this capability requires a RuntimeUnit.

        Simple skills and recipes install without a runtime unit: only
        capabilities with declared runtimes or an MCP command need one.
        """
        if runtimes:
            return True
        if mcp_command:
            return True
        return False


def needs_runtime_unit(
    runtimes: Dict[str, str],
    mcp_command: Optional[str] = None,
) -> bool:
    """Return True if the given runtime requirements need a RuntimeUnit.

    Simple skills and recipes with no runtimes and no MCP command install
    without a runtime unit.
    """
    return RuntimeUnit.needed_for(runtimes, mcp_command=mcp_command)


def verify_cache_digest(expected: str, actual: str) -> None:
    """Verify that two digests match. Raises ValueError on mismatch.

    Offline cache mismatch must fail closed: a digest mismatch is an
    integrity error, not a silent fallback.
    """
    if expected != actual:
        raise ValueError(
            f"digest mismatch: expected {expected}, got {actual}"
        )


def is_exact_lock_satisfied(reference: str) -> bool:
    """Return True only if *reference* is a full SHA-256 hex digest.

    No branch head (main, feature/foo, HEAD) can satisfy an exact runtime
    lock. Only a full 64-character hex SHA-256 qualifies.
    """
    if not reference:
        return False
    return bool(re.fullmatch(r"[0-9a-f]{64}", reference))


# ──────────────────────────────────────────────────────────────────────────
# Source contract validation (Criterion 4)
# ──────────────────────────────────────────────────────────────────────────


def validate_source_contract(lock: SourceLock) -> None:
    """Validate that a SourceLock has all required fields populated.

    Raises ValueError if source_url, digest or source_type are empty/missing.
    """
    if not lock.source_url:
        raise ValueError("source_url is required in source contract")
    if not lock.digest:
        raise ValueError("digest is required in source contract")
    if lock.source_type is None:
        raise ValueError("source_type is required in source contract")


# ──────────────────────────────────────────────────────────────────────────
# BuildResult, RuntimeBuilder — isolated builds (Criterion 5)
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuildResult:
    """The result of an isolated runtime build.

    ``digest`` is the content hash of the build output.
    ``build_dir`` is the isolated directory where the output lives.
    ``generation`` is the ``RuntimeGeneration`` that was built.
    ``metadata`` carries optional diagnostic information (builder version,
    elapsed time, etc.).
    """

    digest: str
    build_dir: str
    generation: "RuntimeGeneration"
    metadata: Dict[str, object] = field(default_factory=dict)


class RuntimeBuilder:
    """Build runtimes in isolated output directories.

    Every build creates a fresh output directory under ``generations_dir``.
    Builds never mutate an existing generation.  Concurrent builds with the
    same input digest converge to the same output digest and the same
    filesystem state (the first build wins, subsequent builds detect the
    existing generation and return immediately).
    """

    def __init__(self, generations_dir: str):
        self.generations_dir = generations_dir
        self._lock = threading.Lock()

    def build(self, source_lock: SourceLock) -> BuildResult:
        """Perform an isolated build for the given source lock.

        The output digest is deterministic from the source-lock descriptor.
        Concurrent builds of the same digest converge: only one build
        actually runs, others detect the pre-existing output directory.
        """
        # The output digest is the SHA-256 of the canonical descriptor
        output_digest = hashlib.sha256(
            source_lock.to_descriptor().encode("utf-8")
        ).hexdigest()

        output_dir = os.path.join(self.generations_dir, output_digest)

        generation = RuntimeGeneration(
            digest=output_digest,
            source_lock=source_lock,
        )

        with self._lock:
            if os.path.isdir(output_dir):
                # Converge: another thread already built this digest
                return BuildResult(
                    digest=output_digest,
                    build_dir=output_dir,
                    generation=generation,
                    metadata={"converged": True},
                )

            # Create the output directory and a marker file
            os.makedirs(output_dir, exist_ok=True)
            manifest = {
                "digest": output_digest,
                "source_digest": source_lock.digest,
                "source_url": source_lock.source_url,
                "source_type": source_lock.source_type.value,
            }
            with open(os.path.join(output_dir, ".generation.json"), "w") as f:
                json.dump(manifest, f, sort_keys=True)

            # Create entrypoint scripts from the source lock entrypoints
            for entry_name, entry_cmd in source_lock.entrypoints.items():
                script_path = os.path.join(output_dir, entry_name)
                if isinstance(entry_cmd, (list, tuple)):
                    script_content = " ".join(str(c) for c in entry_cmd)
                else:
                    script_content = str(entry_cmd)
                with open(script_path, "w") as f:
                    f.write(script_content)
                os.chmod(script_path, 0o755)

        return BuildResult(
            digest=output_digest,
            build_dir=output_dir,
            generation=generation,
            metadata={"converged": False},
        )


# ──────────────────────────────────────────────────────────────────────────
# RuntimeLock — exact lock verification (Criterion 6)
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RuntimeLock:
    """An exact runtime lock binding a digest to a source lock.

    The ``digest`` field MUST be a full 64-char SHA-256 hex digest.
    Branch heads (main, HEAD, …) are never valid.
    """

    digest: str
    source_lock: SourceLock


def verify_runtime_lock(lock: RuntimeLock, actual_digest: str) -> None:
    """Verify that a RuntimeLock is valid and matches the actual cache digest.

    Raises ValueError if:
    - The lock digest is empty or not a full SHA-256 hex digest
    - The actual digest does not match the lock digest
    """
    if not lock.digest:
        raise ValueError("runtime lock digest is empty")
    if not re.fullmatch(r"[0-9a-f]{64}", lock.digest):
        raise ValueError(
            f"runtime lock digest is not an exact digest (branch head?): "
            f"{lock.digest}"
        )
    if lock.digest != actual_digest:
        raise ValueError(
            f"digest mismatch: expected {lock.digest}, got {actual_digest}"
        )


# ──────────────────────────────────────────────────────────────────────────
# Runtime registry
# ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Runtime:
    """Metadata describing a host runtime Capacium can detect."""

    name: str
    check_cmd: Sequence[str]
    provides: Sequence[str]
    install_hints: Dict[str, str] = field(default_factory=dict)
    homepage: str = ""

    def install_hint_for(self, platform: Optional[str] = None) -> Optional[str]:
        """Return the install hint for the given platform name (sys.platform)."""
        plat = platform if platform is not None else sys.platform
        # Try exact match first, then broad linux/darwin/win prefixes.
        if plat in self.install_hints:
            return self.install_hints[plat]
        if plat.startswith("linux") and "linux" in self.install_hints:
            return self.install_hints["linux"]
        if plat.startswith("darwin") and "darwin" in self.install_hints:
            return self.install_hints["darwin"]
        if plat.startswith("win") and "win32" in self.install_hints:
            return self.install_hints["win32"]
        return None


RUNTIMES: Dict[str, Runtime] = {
    "uv": Runtime(
        name="uv",
        check_cmd=("uv", "--version"),
        provides=("uv", "uvx"),
        install_hints={
            "darwin": "brew install uv",
            "linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "win32": "winget install --id=astral-sh.uv",
        },
        homepage="https://docs.astral.sh/uv/",
    ),
    "node": Runtime(
        name="node",
        check_cmd=("node", "--version"),
        provides=("node", "npm", "npx"),
        install_hints={
            "darwin": "brew install node",
            "linux": "see https://nodejs.org/en/download/package-manager",
            "win32": "winget install OpenJS.NodeJS",
        },
        homepage="https://nodejs.org/",
    ),
    "python": Runtime(
        name="python",
        check_cmd=("python3", "--version"),
        provides=("python", "python3"),
        install_hints={
            "darwin": "brew install python",
            "linux": "see https://www.python.org/downloads/",
            "win32": "winget install Python.Python.3",
        },
        homepage="https://www.python.org/",
    ),
    "pipx": Runtime(
        name="pipx",
        check_cmd=("pipx", "--version"),
        provides=("pipx",),
        install_hints={
            "darwin": "brew install pipx",
            "linux": "python3 -m pip install --user pipx && python3 -m pipx ensurepath",
            "win32": "python -m pip install --user pipx",
        },
        homepage="https://pipx.pypa.io/",
    ),
    "docker": Runtime(
        name="docker",
        check_cmd=("docker", "--version"),
        provides=("docker",),
        install_hints={
            "darwin": "brew install --cask docker",
            "linux": "see https://docs.docker.com/engine/install/",
            "win32": "winget install Docker.DockerDesktop",
        },
        homepage="https://www.docker.com/",
    ),
    "go": Runtime(
        name="go",
        check_cmd=("go", "version"),
        provides=("go",),
        install_hints={
            "darwin": "brew install go",
            "linux": "see https://go.dev/doc/install",
            "win32": "winget install GoLang.Go",
        },
        homepage="https://go.dev/",
    ),
    "bun": Runtime(
        name="bun",
        check_cmd=("bun", "--version"),
        provides=("bun", "bunx"),
        install_hints={
            "darwin": "brew install oven-sh/bun/bun",
            "linux": "curl -fsSL https://bun.sh/install | bash",
            "win32": "powershell -c \"irm bun.sh/install.ps1 | iex\"",
        },
        homepage="https://bun.sh/",
    ),
    "deno": Runtime(
        name="deno",
        check_cmd=("deno", "--version"),
        provides=("deno",),
        install_hints={
            "darwin": "brew install deno",
            "linux": "curl -fsSL https://deno.land/install.sh | sh",
            "win32": "winget install DenoLand.Deno",
        },
        homepage="https://deno.com/",
    ),
}


# ──────────────────────────────────────────────────────────────────────────
# Auto-inference of runtimes from mcp.command
# ──────────────────────────────────────────────────────────────────────────

# Map of well-known wrapper commands → runtime name in RUNTIMES.
_COMMAND_TO_RUNTIME: Dict[str, str] = {
    "uvx": "uv",
    "uv": "uv",
    "npx": "node",
    "npm": "node",
    "node": "node",
    "pipx": "pipx",
    "python": "python",
    "python3": "python",
    "docker": "docker",
    "go": "go",
    "bun": "bun",
    "bunx": "bun",
    "deno": "deno",
}


def runtime_for_command(command: str) -> Optional[str]:
    """Return the runtime name that provides ``command``, or None.

    Examples
    --------
    >>> runtime_for_command("uvx")
    'uv'
    >>> runtime_for_command("npx")
    'node'
    >>> runtime_for_command("rustc") is None
    True
    """
    if not command:
        return None
    base = command.strip().split()[0]
    base = base.split("/")[-1]
    return _COMMAND_TO_RUNTIME.get(base)


def infer_required_runtimes(manifest) -> Dict[str, str]:
    """Compute the runtime requirements for a manifest.

    Merges declared ``manifest.runtimes`` with any auto-inferred runtimes from
    ``manifest.mcp.command`` (when missing). Declared values win over inferred.
    """
    declared: Dict[str, str] = {}
    raw = getattr(manifest, "runtimes", None) or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            declared[str(k)] = str(v) if v is not None else "*"

    mcp = getattr(manifest, "mcp", None) or {}
    command = mcp.get("command") if isinstance(mcp, dict) else None
    inferred_name = runtime_for_command(command) if command else None
    if inferred_name and inferred_name not in declared:
        declared[inferred_name] = "*"

    return declared


# ──────────────────────────────────────────────────────────────────────────
# Version comparison (stdlib-only)
# ──────────────────────────────────────────────────────────────────────────

_VERSION_RE = re.compile(r"(\d+(?:\.\d+){0,3})")


def parse_version(text: str) -> Tuple[int, ...]:
    """Extract a numeric version tuple from arbitrary version output.

    Stripped down semver: returns up to 4 numeric components, padded with zeros
    so comparisons are total. Returns ``(0,)`` if nothing parses.
    """
    if not text:
        return (0,)
    match = _VERSION_RE.search(text)
    if not match:
        return (0,)
    parts = match.group(1).split(".")
    nums = tuple(int(p) for p in parts)
    # Pad to length 3 for stable comparisons.
    while len(nums) < 3:
        nums = nums + (0,)
    return nums


def _normalize(t: Tuple[int, ...], length: int) -> Tuple[int, ...]:
    if len(t) >= length:
        return t[:length]
    return t + (0,) * (length - len(t))


def satisfies(version: str, requirement: str) -> bool:
    """Return True if ``version`` satisfies ``requirement``.

    Supported requirement forms:

    * ``"*"`` or empty → always True
    * ``">=X[.Y[.Z]]"`` → version must be greater than or equal to X.Y.Z
    * ``"X.Y.Z"`` (bare) → treated as ``">=X.Y.Z"`` (loose)

    Any other form is permissive and returns True (callers should rely on the
    runtime's own self-check rather than fighting unrecognized strings).
    """
    if not requirement or requirement.strip() == "*":
        return True
    req = requirement.strip()
    if req.startswith(">="):
        bound = parse_version(req[2:])
        have = parse_version(version)
        length = max(len(bound), len(have))
        return _normalize(have, length) >= _normalize(bound, length)
    if re.fullmatch(r"\d+(\.\d+)*", req):
        # bare X.Y.Z → loose >=X.Y.Z
        bound = parse_version(req)
        have = parse_version(version)
        length = max(len(bound), len(have))
        return _normalize(have, length) >= _normalize(bound, length)
    return True


# ──────────────────────────────────────────────────────────────────────────
# Resolver
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class RuntimeStatus:
    """Result of probing a single runtime."""

    name: str
    requirement: str
    runtime: Optional[Runtime]
    found: bool
    version: Optional[str]
    satisfied: bool
    install_hint: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.found and self.satisfied

    def describe(self) -> str:
        if self.runtime is None:
            return f"{self.name}: unknown runtime (no detection rule)"
        if not self.found:
            hint = f" — install: {self.install_hint}" if self.install_hint else ""
            return f"{self.name}: missing (need {self.requirement}){hint}"
        if not self.satisfied:
            return (
                f"{self.name}: found {self.version} but requires {self.requirement}"
            )
        return f"{self.name}: ok ({self.version})"


class RuntimeResolver:
    """Probe local runtimes against a requirement map."""

    def __init__(
        self,
        registry: Optional[Dict[str, Runtime]] = None,
        which=shutil.which,
        run=subprocess.run,
    ):
        self._registry = registry if registry is not None else RUNTIMES
        self._which = which
        self._run = run

    def known(self, name: str) -> Optional[Runtime]:
        return self._registry.get(name)

    def detect(self, name: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Detect a runtime — returns (found, version, error)."""
        rt = self._registry.get(name)
        if rt is None:
            return False, None, f"unknown runtime: {name}"
        if not self._which(rt.check_cmd[0]):
            return False, None, None
        try:
            result = self._run(
                list(rt.check_cmd),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return False, None, str(exc)
        out = (result.stdout or "") + "\n" + (result.stderr or "")
        match = _VERSION_RE.search(out)
        version = match.group(1) if match else None
        return True, version, None

    def resolve(self, requirements: Dict[str, str]) -> List[RuntimeStatus]:
        statuses: List[RuntimeStatus] = []
        for name, requirement in requirements.items():
            rt = self._registry.get(name)
            if rt is None:
                statuses.append(
                    RuntimeStatus(
                        name=name,
                        requirement=requirement or "*",
                        runtime=None,
                        found=False,
                        version=None,
                        satisfied=False,
                        error=f"unknown runtime: {name}",
                    )
                )
                continue
            found, version, error = self.detect(name)
            satisfied = bool(found and satisfies(version or "0", requirement or "*"))
            statuses.append(
                RuntimeStatus(
                    name=name,
                    requirement=requirement or "*",
                    runtime=rt,
                    found=found,
                    version=version,
                    satisfied=satisfied,
                    install_hint=rt.install_hint_for(),
                    error=error,
                )
            )
        return statuses


# ──────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ──────────────────────────────────────────────────────────────────────────

def format_failure_report(
    statuses: Iterable[RuntimeStatus],
    *,
    platform: Optional[str] = None,
) -> str:
    """Format a human-friendly error message listing failing runtimes."""
    lines: List[str] = []
    failures = [s for s in statuses if not s.ok]
    if not failures:
        return ""
    lines.append("Missing or incompatible runtimes:")
    for s in failures:
        lines.append(f"  - {s.describe()}")
        if s.runtime is not None:
            hint = s.runtime.install_hint_for(platform)
            if hint and (not s.found):
                lines.append(f"      install: {hint}")
            if s.runtime.homepage:
                lines.append(f"      docs:    {s.runtime.homepage}")
    lines.append("")
    lines.append("Re-run with --skip-runtime-check to bypass this gate.")
    return "\n".join(lines)


def try_install_runtime(status: RuntimeStatus) -> bool:
    """Attempt to install or upgrade the runtime described by *status*.

    Runs the platform-appropriate install hint as a shell command. Returns True
    when the process exits with code 0, False otherwise.

    Only runtimes with a known install hint for the current platform can be
    auto-resolved. For unknown runtimes or missing hints this returns False
    immediately (no subprocess is spawned).
    """
    if status.runtime is None:
        return False
    hint = status.runtime.install_hint_for()
    if not hint:
        return False
    print(f"  Running: {hint}")
    ret = subprocess.run(hint, shell=True, check=False)
    return ret.returncode == 0


def prompt_and_resolve_runtimes(
    statuses: List[RuntimeStatus],
    *,
    yes: bool = False,
    resolver: Optional["RuntimeResolver"] = None,
) -> List[RuntimeStatus]:
    """Interactive loop: show failing runtimes, optionally install, re-check.

    Parameters
    ----------
    statuses:
        The initial resolver output — only failures are acted on.
    yes:
        If True, auto-accept without prompting (non-interactive CI mode).
    resolver:
        Resolver instance used for the post-install re-check. A fresh default
        instance is created when None.

    Returns
    -------
    Updated list of RuntimeStatus after any install attempts.
    """
    failures = [s for s in statuses if not s.ok]
    if not failures:
        return statuses

    _rt_sym = {True: "✓", False: "✗"}
    print()
    print("  Runtime requirements:")
    for s in statuses:
        sym = _rt_sym[s.ok]
        label = s.version if s.found else "not found"
        req = f"requires {s.requirement}" if s.requirement and s.requirement != "*" else "any version"
        upgrade = " (upgrade available)" if s.found and not s.satisfied else ""
        print(f"    {sym}  {s.name}: {label} — {req}{upgrade}")
        if not s.ok and s.install_hint:
            action = "upgrade" if s.found else "install"
            print(f"         hint: {s.install_hint}  [{action}]")

    # Check which failures have a resolvable install hint
    resolvable = [s for s in failures if s.runtime and s.runtime.install_hint_for()]
    unresolvable = [s for s in failures if not (s.runtime and s.runtime.install_hint_for())]

    if unresolvable:
        print()
        for s in unresolvable:
            print(f"  ⚠  {s.name}: no automatic install hint available")
            if s.runtime and s.runtime.homepage:
                print(f"     See: {s.runtime.homepage}")

    if not resolvable:
        print()
        print("  No runtimes can be auto-installed. Use --skip-runtime-check to bypass.")
        return statuses

    print()
    names = ", ".join(s.name for s in resolvable)
    if yes:
        print(f"  Auto-installing: {names}")
        answer = "y"
    else:
        try:
            answer = input(f"  Install/upgrade {names}? [Y/n] ").strip().lower() or "y"
        except (EOFError, KeyboardInterrupt):
            answer = "n"

    if answer not in ("y", "yes"):
        print("  Skipping. Use --skip-runtime-check to install without runtime checks.")
        return statuses

    any_installed = False
    for s in resolvable:
        action = "Upgrading" if s.found else "Installing"
        print(f"  {action} {s.name}...")
        if try_install_runtime(s):
            print(f"  ✓  {s.name} installed successfully")
            any_installed = True
        else:
            print(f"  ✗  {s.name} install failed — check output above")

    if not any_installed:
        return statuses

    # Re-check all requirements after install
    if resolver is None:
        resolver = RuntimeResolver()
    requirements = {s.name: s.requirement for s in statuses}
    return resolver.resolve(requirements)


def known_runtime_names() -> List[str]:
    return sorted(RUNTIMES.keys())


# ──────────────────────────────────────────────────────────────────────────
# Criterion 7: Generation GC — rollback retention and safe deletion
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GenerationLease:
    """A lease that prevents GC from deleting a generation during use.

    Acquired before a concurrent build/activation and released when done.
    """

    lease_id: str
    generation_id: str


def _store_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".capacium", "generations", "store.json")


class GenerationStore:
    """Persistent store for runtime generations with active/reference/lease tracking.

    Holds RuntimeGeneration objects and tracks:
    - Which generation is currently active
    - References between generations (e.g. parent -> child)
    - Active leases that prevent GC

    Persisted to ``~/.capacium/generations/store.json`` so generations
    survive across CLI process invocations.
    """

    def __init__(self) -> None:
        self._generations: Dict[str, RuntimeGeneration] = {}
        self._active_generation_id: Optional[str] = None
        self._references: Dict[str, set] = {}  # parent_id -> set of child_ids
        self._leases: Dict[str, GenerationLease] = {}  # generation_id -> lease
        self._lease_counter: int = 0

    def add(self, gen: RuntimeGeneration) -> None:
        """Add a generation to the store and persist."""
        self._generations[gen.digest] = gen
        self.save()

    def get(self, digest: str) -> Optional[RuntimeGeneration]:
        """Retrieve a generation by digest."""
        return self._generations.get(digest)

    def remove(self, digest: str) -> Optional[RuntimeGeneration]:
        """Remove a generation from the store and persist. Returns the removed gen or None."""
        removed = self._generations.pop(digest, None)
        if removed is not None:
            self.save()
        return removed

    def save(self) -> None:
        """Persist the store to disk."""
        sp = _store_path()
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        data: Dict[str, Any] = {
            "active_generation_id": self._active_generation_id,
            "generations": {
                digest: {
                    "digest": gen.digest,
                    "source_lock": {
                        "source_url": gen.source_lock.source_url,
                        "digest": gen.source_lock.digest,
                        "source_type": gen.source_lock.source_type.value,
                        "interpreter": gen.source_lock.interpreter,
                        "platforms": gen.source_lock.platforms,
                        "dependency_lock_digest": gen.source_lock.dependency_lock_digest,
                        "build_inputs": gen.source_lock.build_inputs,
                        "probes": gen.source_lock.probes,
                        "entrypoints": {
                            k: list(v) for k, v in gen.source_lock.entrypoints.items()
                        },
                    },
                }
                for digest, gen in self._generations.items()
            },
        }
        with open(sp, "w") as f:
            json.dump(data, f, sort_keys=True, indent=2)

    def load(self) -> bool:
        """Load the store from disk. Returns True if a file existed and was loaded."""
        sp = _store_path()
        if not os.path.isfile(sp):
            return False
        try:
            with open(sp, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False
        self._active_generation_id = data.get("active_generation_id")
        for digest, gen_data in data.get("generations", {}).items():
            sl = gen_data.get("source_lock", {})
            entrypoints_raw = sl.get("entrypoints", {})
            source_lock = SourceLock(
                source_url=sl.get("source_url", ""),
                digest=sl.get("digest", ""),
                source_type=SourceType(sl.get("source_type", "verified_local_cache")),
                interpreter=sl.get("interpreter", ""),
                platforms=sl.get("platforms", []),
                dependency_lock_digest=sl.get("dependency_lock_digest", ""),
                build_inputs=sl.get("build_inputs", {}),
                probes=sl.get("probes", {}),
                entrypoints={
                    k: tuple(v) for k, v in entrypoints_raw.items()
                },
            )
            gen = RuntimeGeneration(
                digest=gen_data.get("digest", digest),
                source_lock=source_lock,
            )
            self._generations[digest] = gen
        return True

    @property
    def active_generation_id(self) -> Optional[str]:
        return self._active_generation_id

    def set_active(self, digest: str) -> None:
        """Mark a generation as the currently active one."""
        self._active_generation_id = digest

    def is_active(self, digest: str) -> bool:
        """Return True if the given digest is the active generation."""
        return self._active_generation_id == digest

    def add_reference(self, parent_id: str, child_id: str) -> None:
        """Record that *parent_id* references *child_id*."""
        if parent_id not in self._references:
            self._references[parent_id] = set()
        self._references[parent_id].add(child_id)

    def is_referenced(self, digest: str) -> bool:
        """Return True if any generation references *digest*."""
        return any(digest in refs for refs in self._references.values())

    def acquire_lease(self, generation_id: str) -> GenerationLease:
        """Acquire a lease on a generation, preventing GC deletion.

        Returns a GenerationLease that must be released when done.
        """
        self._lease_counter += 1
        lease = GenerationLease(
            lease_id=f"lease-{self._lease_counter}",
            generation_id=generation_id,
        )
        self._leases[generation_id] = lease
        return lease

    def release_lease(self, lease: GenerationLease) -> None:
        """Release a previously acquired lease. Idempotent — missing leases
        are silently ignored."""
        if lease.generation_id in self._leases:
            existing = self._leases[lease.generation_id]
            if existing.lease_id == lease.lease_id:
                del self._leases[lease.generation_id]

    def is_leased(self, generation_id: str) -> bool:
        """Return True if *generation_id* has an active lease."""
        return generation_id in self._leases

    def _is_protected(self, digest: str) -> bool:
        """Return True if a generation is active, referenced or leased."""
        if self.is_active(digest):
            return True
        if self.is_referenced(digest):
            return True
        if self.is_leased(digest):
            return True
        return False


class RuntimeGarbageCollector:
    """Basic GC for runtime generations.

    Only deletes generations that are:
    - Unreferenced (no other generation references them)
    - Inactive (not the current active generation)
    - Unleashed (no concurrent build/activation lease)
    """

    def __init__(self, store: GenerationStore):
        self._store = store

    def dry_run(self) -> Dict[str, bool]:
        """Report which generations would be deleted, without deleting.

        Returns a dict mapping generation digest -> True for each candidate.
        Active, leased and referenced generations are excluded.
        """
        candidates: Dict[str, bool] = {}
        for digest, gen in list(self._store._generations.items()):
            if not self._store._is_protected(digest):
                candidates[digest] = True
        return candidates

    def collect(self) -> Dict[str, bool]:
        """Delete unreferenced, inactive, unleased generations.

        Returns a dict mapping deleted generation digest -> True.
        Protected generations (active, referenced, leased) are never deleted.
        """
        deleted: Dict[str, bool] = {}
        for digest in list(self._store._generations.keys()):
            if not self._store._is_protected(digest):
                self._store.remove(digest)
                deleted[digest] = True
        return deleted


class GenerationManager:
    """Orchestrates the generation lifecycle: store, dry-run and GC collect.

    On construction, loads the persistent store from
    ``~/.capacium/generations/store.json`` so generations survive across
    CLI process invocations.
    """

    def __init__(self) -> None:
        self.store = GenerationStore()
        self.store.load()
        self._gc = RuntimeGarbageCollector(self.store)

    def dry_run_gc(self) -> Dict[str, bool]:
        """Report which generations would be collected by GC."""
        return self._gc.dry_run()

    def collect_gc(self) -> Dict[str, bool]:
        """Run GC collection, deleting unprotected generations."""
        return self._gc.collect()
