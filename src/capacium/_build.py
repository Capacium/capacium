"""Deterministic sdist and wheel builds for the Capacium release.

``setuptools`` honours ``SOURCE_DATE_EPOCH`` for wheel zip entry timestamps
(``setuptools/_vendor/wheel/wheelfile.py``) but the wheel METADATA and WHEEL
files differ across setuptools versions: Metadata-Version, Requires-Dist
spacing and ordering, Generator tag, Dynamic fields and license-file placement
all vary. Two builds of the same commit on different machines therefore
produce different wheel bytes even though the payload is identical.

The sdist fares worse: ``distutils.archive_util.make_tarball`` writes the gzip
container header with ``time.time()`` and every tar member with its on-disk
mtime, so two builds differ in every timestamp field.

This module provides setuptools commands that post-process both artifacts.
When ``SOURCE_DATE_EPOCH`` is set the sdist archive is rewritten with pinned
container mtime, member mtimes, ownership fields and PAX headers, and the
wheel is re-packed with normalised METADATA/WHEEL content, sorted entries and
fixed zip timestamps. When the variable is unset both artifacts are left
exactly as setuptools produced them.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import os
import re
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel
from setuptools.command.sdist import sdist as _sdist


def source_date_epoch() -> int | None:
    """Return ``SOURCE_DATE_EPOCH`` as an int, or ``None`` when it is unset."""
    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"SOURCE_DATE_EPOCH must be an integer number of seconds, got {raw!r}"
        ) from exc


def normalize_gztar(path: Path, epoch: int) -> None:
    """Rewrite the gzip-compressed tarball at *path* with timestamps pinned.

    Member payloads, names, order and modes are preserved byte for byte; only
    the container header and the per-member metadata become fixed.

    PKG-INFO files are also normalised so that ``Metadata-Version`` and
    ``Dynamic`` fields do not depend on the installed setuptools version.
    """
    tmp = path.with_name(path.name + ".normalized")
    with tarfile.open(path, "r:gz") as source, open(tmp, "wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=epoch
        ) as gz:
            with tarfile.open(
                fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT
            ) as target:
                for member in source:
                    member.mtime = epoch
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    member.pax_headers = {}
                    payload = source.extractfile(member) if member.isfile() else None
                    if payload is not None and member.name.endswith("/PKG-INFO"):
                        raw_data = payload.read()
                        normalized = _normalize_metadata(raw_data)
                        member.size = len(normalized)
                        payload = io.BytesIO(normalized)
                    target.addfile(member, payload)
    os.replace(tmp, path)


# -- wheel normalization ------------------------------------------------------

def _find_dist_info(entries: dict) -> str:
    """Return the ``.dist-info`` directory name from a wheel's entry map."""
    for name in entries:
        if ".dist-info" in name:
            idx = name.index(".dist-info")
            return name[: idx + len(".dist-info")]
    raise ValueError("no .dist-info directory found in wheel")


def _normalize_requires_dist(value: str) -> str:
    """Normalize a ``Requires-Dist`` value for reproducibility.

    Collapses space between the distribution name and the version operator
    (``name>=version``) and normalises semicolons and quoting in extras
    markers.
    """
    # Collapse space(s) between package name and version operator
    value = re.sub(r"(\w)\s+(>=|<=|!=|==|~=|<|>|===)", r"\1\2", value)
    # Normalise double quotes to single in extras markers
    value = value.replace('"', "'")
    # Normalise semicolon spacing: one space before and after
    value = re.sub(r"\s*;\s*", "; ", value)
    return value


def _normalize_metadata(data: bytes) -> bytes:
    """Rewrite wheel METADATA for version-independent reproducibility.

    Pins ``Metadata-Version`` to 2.1, normalises ``Requires-Dist`` spacing
    and quoting, drops ``Dynamic``, and sorts headers alphabetically (with
    ``Metadata-Version`` always first). The blank line that separates RFC 822
    headers from the body is preserved; body lines are never sorted.
    """
    lines = data.decode("utf-8").splitlines()
    # Find the first blank line — it separates headers from the body.
    blank_idx: int | None = None
    for i, line in enumerate(lines):
        if line == "":
            blank_idx = i
            break
    if blank_idx is None:
        blank_idx = len(lines)
    header_lines = lines[:blank_idx]
    body_lines = lines[blank_idx:]  # includes the blank terminator at [0]

    result: list[str] = []
    for line in header_lines:
        if line.startswith("Metadata-Version:"):
            result.append("Metadata-Version: 2.1")
        elif line.startswith("Dynamic:"):
            continue
        elif line.startswith("Requires-Dist:"):
            _prefix, value = line.split(":", 1)
            result.append(f"Requires-Dist: {_normalize_requires_dist(value.strip())}")
        else:
            result.append(line)
    header_first = result[0]  # Metadata-Version
    header_rest = sorted(result[1:])
    return "\n".join([header_first] + header_rest + body_lines).encode("utf-8")


