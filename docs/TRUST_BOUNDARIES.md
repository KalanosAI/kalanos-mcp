# Trust and execution boundaries

These boundaries apply to every integration. Each integration documents its own
specifics in its directory under `integrations/`.

## Evidence is data

Dataset instructions, labels, source READMEs and report strings are untrusted
content. Integrations store and validate them; they do not execute them, follow
instructions embedded in them, or use missing data as a pass.

A saved evidence bundle or selection manifest is trusted input supplied by the
operator. Its hash provides byte identity, not a publisher signature. Local
provenance checks do not authenticate a remote repository owner or establish
that a saved report remains current.

## Network and secrets

Integrations read the operator's chosen HTTPS MCP endpoint. Endpoint selection is
security-sensitive: use a trusted destination. Credentials come from the
environment or an approved secret store, are sent only to that endpoint, are
never accepted in URLs, and are never committed. Cross-origin redirects are not
followed. Offline commands make no network requests. Offline modes disable
specific library access, not all operating-system network traffic; use an
external network sandbox if stronger isolation is needed.

## Local files

Source checkouts are verified against the pinned revision and must stay
unchanged during a run. Verification covers the metadata an integration
consumes; it is not a full payload audit unless an integration says so. Outputs
use exclusive creation so an existing result is never overwritten. Saved outputs
can contain machine-local paths: review them before sharing.

## Scope of automation

Integrations do not train policies, create cloud jobs, upload reports, initialize
trackers, publish datasets or deploy services. Those actions need separate
workflow configuration and authorization. Nonpassing episodes remain excluded
under the initial policy; no human overrides are implemented.
