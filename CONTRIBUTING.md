# Contributing to Capacium

Thanks for your interest. Contributions are welcome.

## Development Setup

```bash
git clone https://github.com/typelicious/capacium.git capacium
cd capacium
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
pytest --cov=capacium tests/
```

## Linting

```bash
ruff check .
ruff format --check .
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
4. Ensure `pytest` and `ruff` pass
5. Open a PR with a clear description

## Community And Security

- Follow [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) in all repo interactions
- Report vulnerabilities through [SECURITY.md](./SECURITY.md), not a public issue
