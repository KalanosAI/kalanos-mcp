# Kalanos MCP → LeRobot

**Build a reproducible episode selection from published evidence, then use
LeRobot's existing loader.**

This self-contained Python integration reads the public Kalanos MCP service,
checks every selection page, verifies the source against a local Hugging Face
Git checkout, and exports loader-ready arguments. You do not need the Kalanos
grader CLI, a separate Node helper, or another MCP server.

## What you get

| Command | What it does | Network behavior |
| :--- | :--- | :--- |
| `fetch` | Save a complete, revision-consistent report/episode bundle | Reads the chosen HTTPS MCP endpoint |
| `preview` | Show counts, policy, provenance and mapping gaps | Local only |
| `export` | Write the verified pass-only selection manifest | Local only |
| `handoff` | Recheck the manifest and emit LeRobot dataset arguments | Local only |
| `smoke` | Check loaded IDs/frame counts and decode sampled observations | Hugging Face Hub access disabled; local caches may be written |

No command starts grading, policy training, a tracker run, or an upload.

## Installation

Tested with Python **3.12**, LeRobot **0.7.0**, dataset format **v3.0**, and macOS.
The shell examples below use Bash. The Python package requires Python 3.12 or
newer, but other Python/platform combinations have not been load-tested here.

From this directory:

```bash
# Complete example, including LeRobot's dataset and PyAV dependencies:
uv sync --frozen --extra lerobot
source .venv/bin/activate

# Confirm the independent CLI:
kalanos-lerobot --help
```

For evidence collection and export only, omit `--extra lerobot`. The package is
installed from this checkout and is not yet a PyPI release. When using `uv run`
instead of activating the environment, include `--extra lerobot` for loader work.

## Walkthrough

Use fresh output and dataset directories. Output files are created exclusively;
reruns will not silently overwrite earlier evidence.

### 1. Collect the current published report

```bash
export RUN_DIR="$PWD/artifacts/xarm-demo"
export DATASET_ROOT="$PWD/data/xarm_lift_medium_replay"
mkdir -p "$RUN_DIR"

kalanos-lerobot fetch lerobot/xarm_lift_medium_replay \
  -o "$RUN_DIR/mcp-bundle.json"
```

The client pins the report revision, follows the server's exact `next_after`
cursors, checks source identity on every page, and performs a final current-token
check. If the report changes, it discards that attempt and restarts once. A
failed fetch does not save a partial bundle. Initialization and collection have
a ten-minute deadline.

To replay the captured test rather than fetch a newer report, use this **instead
of** the `fetch` command:

```bash
cp examples/xarm-lift-demo/mcp-bundle.json "$RUN_DIR/mcp-bundle.json"
```

The captured source commit is
`1da06eafab3a2e6ad52e36edfba6583bd6378d19`. A live report may reference a later
commit or different decisions, so read the revision from the actual bundle.

### 2. Materialize that exact dataset revision

The example dataset is public and approximately **18.9 MB**, including video.
These commands explicitly download it. The integration itself does not clone
repositories or choose download destinations.

```bash
export DATASET_REVISION="$(python -c \
  'import json,os; print(json.load(open(os.environ["RUN_DIR"]+"/mcp-bundle.json"))["report"]["source_dataset_revision"])')"

GIT_LFS_SKIP_SMUDGE=1 git clone --no-checkout \
  https://huggingface.co/datasets/lerobot/xarm_lift_medium_replay "$DATASET_ROOT"
GIT_LFS_SKIP_SMUDGE=1 git -C "$DATASET_ROOT" checkout --detach "$DATASET_REVISION"

python - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="lerobot/xarm_lift_medium_replay",
    repo_type="dataset",
    revision=os.environ["DATASET_REVISION"],
    local_dir=os.environ["DATASET_ROOT"],
    token=False,  # This public example needs no account or token.
)
PY
```

The Git checkout supplies committed provenance. The Hub download hydrates the
LFS-backed parquet/video files at the same revision. Keep this checkout unchanged
while preparing and loading the selection. Copying a source name or revision
into an unrelated directory does not pass verification.

### 3. Preview and export

```bash
kalanos-lerobot preview "$RUN_DIR/mcp-bundle.json" --dataset "$DATASET_ROOT"
kalanos-lerobot export "$RUN_DIR/mcp-bundle.json" --dataset "$DATASET_ROOT" \
  -o "$RUN_DIR/selection.json"
```

For the captured report, the counts are:

```json
{
  "selected": 798,
  "excluded": 2,
  "review": 2,
  "unknown": 0,
  "blocked": 0,
  "unmapped": 0
}
```

Use `preview --full` to include every selected episode record. The normal preview
keeps the output focused on counts, provenance, policy and gaps.

The policy is explicit: include `pass`; hold out `review`, `blocked`, and
`unknown`. Review episodes **38 and 46** remain review decisions. The complete
MCP bundle retains excluded records and unresolved reason references; missing
reason text is not invented.

### 4. Prepare the LeRobot handoff

```bash
kalanos-lerobot handoff "$RUN_DIR/selection.json" --dataset "$DATASET_ROOT" \
  -o "$RUN_DIR/lerobot-input.json"
```

The handoff contains `dataset` and `selection` objects. Only the `dataset` object
is passed to LeRobot. It includes the exact `repo_id`, local `root`, full commit
`revision`, and verified source `episodes` list. Report identity, policy, counts
and the exact manifest file's SHA-256 stay alongside it for experiment provenance.

```python
import json
import os
from lerobot.datasets.lerobot_dataset import LeRobotDataset

with open(os.environ["RUN_DIR"] + "/lerobot-input.json") as handle:
    handoff = json.load(handle)

dataset = LeRobotDataset(**handoff["dataset"], video_backend="pyav")
```

