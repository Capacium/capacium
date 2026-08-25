# Contributing to Capacium

Thanks for your interest. Contributions are welcome.

## Development Setup

```bash
git clone https://git.langevc.com/capacium/capacium.git capacium
cd capacium
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install pyyaml cryptography pytest pytest-cov ruff
pip install git+https://github.com/Capacium/capacium-models.git
pip install -e ".[trust]"
```

These install steps match `.forgejo/workflows/ci.yml` exactly. Do not use
`pip install -e ".[dev]"` — that extra is missing `pyyaml`, `cryptography`,
`pytest-cov`, `ruff`, `trust` (PyNaCl) and `capacium-models`, so the test
suite fails to collect (`ModuleNotFoundError: No module named 'nacl'`).

## Running Tests

```bash
python -m pytest tests/ -v --tb=short --cov=src/capacium \
  --ignore=tests/test_signing.py \
  --ignore=tests/test_integration_phase0.py
```

This is the exact command CI runs (`ci.yml` "Test with pytest"). It must be
run from a real install (`pip install -e ".[trust]"` above): several tests
spawn `python -m capacium.cli` as a subprocess and fail with
`ModuleNotFoundError: No module named 'capacium'` when the package is only on
`PYTHONPATH` or not installed at all.

The result is deterministic whether or not `.venv` is activated: the
subprocess-spawning tests invoke `sys.executable` (the interpreter running
pytest), never a `python3` resolved from `PATH`.

Three failures have existed across recent releases and are not caused by your
checkout:

- `tests/neutrality/test_p01k_hermeticity.py::test_p01_suite_passes_under_the_access_guard` — the P01 suite exits 1 under the hermeticity access guard (CAP-OPS-A5); still failing.
- `tests/test_resource_kind.py::TestCapInitKindResource::test_cap_init_kind_resource_produces_valid_manifest` — formerly spawned `python3` from `PATH` and so failed outside an activated venv; it now uses `sys.executable` and passes.
- `tests/test_integration_phase0.py::TestP0006BackfillMigrationLogic::test_migration_file_exists` — asserts `capacium-exchange/migrations/0004_backfill_kind_source.sql` exists as a sibling checkout, so it fails in a fresh clone; it is excluded by `--ignore=tests/test_integration_phase0.py` above.

Expected result: `1 failed, 2069 passed` (the single failure is the
`test_p01k_hermeticity` test above), with or without `source .venv/bin/activate`.

## Linting

```bash
python -m ruff check .
```

## Adding a New Capability Kind

1. Add the kind to `Kind` enum in `src/capacium/models.py`
2. Add validation rules in `src/capacium/manifest.py`
3. Add kind-specific install logic in `src/capacium/commands/install.py`
4. Add tests in `tests/test_manifest.py` and `tests/test_models.py`

## Adding a New Framework Adapter

1. Create `src/capacium/adapters/<framework>.py` extending `FrameworkAdapter`
2. Implement `install()`, `remove()`, `list_installed()` methods
3. Add tests in `tests/test_adapters/`
4. Register in adapter auto-selection logic

## Submitting Changes

1. Fork the repo
2. Create a `feature/<topic>` branch
3. Add tests for new functionality
4. Ensure `python -m pytest tests/ ...` and `python -m ruff check .` pass (see `Running Tests` above)
5. Open a PR with a clear description

## Community And Security

- Follow [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) in all repo interactions
- Report vulnerabilities through [SECURITY.md](./SECURITY.md), not a public issue
