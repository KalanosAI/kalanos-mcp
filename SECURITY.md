# Security policy

## Supported versions

This repository is a 0.x source preview. Fixes land on `main`; older commits are not
patched separately.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting: open the **Security** tab and choose **Report a vulnerability**.
Include the affected commit or version, reproduction steps, and the impact you observed.
We will acknowledge the report, work on a fix, and coordinate disclosure with you.

You can also email [reports@kalanos.ai](mailto:reports@kalanos.ai). Email is not encrypted,
so use the GitHub advisory for sensitive technical detail.

Never include real credentials, private reports or private datasets in a report.

## Scope

In scope: code in this repository, including each integration's collectors, verifiers and command-line tools.
Issues in the hosted Kalanos MCP service are out of scope for this repository; send them
through the same private channel and they will be routed.

For what the integration trusts and what it does not verify, see
[docs/TRUST_BOUNDARIES.md](docs/TRUST_BOUNDARIES.md) and the
TRUST_BOUNDARIES.md in each integration's `docs/` directory.
