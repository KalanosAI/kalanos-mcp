"""Validate a saved selection and hand it to LeRobot's existing dataset loader.

This module does not import LeRobot, download data, or start a training job.
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr

from kalanos_mcp_lerobot.selection import (
    Boundary,
    Reason,
    SelectionError,
    local_episode_indices,
)


class SelectionPolicy(Boundary):
    """The only selection policy supported by the first adapter."""

    include_decisions: list[StrictStr]
    exclude_decisions: list[StrictStr]
    require_complete_report: StrictBool
    require_verified_mapping: StrictBool
    overrides: list[Any]


class SelectedEpisode(Boundary):
    """An explicitly passing episode with a verified source index."""

    episode_id: StrictStr
    source_episode_index: StrictInt = Field(ge=0)
    decision: Literal["pass"]
    reasons: list[Reason]
    mapping_verification: Literal["pinned_lerobot_metadata"]
    reasons_complete: bool


class SelectionCounts(Boundary):
    """Selection totals preserved alongside the loader input."""

    selected: StrictInt = Field(ge=0)
    excluded: StrictInt = Field(ge=0)
    review: StrictInt = Field(ge=0)
    unknown: StrictInt = Field(ge=0)
    blocked: StrictInt = Field(ge=0)
    unmapped: StrictInt = Field(ge=0, le=0)


class SelectionCoverage(Boundary):
    """Complete episode mapping, not a claim that every metric passed."""

    local_episodes: StrictInt = Field(ge=0)
    report_episodes: StrictInt = Field(ge=0)
    expected_report_episodes: StrictInt = Field(ge=0)
    missing_source_indices: list[StrictInt]
    unmapped_episode_ids: list[StrictStr]


class SelectionManifest(Boundary):
    """Validated input boundary for the existing selection.v1 format."""

    schema_version: Literal["kalanos.selection.v1"]
    source_ref: StrictStr
    dataset_revision: StrictStr
    source_dataset_revision: StrictStr
    report_id: StrictStr = Field(min_length=1)
    report_revision: StrictStr = Field(min_length=1)
    policy: SelectionPolicy
    counts: SelectionCounts
    coverage: SelectionCoverage
    exportable: StrictBool
    issues: list[StrictStr]
    episodes: list[SelectedEpisode]


def lerobot_input(manifest_path: Path, root: Path) -> dict[str, Any]:
    """Build LeRobot dataset arguments after rechecking the saved selection.

    Parameters
    ----------
    manifest_path : Path
        A trusted, previously exported selection.v1 JSON file.
    root : Path
        The same immutable local HF Git checkout used for selection export.

    Returns
    -------
    dict[str, Any]
        A loader-ready ``dataset`` object and selection provenance. Its dataset
        fields can also populate LeRobot's training DatasetConfig.

    Notes
    -----
    Metadata identity is verified again. This is not a signature check, a full
    data/video integrity check, or proof that the report is still current.
    """
    raw = manifest_path.read_bytes()
    manifest = SelectionManifest.model_validate_json(raw)
    policy = manifest.policy
    if (
        policy.include_decisions != ["pass"]
        or policy.exclude_decisions != ["blocked", "review", "unknown"]
        or policy.overrides
        or not policy.require_complete_report
        or not policy.require_verified_mapping
    ):
        raise SelectionError("LeRobot adapter only accepts the pass-only policy")
    if not manifest.exportable:
        raise SelectionError("Selection is not exportable")
    coverage = manifest.coverage
    if (
        manifest.issues
        or coverage.missing_source_indices
        or coverage.unmapped_episode_ids
    ):
        raise SelectionError(
            "Selection contains unresolved mapping or inventory issues"
        )
    revision = manifest.source_dataset_revision
    if not re.fullmatch(
        r"[0-9a-f]{7,64}", manifest.dataset_revision
    ) or not revision.startswith(manifest.dataset_revision):
        raise SelectionError("Source commit and dataset revision disagree")
    indices = local_episode_indices(
        root, manifest.source_ref, revision, require_lerobot_v3_order=True
    )
    count = manifest.counts
    total = len(indices)
    if (
        count.selected != len(manifest.episodes)
        or count.selected + count.excluded != total
        or count.excluded != count.review + count.unknown + count.blocked
        or coverage.local_episodes != total
        or coverage.report_episodes != total
        or coverage.expected_report_episodes != total
    ):
        raise SelectionError(
            "Selection counts or coverage disagree with source metadata"
        )
    if not manifest.episodes:
        raise SelectionError("Empty selection cannot be handed to a training loader")
    selected = []
    seen_ids = set()
    source = f"{manifest.source_ref.split('/')[-1]}@{revision}"
    for episode in manifest.episodes:
        index = episode.source_episode_index
        canonical = f"episode_{index:06d}"
        if (
            index not in indices
            or index in selected
            or episode.episode_id in seen_ids
            or episode.episode_id not in {canonical, f"{source}::{canonical}"}
        ):
            raise SelectionError(
                "Selected episode identity does not match pinned metadata"
            )
        selected.append(index)
        seen_ids.add(episode.episode_id)
    return {
        "schema_version": "kalanos.lerobot-input.v1",
        "dataset": {
            "repo_id": manifest.source_ref,
            "root": str(root.resolve()),
            "revision": revision,
            "episodes": selected,
        },
        "selection": {
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "report_id": manifest.report_id,
            "report_revision": manifest.report_revision,
            "dataset_revision": manifest.dataset_revision,
            "source_dataset_revision": revision,
            "counts": count.model_dump(),
            "policy": policy.model_dump(),
        },
        "compatibility": {"tested_lerobot_version": "0.7.0", "dataset_format": "v3.0"},
        "interpretation": (
            "Pass means passed the recorded checks, not task success or training "
            "quality. Only episode-index metadata was reverified. The manifest "
            "is trusted input, not signed evidence; report currentness was not checked."
        ),
    }
