# Contributing

Report suspected vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

Keep integrations independently installable and do not add dependencies for
features that do not exist. Follow the current selection/report contracts and
preserve unresolved evidence rather than filling gaps with guesses. New
integrations follow the contract in [integrations/README.md](integrations/README.md);
CI discovers them automatically.

From an integration's directory (`integrations/<tool>`):

```bash
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
uv build
```

Use `uv add` for dependency changes and commit the resulting lockfile. Unit tests
must remain offline. Cover stale revisions, missing/duplicate pages, unknown
and review decisions, provenance mismatches, invalid source indices, output
protection and any tool-specific loader or handoff checks.

Keep real-data checks opt-in. Document the source commit, report revision,
software versions, exact checks and limitations. Do not include credentials,
private reports, machine-specific root paths or raw datasets in a pull request.
Example reports are public evidence, not a claim of training improvement.
