# Captured xarm lift example

This directory records the 12 November 2026 UTC test of the public
`lerobot/xarm_lift_medium_replay` dataset. It contains public assessment evidence
and results, not the dataset's raw data or video.

- `mcp-bundle.json`: all 800 episode decisions, collected from live MCP in eight pages.
- `selection.json`: 798 verified passing source episodes, with the exact pinned revision.
- `smoke-result.json`: actual LeRobot load results and six decoded observation samples.
- `review-evidence.json`: full evidence for review episodes 38 and 46.
- `source-integrity.json`: all eight downloaded source files checked against committed Git/LFS content.

See the [test report](../../docs/REAL_DATA_TEST.md) for provenance and limits,
and the [walkthrough](../../README.md#walkthrough) to replay this captured bundle
or collect fresh evidence. Never combine pages from the two modes.
