# Repository design

`kalanos-mcp` hosts small integrations around the same published evidence
contract. It is an integration kit, not another MCP host.

## Layout

Each directory under `integrations/` is an independent integration with its own
package, lockfile, optional runtime dependencies, examples, tests and
documentation. Installing one does not install the grader or any other
integration. There are no empty packages and no generic orchestration framework.
The contract a new integration follows is in
[integrations/README.md](../integrations/README.md).

## Shared flow

1. **Collection:** official MCP SDK, complete pagination, report/source identity
   checks, one complete restart on stale evidence, final current-token check.
2. **Selection:** an offline, pass-only policy with pinned source-metadata
   verification. It exports the shared `kalanos.selection.v1` contract.
3. **Handoff:** tool-specific compatibility checks and arguments for the
   existing tool, which remains responsible for loading, training or review.

## Adding an integration

Add a directory under `integrations/` that follows the contract. CI discovers it
automatically; no repository-level file needs editing. Do not add a tool-specific
MCP call to carry data the shared manifest already represents. When two
integrations need the same implementation, extract a tested shared library;
until then, keep interfaces explicit.

## What stays outside this repository

- Kalanos's hosted MCP worker and Hub deployment.
- The grading engine and private grading execution.
- Policy trainers, model architectures and training schedulers.
- Accounts, API keys, private data and credentials.
- Automatic publication, paid compute or third-party messages.
