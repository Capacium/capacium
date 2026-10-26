"""Deterministic sdist archiving for the Capacium release build.

``setuptools`` honours ``SOURCE_DATE_EPOCH`` for wheels
(``setuptools/_vendor/wheel/wheelfile.py``) but not for an sdist:
``distutils.archive_util.make_tarball`` writes the gzip container header with
``time.time()`` and every tar member with its on-disk mtime. Two builds of the
same commit therefore differ in bytes even though the payload is identical.

This command rewrites the archive after it is produced, pinning the container
mtime, every member mtime, the ownership fields and the PAX headers to
``SOURCE_DATE_EPOCH``. Nothing else (member order, names, modes, contents) is
changed, so the archive stays a faithful sdist.

When ``SOURCE_DATE_EPOCH`` is unset the archive is left exactly as setuptools
produced it: an ordinary developer build keeps its build-time stamp, and only a
build that declares a normalised timestamp becomes byte-reproducible.
"""

from __future__ import annotations

import gzip
import os
import tarfile
from pathlib import Path

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
                    target.addfile(member, payload)
    os.replace(tmp, path)


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
