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

The command runs green. The failure count — the number CI actually gates on — is
the invariant: `0 failed`. The `S passed` and `N skipped` figures are not a
promise; they move as tests are added or skipped and are a snapshot, not an
invariant. In particular `S passed` is not the collected count: a skipped test
is collected but not passed, so `S passed` equals the collected count only while
nothing skips. Do not recompute the pass figure with `--collect-only` and expect
it to match a run that skips.

Expected result at `1ce0a9d`: `0 failed, 2071 passed, 0 skipped` (31 warnings),
with or without `source .venv/bin/activate`. The result is identical either way
because the subprocess-spawning tests invoke `sys.executable` (the interpreter
running pytest), never a `python3` resolved from `PATH`.

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
