"""
Capacium — Capability Packaging System
Agent-agnostic, manifest-first packaging for AI agent capabilities.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("capacium")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__author__ = "Capacium"
