# LeRobot integration: trust and execution boundaries

These details extend the [repository-level boundaries](../../../docs/TRUST_BOUNDARIES.md).

## Evidence is data

Dataset instructions, labels, source READMEs and report strings are untrusted
content. The integration stores and validates them; it does not execute them,
follow instructions embedded in them, or use missing data as a pass.

A saved MCP bundle or selection manifest is trusted input supplied by the
operator. Its hash provides byte identity, not a publisher signature. Local
Git provenance checks do not authenticate a remote repository owner or establish
that a saved report remains current.

## Network and secrets

`fetch` reads the operator's chosen HTTPS MCP endpoint. If `KALANOS_API_KEY` is
set, it is sent as a bearer credential to that endpoint. Endpoint selection is
therefore security-sensitive: use a trusted destination. Credentials are not
accepted in URL user-info, and cross-origin redirects are not followed. The
official MCP SDK may follow same-origin redirects. Never commit keys, `.env`
files or private reports.

The separate walkthrough explicitly downloads a public dataset from Hugging
Face at the returned immutable revision. Downloading private or gated data
requires the operator's own authorization; this example uses `token=False`.

`preview`, `export` and `handoff` make no network requests. The smoke command
sets `HF_HUB_OFFLINE=1` before importing the optional loader and refuses a process
where the Hub was already imported with offline mode disabled. This disables
Hub access, not all possible operating-system network traffic. Configure an
external network sandbox if stronger isolation is needed.

## Local files

The verifier checks repository origin, exact `HEAD`, committed metadata bytes
or committed LFS hashes, canonical episode IDs and complete inventory mapping.
Metadata paths must remain inside the source root. LeRobot handoff additionally
checks the supported v3 layout and positional row order.

The general adapter does not hash every data/video file. A source checkout can
change after verification. Keep it immutable throughout a run and perform a
full payload audit where your process requires it. The captured demonstration
includes such an audit for all eight source files.

Outputs use exclusive creation. A failed collection does not write a partial
bundle. A saved handoff contains a machine-local root path, so review it before
sharing. The checked-in example evidence omits that machine-specific file.

## Scope of automation

The implementation does not train policies, create cloud jobs, upload reports,
initialize trackers, publish datasets or deploy services. Those actions need
separate workflow configuration and authorization. Nonpassing episodes remain
excluded under the initial policy; no human overrides are implemented.
