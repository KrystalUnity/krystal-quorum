# Contributing

Thanks for helping make Krystal Quorum useful for developers who review AI coding plans before implementation.

## Development Setup

```bash
git clone https://github.com/KrystalUnity/krystal-quorum.git
cd krystal-quorum
python -m pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request:

```bash
python -m ruff check .
python -m pytest -q
python -m build
python -m twine check dist/*
```

## Pull Requests

- Keep changes focused and easy to review.
- Add tests for new behavior.
- Avoid committing private reviewer outputs, local `.env` files, or `.krystal-quorum/reviews/` artifacts.
- Prefer public, reusable examples over machine-specific scripts.

## Reviewer Integrations

New reviewer adapters should preserve the strict JSON contract and should abstain cleanly when a model or command cannot return parseable review output.
