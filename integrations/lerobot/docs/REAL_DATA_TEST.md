# Real-data integration verification

**Result: passed.** On 12 November 2026 (UTC), the independent integration
collected live Kalanos MCP evidence, verified an exact public LeRobot source,
exported a pass-only selection, and loaded actual selected frames and video.
No grader CLI was imported and no policy training was run.

## Source and report

| Field | Recorded value |
| :--- | :--- |
| Dataset | [`lerobot/xarm_lift_medium_replay`](https://huggingface.co/datasets/lerobot/xarm_lift_medium_replay) |
| Source commit | `1da06eafab3a2e6ad52e36edfba6583bd6378d19` |
| Dataset format | v3.0, 800 episodes, 20,000 frames, 15 FPS |
| Report | [Published Hub assessment](https://hub.kalanos.ai/d/%40kalanos/hf/lerobot/xarm_lift_medium_replay) |
| Report ID | `0MVYOQRXB6E4C9564845047A1B` |
| Report revision | `5dfeab2ecd8fbc12dd941db208976f55` |
| Recorded scope | `vision-imitation-v1`, `default-decisions-v1`, full tier |
| Source instruction | “Pick up the cube and lift it.” |
| License declared by source | MIT |

This is a public robotics benchmark dataset, not a newly generated test fixture.
The test does not establish hardware capture, robot safety or task success.

## Results

| Check | Outcome |
| :--- | :--- |
| Live MCP collection | 8 pages, 800 unique episode records, one pinned report revision |
| Complete published decisions | 798 pass, 2 review, 0 blocked, 0 unknown |
| Pinned episode inventory | 800 unique indices, exactly 0–799, in the loader's required order |
| Source bytes | All 8 tracked files verified, totaling 18,930,570 bytes, including data and video |
| Pass-only export | 798 selected; indices 38 and 46 held out |
| Actual loader result | 798 episode IDs, each with 25 frames; exactly 19,950 selected frames |
| Selected observations | First/last frames of episodes 0, 400 and 799 decoded successfully |
| Video and action shape | Image `[3, 84, 84]`; action/state `[4]` |
| Network posture during loading | `HF_HUB_OFFLINE=1`; this is a Hub setting, not an OS-level network firewall |
| Runtime | LeRobot 0.7.0, Python 3.12, macOS, PyAV decoder |
| Unit suite | 89 tests passed; no external-service calls in unit tests |

The emitted source revision was preserved by the LeRobot loader. The exact
selection manifest SHA-256 was:

```text
0054fcec4f66a0449944e91fa879261353d15cfccefe7768f24b6e8841880c86
```

## What the exclusions show

| Source episode | Recorded decision | Initial selection outcome |
| :--- | :--- | :--- |
| 37 | pass | Included |
| 38 | review | Held out |
| 39 | pass | Included |
| 46 | review | Held out |

The review evidence concerns brightness versus the same-camera episode baseline.
The compact response retains unresolved reason references 44 and 45 with
`text: null` and `resolved: false`. The integration preserves that uncertainty.
It does not turn a `review` decision into `blocked`, nor treat severity alone as
permission to override the decision.

Published semantic labels are incomplete and absent on the two review episodes.
This test selects from the entire quality inventory, not an incomplete semantic
label subset. The source task instruction is distinct from generated labels.

## Retained evidence

All paths below are relative to `integrations/lerobot/examples/xarm-lift-demo/`:

- [`mcp-bundle.json`](../examples/xarm-lift-demo/mcp-bundle.json): complete report and eight selection pages.
- [`selection.json`](../examples/xarm-lift-demo/selection.json): exact exported selection manifest.
- [`smoke-result.json`](../examples/xarm-lift-demo/smoke-result.json): selected IDs, frame totals, sampled observation shapes and provenance.
- [`review-evidence.json`](../examples/xarm-lift-demo/review-evidence.json): full recorded evidence for the two review episodes, read at the same report revision.
- [`source-integrity.json`](../examples/xarm-lift-demo/source-integrity.json): per-file hashes, sizes and Git/LFS verification methods.

Raw dataset/video files and machine-specific loader-root paths are not included.
The snapshot is a record of this run, not an assertion that the report remains
current. The hosted MCP does not retain historical report versions for retrieval.

## What this does not prove

- No policy training, fixed-evaluation comparison or improvement in model quality
  was measured.
- Six frames were decoded. The test did not decode all 19,950 selected frames.
- Passing recorded checks does not establish task success, sufficiency, signal
  semantics, capture timing or absence of all defects.
- The adapter's normal verification covers index metadata; the full-file audit
  above was an additional check for this demonstration.
- Other platforms, LeRobot versions and v2 conversion workflows were not tested.
- A metadata warning about the source's `files_size_in_mb` field was emitted and
  ignored by LeRobot. It did not prevent the successful checks above.

## Reproduce

Follow the [LeRobot walkthrough](../README.md#walkthrough).
Use its captured-bundle option for the recorded source/revision, or fetch fresh
evidence and use the full source revision returned by that new bundle. Do not
combine those two modes or edit a captured manifest to a newer dataset commit.
