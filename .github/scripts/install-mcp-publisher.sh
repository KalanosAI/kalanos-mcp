#!/usr/bin/env bash
# Install the pinned publisher for GitHub-hosted Linux x64 runners.
set -euo pipefail

version=v1.8.16
archive=mcp-publisher_linux_amd64.tar.gz
sha256=6e2f799550cf843c6fd3350498d56cc49be3dc0af1e6237eb0e6435c7a9d5c05
: "${RUNNER_TEMP:?Run this installer on the GitHub Actions runner}"

scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT

cd "$scratch"
curl --fail --silent --show-error --location --retry 3 --max-time 120 \
  --output "$archive" \
  "https://github.com/modelcontextprotocol/registry/releases/download/$version/$archive"
printf '%s  %s\n' "$sha256" "$archive" | sha256sum --check --strict -
tar -xzf "$archive" mcp-publisher
install -m 0755 mcp-publisher "$RUNNER_TEMP/mcp-publisher"
