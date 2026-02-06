# Contributing to Nautilus Bitbank Adapter

Thank you for your interest in contributing to the Nautilus Bitbank Adapter!

## Branch Naming Convention

We follow a strict branch naming convention to keep our repository organized. Please use the following prefixes for your branches:

- **`feature/*`**: For new features or enhancements.
  - Example: `feature/add-market-data-stream`
- **`fix/*`**: For bug fixes.
  - Example: `fix/resolve-connection-timeout`
- **`docs/*`**: For documentation updates.
  - Example: `docs/update-installation-guide`
- **`chore/*`**: For maintenance tasks, dependency updates, etc.
  - Example: `chore/update-dependencies`

**Note:** The CI pipeline will trigger tests on `feature/*` and `fix/*` branches.

## Development Workflow

1.  Create a new branch from `main` using one of the prefixes above.
2.  Make your changes and ensure tests pass locally.
3.  Push your branch to the repository.
4.  Open a Pull Request pointing to `main`.
5.  Ensure CI checks pass before merging.

## Testing

Run unit tests locally before pushing:

```bash
pytest tests/ -v -m "not live"
```

For live tests (requires API credentials):

```bash
export BITBANK_API_KEY="your_key"
export BITBANK_API_SECRET="your_secret"
pytest tests/ -v -m "live"
```
