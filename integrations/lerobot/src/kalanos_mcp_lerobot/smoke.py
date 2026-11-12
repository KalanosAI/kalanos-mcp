"""Offline validation of a verified selection using the actual LeRobot loader."""

import importlib.metadata
import os
from collections import Counter
from pathlib import Path
from typing import Any

from kalanos_mcp_lerobot.selection import SelectionError
from kalanos_mcp_lerobot.selection_lerobot import lerobot_input


def smoke_selection(
    manifest: Path, root: Path, *, sample_episodes: int = 3
) -> dict[str, Any]:
    """Check all loaded episode IDs/counts and decode sampled selected frames.

    This reads real frames but does not train, evaluate a policy, or upload data.
    Hugging Face must be offline before its modules are imported.
    """
    if type(sample_episodes) is not int or not 1 <= sample_episodes <= 20:
        raise SelectionError("sample_episodes must be an integer between 1 and 20")
    handoff = lerobot_input(manifest, root)
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        from huggingface_hub import constants
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError as exc:
        raise SelectionError(
            "Install this package with its lerobot extra before running smoke"
        ) from exc
    if not constants.HF_HUB_OFFLINE:
        raise SelectionError("Restart in a fresh process with HF_HUB_OFFLINE=1")
    version = importlib.metadata.version("lerobot")
    if version != "0.7.0":
        raise SelectionError(
            f"This smoke check is validated with LeRobot 0.7.0, not {version}"
        )
    dataset = LeRobotDataset(**handoff["dataset"], video_backend="pyav")
    selected = handoff["dataset"]["episodes"]
    values = [int(i) for i in dataset.hf_dataset["episode_index"]]
    observed = Counter(values)
    expected = {i: int(dataset.meta.episodes[i]["length"]) for i in selected}
    if dict(observed) != expected:
        raise SelectionError(
            "Loaded episode IDs or frame counts differ from selected metadata"
        )
    if not values or dataset.revision != handoff["dataset"]["revision"]:
        raise SelectionError(
            "Loaded source revision differs or the selection has no frames"
        )
    count = min(sample_episodes, len(selected))
    chosen = [
        selected[round(i * (len(selected) - 1) / max(count - 1, 1))]
        for i in range(count)
    ]
    first, last = {}, {}
    for pos, index in enumerate(values):
        first.setdefault(index, pos)
        last[index] = pos
    samples = []
    for index in chosen:
        for pos in sorted({first[index], last[index]}):
            row = dataset[pos]
            if int(row["episode_index"]) != index:
                raise SelectionError("Decoded sample has an unexpected episode index")
            samples.append(
                {
                    "episode_index": index,
                    "selected_frame_offset": pos,
                    "task": row.get("task"),
                    "feature_shapes": {
                        key: list(value.shape)
                        for key, value in row.items()
                        if hasattr(value, "shape")
                    },
                }
            )
    return {
        "status": "passed",
        "lerobot_version": version,
        "source_ref": handoff["dataset"]["repo_id"],
        "source_dataset_revision": dataset.revision,
        "report_id": handoff["selection"]["report_id"],
        "report_revision": handoff["selection"]["report_revision"],
        "manifest_sha256": handoff["selection"]["manifest_sha256"],
        "source_episodes": int(dataset.meta.total_episodes),
        "selected_episodes": len(selected),
        "excluded_source_indices": sorted(
            set(range(dataset.meta.total_episodes)) - set(selected)
        ),
        "source_frames": int(dataset.meta.total_frames),
        "loaded_frames": len(values),
        "selected_source_indices": selected,
        "sampled_frames": samples,
        "offline": True,
        "limits": [
            "No policy training or evaluation was run",
            "Only sampled frames were decoded",
            "Pass is scoped to recorded checks, not task success",
        ],
    }
