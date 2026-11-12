# Integrations

Each subdirectory is an independently installable integration for one tool. Its
README states its status, supported versions, limits and how to reproduce its
real-data check. Browse the directories; nothing outside them needs to change
when an integration is added or removed.

## Contract for an integration

- `README.md`: what it does, installation, walkthrough, supported versions, limits
  and troubleshooting.
- `pyproject.toml` and `uv.lock`: its own dependencies, with a `dev` dependency
  group containing `ruff` and `pytest`; heavy third-party tools go in optional extras.
- `src/` and `tests/`: unit tests stay offline, using fixtures and transport doubles.
- `docs/`: a real-data verification (source revision, report revision, software
  versions, checks run, limitations) and an integration-specific
  `TRUST_BOUNDARIES.md` that extends [the repository-level boundaries](../docs/TRUST_BOUNDARIES.md).
- `examples/`: captured public evidence only. No credentials, private reports,
  machine-specific paths or raw datasets.
- `LICENSE`: a copy of the repository license so built distributions carry it.

## Continuous integration

CI discovers every `integrations/*/pyproject.toml` and, for each one, runs
`uv sync --frozen`, `ruff check`, `ruff format --check` and `pytest` from that
directory. The single `tests` check passes only when all of them pass, so branch
protection never needs updating when integrations change.
