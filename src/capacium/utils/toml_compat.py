"""tomllib compatibility: stdlib since 3.11, tomli backport on 3.10."""

try:
    import tomllib  # noqa: F401
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # noqa: F401