Direct LeRobot loading has LeRobot's normal behavior, including downloads if
files are missing. Use the offline `smoke` command below for a bounded local
verification. On another machine, recreate the pinned checkout and regenerate
the handoff there; its local root is not portable.

### 5. Check actual loading, including video

```bash
HF_HUB_OFFLINE=1 kalanos-lerobot smoke "$RUN_DIR/selection.json" \
  --dataset "$DATASET_ROOT" -o "$RUN_DIR/smoke-result.json"
```

The smoke check revalidates the selection, loads the selected dataset, compares
**every loaded source episode ID and per-episode frame count** with the selected
metadata, and decodes the first/last frames of three spread-out selected episodes.
Use `--sample-episodes N` for 1–20 sampled episodes.

Recorded result:

```text
798 selected episodes
19,950 frames loaded
Excluded source indices: 38, 46
6 frames decoded from episodes 0, 400, 799
Video observation shape: [3, 84, 84]
```

`HF_HUB_OFFLINE=1` disables Hugging Face Hub access. It is not an operating-system
network sandbox. The command may write local library caches. Set `HF_HOME`,
`HF_LEROBOT_HOME`, `XDG_CACHE_HOME` and temporary directories when working in a
restricted environment. No policy training or evaluation is performed.

## Why these checks matter

- `episode.key`, page offsets and presentation positions are not source indices.
  The mapping is verified against committed LeRobot metadata.
- A branch name or short SHA is insufficient. The full published source commit
  must match local Git `HEAD`, origin and consumed metadata bytes.
- Incomplete pages, duplicate IDs, mismatched counts or missing source episodes
  refuse export rather than quietly selecting whatever arrived.
- LeRobot 0.7 uses positional v3 metadata lookup. The handoff verifies the exact
  shard layout and contiguous source-index row order it expects.
- Empty selections, unverified mappings and policy overrides are refused.
- Converting a v2 dataset changes its source identity. Convert and reassess at
  the new revision rather than relabeling an old manifest.

## The example's meaning and limits

The two excluded episodes have recorded `review` decisions for brightness versus
the same-camera episode baseline. They are not established training failures.
Their reason references remain unresolved in the compact view; the captured
[full evidence](examples/xarm-lift-demo/review-evidence.json) is retained separately.

All 800 episodes share the source task instruction, but published semantic labels
cover only part of the dataset and are absent for the two review episodes. This
demo uses the full unfiltered quality inventory. It does not claim a semantic
label filter covers every episode or certifies task success.

The source README includes an older v2 snippet; the actual pinned `meta/info.json`
and data layout are v3.0. Actual metadata governs this integration.

The adapter normally rechecks index metadata only. The recorded real-data test
also verified all eight downloaded files against committed Git bytes or LFS
SHA-256/size. A saved manifest is trusted input, not signed evidence. Its hash
identifies bytes, not authenticity. Report currentness is checked at collection,
not continuously during later training.

## Optional authentication

Public collection works without an account. If you have a Hub API key, set
`KALANOS_API_KEY` in your environment or approved secret store. Never commit it.
The client sends it only to the chosen HTTPS endpoint and does not follow
cross-origin redirects; the official MCP SDK may follow same-origin redirects.
`--endpoint` is an operator-controlled setting; use a trusted service.

## From a load check to a training experiment

Copy the handoff's four `dataset` fields into a complete LeRobot training
configuration, retaining the intended model and other dataset settings. For this
first adapter, use non-streaming loading and do not add a second episode filter.

Choose a policy/model, fixed evaluation set, seeds and compute budget before
starting a full-versus-selected comparison. Preserve the original manifest and
handoff with the run. Trackio/W&B logging is a planned next integration, not a
side effect of these commands.

## Troubleshooting

| Message or symptom | What to do |
| :--- | :--- |
| `stale_revision` after the allowed restart | Collect again later into a fresh output path; do not combine old and new pages |
| Local HEAD/origin mismatch | Materialize the exact repository and full commit published in the bundle |
| LFS metadata mismatch | Hydrate the pinned files; do not treat pointer text as parquet content |
| Inventory or mapping gap | Inspect the preview and source metadata; do not substitute presentation positions |
| v2 format rejected by handoff | Convert and reassess the converted revision, or use a separately validated older integration |
| Offline smoke lacks a file | Finish materializing the pinned source before retrying; the smoke check does not download it |
| Existing output file | Choose a fresh output path to preserve the earlier result |
| LeRobot ignores `files_size_in_mb` | This occurred in the recorded example; loading and sampled decoding still passed |

## Test the integration

```bash
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
```

The test suite uses local fixtures and transport/loader doubles. The separate
[real-data report](docs/REAL_DATA_TEST.md) records the live MCP and actual
LeRobot/video checks.

## Current boundaries

- The end-to-end adapter targets LeRobot **0.7.0** and dataset format **v3.0**.
- The CLI verifies local HF Git provenance and the consumed episode metadata.
  It does not continuously rehash every data/video file or authenticate a saved
  manifest's publisher. The recorded demo separately verified every source file.
- The initial policy includes only explicit `pass` decisions. `review`, `blocked`
  and `unknown` are held out separately. Human overrides are not implemented.
- A saved report revision is not a report-history service. Refresh evidence when
  currentness matters. Keep the pinned checkout unchanged while loading.
- No training, tracker upload, dataset publication or deployment is launched.

See [docs/TRUST_BOUNDARIES.md](docs/TRUST_BOUNDARIES.md) for this integration's
network, credential and local-file boundaries.