def _normalize_wheel_file(data: bytes) -> bytes:
    """Strip the ``Generator`` line from the WHEEL metadata."""
    lines = data.decode("utf-8").splitlines()
    kept = [line for line in lines if not line.startswith("Generator:")]
    return "\n".join(kept).encode("utf-8") + b"\n"


def normalize_wheel(path: Path, epoch: int) -> None:
    """Repack the wheel at *path* with normalised metadata and timestamps.

    The METADATA file is rewritten so that ``Metadata-Version``,
    ``Requires-Dist`` spacing/ordering, ``Dynamic`` and ``Generator`` no
    longer depend on the installed setuptools version. License files are
    moved from ``dist-info/licenses/`` to ``dist-info/`` (older setuptools
    convention). Zip entry timestamps and permissions are pinned, entries are
    sorted alphabetically and ``RECORD`` is regenerated with correct digests.
    """
    with zipfile.ZipFile(path, "r") as zf:
        entries = {info.filename: zf.read(info.filename) for info in zf.infolist()}

    pkginfo = _find_dist_info(entries)

    meta_key = f"{pkginfo}/METADATA"
    if meta_key in entries:
        entries[meta_key] = _normalize_metadata(entries[meta_key])

    wheel_key = f"{pkginfo}/WHEEL"
    if wheel_key in entries:
        entries[wheel_key] = _normalize_wheel_file(entries[wheel_key])

    # Move license files from licenses/ subdir to flat dist-info/
    licenses_dir = f"{pkginfo}/licenses/"
    for name in list(entries):
        if name.startswith(licenses_dir):
            flat_name = f"{pkginfo}/{name[len(licenses_dir):]}"
            entries[flat_name] = entries.pop(name)

    # Remove stale RECORD
    entries.pop(f"{pkginfo}/RECORD", None)

    sorted_names = sorted(entries.keys())

    # Generate RECORD with SHA-256 digests of normalised content
    record_lines = []
    for name in sorted_names:
        data = entries[name]
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .rstrip(b"=")
            .decode()
        )
        record_lines.append(f"{name},sha256={digest},{len(data)}")
    record_lines.append(f"{pkginfo}/RECORD,,")
    entries[f"{pkginfo}/RECORD"] = "\n".join(record_lines).encode("utf-8") + b"\n"
    sorted_names = sorted(entries.keys())

    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    ts = dt.timetuple()[:6]
    tmp = path.with_name(path.name + ".normalized")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted_names:
            zi = zipfile.ZipInfo(name, ts)
            zi.external_attr = 0o644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, entries[name])
    os.replace(tmp, path)


# -- setuptools commands -------------------------------------------------------

class ReproducibleSdist(_sdist):
    """``sdist`` that pins the archive timestamps when an epoch is declared."""

    def make_archive(  # type: ignore[override]
        self,
        base_name: str,
        format: str,
        root_dir: str | None = None,
        base_dir: str | None = None,
        owner: str | None = None,
        group: str | None = None,
    ) -> str:
        archive = super().make_archive(
            base_name,
            format,
            root_dir=root_dir,
            base_dir=base_dir,
            owner=owner,
            group=group,
        )
        epoch = source_date_epoch()
        if format == "gztar" and epoch is not None:
            normalize_gztar(Path(archive), epoch)
        return archive


class ReproducibleWheel(_bdist_wheel):
    """``bdist_wheel`` that normalises metadata for cross-version reproducibility."""

    def run(self) -> None:
        super().run()
        epoch = source_date_epoch()
        if epoch is not None:
            wheels = sorted(Path(self.dist_dir).glob("*.whl"))
            if wheels:
                normalize_wheel(wheels[0], epoch)
