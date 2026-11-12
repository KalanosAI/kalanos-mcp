"""Fail-closed selection of local LeRobot episodes from saved MCP findings pages.

This is an offline consumer, not an MCP transport or report history store.
"""

import hashlib
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class SelectionError(ValueError):
    """A selection cannot be verified safely."""


class Boundary(BaseModel):
    """Validate known fields without discarding forward-compatible MCP metadata."""

    model_config = ConfigDict(extra="allow", strict=True)


class Reason(Boundary):
    """An evidence reference, with explicitly known or unresolved text."""

    reference: StrictInt | StrictStr | None = None
    text: StrictStr | None = None
    resolved: bool


class SelectionEpisode(Boundary):
    """One report decision; missing decisions are never passes."""

    episode_id: StrictStr = Field(min_length=1)
    source_episode_index: StrictInt | None = Field(default=None, ge=0)
    source_episode_index_status: StrictStr
    decision: Literal["pass", "review", "blocked", "unknown"]
    reasons: list[Reason]
    reasons_complete: bool = False


class Pagination(Boundary):
    """An offset page in an unfiltered findings sequence."""

    after: StrictInt = Field(ge=0)
    limit: StrictInt = Field(gt=0)
    total_episodes: StrictInt = Field(ge=0)
    next_after: StrictInt | None = Field(ge=0)
    truncated: bool = False


class DecisionCounts(Boundary):
    """Published inventory and decision totals, independently checked against pages."""

    total: StrictInt = Field(ge=0)
    pass_count: StrictInt = Field(ge=0)
    blocked: StrictInt = Field(ge=0)
    review: StrictInt = Field(ge=0)
    unknown: StrictInt = Field(ge=0)
    inventory_complete: bool


class FindingsPage(Boundary):
    """The provenance and selection fields required from each saved MCP result."""

    report_id: StrictStr = Field(min_length=1)
    report_revision: StrictStr = Field(min_length=1)
    source_ref: StrictStr = Field(min_length=1)
    dataset_revision: StrictStr = Field(min_length=1)
    source_dataset_revision: StrictStr | None = None
    inventory_complete: bool | None = None
    counts: DecisionCounts | None = None
    view: Literal["selection"] = "selection"
    episodes: list[SelectionEpisode]
    page: Pagination


def load_pages(paths: list[Path]) -> list[FindingsPage]:
    """Read raw structured results, MCP envelopes, or arrays of either.

    Parameters
    ----------
    paths : list[Path]
        Saved JSON files in pagination order.
    """
    pages = []
    reports = []
    for path in paths:
        value = json.loads(path.read_text())
        if isinstance(value, dict) and "pages" in value:
            report = value.get("report")
            if (
                not isinstance(report, dict)
                or "error" in report
                or report.get("isError")
            ):
                raise SelectionError(
                    "Bundle must contain a successful structured report"
                )
            reports.append(report)
            value = value["pages"]
            if not isinstance(value, list):
                raise SelectionError("Bundle pages must be a JSON array")
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, dict):
                raise SelectionError("Each saved result must be a JSON object")
            if item.get("isError") or "error" in item:
                raise SelectionError(
                    "MCP error response (possibly stale_revision); refetch all pages"
                )
            item = item.get("structuredContent", item)
            if not isinstance(item, dict) or "error" in item:
                raise SelectionError(
                    "MCP error or missing structured result; refetch all pages"
                )
            pages.append(FindingsPage.model_validate(item))
    if not pages:
        raise SelectionError("At least one findings page is required")
    for report in reports:
        for key in ("source_ref", "dataset_revision", "report_id", "report_revision"):
            if report.get(key) != getattr(pages[0], key):
                raise SelectionError(
                    "Bundle report provenance differs from findings pages"
                )
        if (
            report.get("source_dataset_revision") or report.get("dataset_revision")
        ) != (pages[0].source_dataset_revision or pages[0].dataset_revision):
            raise SelectionError("Bundle source commit differs from findings pages")
    return pages


def _git(root: Path, *args: str) -> bytes:
    """Run a read-only Git query against a local dataset checkout."""
    try:
        return subprocess.check_output(
            ["git", "--no-optional-locks", "-C", str(root), *args],
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SelectionError(
            "Dataset must be a local Git checkout with verifiable HF provenance"
        ) from exc


def _pinned_metadata(root: Path, source_ref: str, revision: str) -> dict[Path, bytes]:
    """Verify the HF origin, full commit, and consumed metadata bytes.

    Git LFS metadata is checked against the committed SHA-256 pointer. A directory
    name or caller-supplied revision assertion alone does not establish identity.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source_ref):
        raise SelectionError(
            "source_ref must be the exact HF org/dataset repository name"
        )
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise SelectionError(
            "An immutable full Git commit is required, not a branch or prefix"
        )
    if (
        Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        != root.resolve()
    ):
        raise SelectionError("Dataset root must be the Git checkout root")
    origin = _git(root, "remote", "get-url", "origin").decode().strip()
    expected = {
        f"https://huggingface.co/datasets/{source_ref}",
        f"git@hf.co:datasets/{source_ref}",
        f"ssh://git@hf.co/datasets/{source_ref}",
    }
    if origin.removesuffix(".git").rstrip("/") not in expected:
        raise SelectionError("Local Git origin does not match report source_ref")
    if _git(root, "rev-parse", "HEAD").decode().strip() != revision:
        raise SelectionError("Local Git HEAD does not match dataset_revision")
    files = [root / "meta/info.json"]
    # Verify all candidate index files before parsing the format declaration.
    if (root / "meta/episodes.jsonl").exists():
        files.append(root / "meta/episodes.jsonl")
    files.extend(sorted((root / "meta/episodes").rglob("*.parquet")))
    verified = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root.resolve()):
            raise SelectionError(f"Metadata escapes dataset root: {relative}")
        committed = _git(root, "show", f"{revision}:{relative}")
        actual = path.read_bytes()
        if committed.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
            match = re.search(rb"\noid sha256:([0-9a-f]{64})\nsize (\d+)\n?", committed)
            if (
                not match
                or hashlib.sha256(actual).hexdigest() != match[1].decode()
                or len(actual) != int(match[2])
            ):
                raise SelectionError(
                    f"Metadata does not match committed LFS object: {relative}"
                )
        elif actual != committed:
            raise SelectionError(f"Metadata differs from pinned commit: {relative}")
        verified[path] = actual
    return verified


def local_episode_indices(
    root: Path,
    source_ref: str,
    revision: str,
    *,
    require_lerobot_v3_order: bool = False,
) -> set[int]:
    """Read actual LeRobot v2/v3 index metadata from a pinned local checkout.

    Returns
    -------
    set[int]
        Unique nonnegative source indices, validated against the declared total.
        With require_lerobot_v3_order, additionally enforce the exact v3 metadata
        layout and positional ordering consumed by LeRobot 0.7.
    """
    files = _pinned_metadata(root, source_ref, revision)
    info = json.loads(files[root / "meta/info.json"])
    if not isinstance(info, dict):
        raise SelectionError("LeRobot info metadata must be a JSON object")
    version = info.get("codebase_version")
    if require_lerobot_v3_order and version != "v3.0":
        raise SelectionError(
            "This adapter targets LeRobot 0.7 and dataset v3.0. A v2 source must "
            "be converted and reassessed at its new revision, not silently relabelled."
        )
    if version in {"v2.0", "v2.1"}:
        index = root / "meta/episodes.jsonl"
        if index not in files:
            raise SelectionError(
                "LeRobot v2 requires meta/episodes.jsonl; count alone is not a mapping"
            )
        rows = [
            json.loads(line)
            for line in files[index].decode().splitlines()
            if line.strip()
        ]
    elif version == "v3.0":
        parquet = [p for p in files if p.suffix == ".parquet"]
        if require_lerobot_v3_order and any(
            len(p.relative_to(root / "meta/episodes").parts) != 2 for p in parquet
        ):
            raise SelectionError(
                "LeRobot episode metadata must use meta/episodes/<chunk>/<file>.parquet"
            )
        if not parquet:
            raise SelectionError("LeRobot v3 episode metadata is absent")
        rows = [
            row
            for p in parquet
            for row in pl.read_parquet(
                io.BytesIO(files[p]), columns=["episode_index"]
            ).to_dicts()
        ]
    else:
        raise SelectionError("Only LeRobot v2.0, v2.1, and v3.0 mappings are supported")
    if any(not isinstance(row, dict) for row in rows):
        raise SelectionError("LeRobot episode metadata must contain objects")
    values = [row.get("episode_index") for row in rows]
    if any(type(value) is not int or value < 0 for value in values):
        raise SelectionError("Invalid episode_index in local metadata")
    indices = set(values)
    if len(indices) != len(values):
        raise SelectionError("Duplicate episode_index in local metadata")
    if (
        type(info.get("total_episodes")) is not int
        or len(indices) != info["total_episodes"]
    ):
        raise SelectionError("Local metadata episode count is inconsistent")
    if require_lerobot_v3_order and values != list(range(len(indices))):
        raise SelectionError(
            "LeRobot 0.7 requires metadata rows in contiguous source-index order"
        )
    if version.startswith("v2") and indices != set(range(len(indices))):
        raise SelectionError("LeRobot v2 adapter requires contiguous source indices")
    return indices


def preview(pages: list[FindingsPage], root: Path) -> dict[str, Any]:
    """Verify page consistency and expose selection counts and coverage gaps.

    Parameters
    ----------
    pages : list[FindingsPage]
        Complete, ordered, unfiltered selection pages from one report revision.
    root : Path
        The source's pinned local LeRobot Git checkout.
    """
    if not pages:
        raise SelectionError("At least one findings page is required")
    first = pages[0]
    provenance = {
        key: getattr(first, key)
        for key in ("source_ref", "dataset_revision", "report_id", "report_revision")
    }
    resolved_revision = first.source_dataset_revision or first.dataset_revision
    if not re.fullmatch(
        r"[0-9a-f]{7,64}", first.dataset_revision
    ) or not resolved_revision.startswith(first.dataset_revision):
        raise SelectionError("Source commit and dataset revision disagree")
    indices = local_episode_indices(root, first.source_ref, resolved_revision)
    provenance["source_dataset_revision"] = resolved_revision
    episodes: list[SelectionEpisode] = []
    expected_after = 0
    seen_ids: set[str] = set()
    seen_indices: set[int] = set()
    declared_indices: set[int] = set()
    issues = []
    unmapped = []
    verified = []
    for position, page in enumerate(pages):
        if any(
            (
                getattr(page, key) or page.dataset_revision
                if key == "source_dataset_revision"
                else getattr(page, key)
            )
            != value
            for key, value in provenance.items()
        ):
            raise SelectionError(
                "Mixed source, dataset revision, report ID or report revision; "
                "refetch all pages"
            )
        if page.counts != first.counts:
            raise SelectionError("Report decision counts changed across pages")
        if (
            not page.inventory_complete
            or not page.counts
            or not page.counts.inventory_complete
        ):
            issues.append("Report inventory is incomplete or not established")
        paging = page.page
        if paging.total_episodes != first.page.total_episodes:
            raise SelectionError("Pagination total changed")
        if paging.after != expected_after or len(page.episodes) > paging.limit:
            raise SelectionError("Pagination gap, overlap, or invalid page size")
        expected_after += len(page.episodes)
        if paging.next_after is not None and paging.next_after != expected_after:
            raise SelectionError("Invalid pagination cursor")
        if paging.next_after is not None and not page.episodes:
            raise SelectionError("Pagination made no progress")
        if position < len(pages) - 1 and paging.next_after is None:
            raise SelectionError("Unexpected page after terminal cursor")
        if paging.truncated:
            issues.append("MCP marked the response truncated")
        for episode in page.episodes:
            if episode.episode_id in seen_ids:
                raise SelectionError("Duplicate report episode ID")
            seen_ids.add(episode.episode_id)
            index = episode.source_episode_index
            if index is not None:
                if index in declared_indices:
                    raise SelectionError("Duplicate declared source episode index")
                declared_indices.add(index)
            # The adapter's canonical episode ID is an independent mapping check.
            # Plain numeric IDs remain candidates only: membership is not identity.
            parts = episode.episode_id.split("::")
            expected_root = f"{first.source_ref.split('/')[-1]}@{resolved_revision}"
            qualified_root_matches = len(parts) == 1 or (
                len(parts) == 2 and parts[0] == expected_root
            )
            suffix = parts[-1]
            canonical = re.fullmatch(r"episode_(\d{6,})", suffix)
            inferred = int(canonical[1]) if canonical else None
            if inferred is not None and suffix != f"episode_{inferred:06d}":
                inferred = None
            if index is None and "::" not in episode.episode_id:
                index = inferred
            if (
                qualified_root_matches
                and index is not None
                and inferred == index
                and index in indices
            ):
                if index in seen_indices:
                    raise SelectionError("Duplicate source episode index")
                seen_indices.add(index)
                verified.append(
                    {
                        "episode_id": episode.episode_id,
                        "source_episode_index": index,
                        "decision": episode.decision,
                        "reasons": [r.model_dump() for r in episode.reasons],
                        "mapping_verification": "pinned_lerobot_metadata",
                        "reasons_complete": episode.reasons_complete,
                    }
                )
            else:
                unmapped.append(episode.episode_id)
            episodes.append(episode)
    if (
        pages[-1].page.next_after is not None
        or expected_after != first.page.total_episodes
    ):
        issues.append("Incomplete MCP pagination; fetch all unfiltered pages")
    gaps = sorted(indices - seen_indices)
    if gaps:
        issues.append("Local source episodes are absent or unmapped in the report")
    if unmapped:
        issues.append("Report episode IDs could not be independently mapped")
    counts = {
        decision: sum(e.decision == decision for e in episodes)
        for decision in ("pass", "review", "blocked", "unknown")
    }
    if first.counts:
        reported = first.counts
        expected_counts = {
            "pass": reported.pass_count,
            "review": reported.review,
            "blocked": reported.blocked,
            "unknown": reported.unknown,
        }
        if reported.total != sum(expected_counts.values()):
            raise SelectionError("Published decision counts do not sum to total")
        if (
            reported.total != len(indices)
            or reported.total != first.page.total_episodes
        ):
            issues.append(
                "Published decision inventory does not match the local source"
            )
        if expected_after == first.page.total_episodes and counts != expected_counts:
            raise SelectionError(
                "Published decision counts disagree with findings pages"
            )
    selected = [episode for episode in verified if episode["decision"] == "pass"]
    return {
        "schema_version": "kalanos.selection.v1",
        **provenance,
        "policy": {
            "include_decisions": ["pass"],
            "exclude_decisions": ["blocked", "review", "unknown"],
            "require_complete_report": True,
            "require_verified_mapping": True,
            "overrides": [],
        },
        "counts": {
            "selected": len(selected),
            "excluded": len(episodes) - len(selected),
            "review": counts["review"],
            "unknown": counts["unknown"],
            "blocked": counts["blocked"],
            "unmapped": len(unmapped),
        },
        "coverage": {
            "local_episodes": len(indices),
            "report_episodes": len(episodes),
            "expected_report_episodes": first.page.total_episodes,
            "missing_source_indices": gaps,
            "unmapped_episode_ids": unmapped,
        },
        "exportable": not issues,
        "issues": issues,
        "episodes": selected,
    }


def export_manifest(result: dict[str, Any], output: Path) -> None:
    """Write a new manifest only when every safety check passed.

    Existing output files are never overwritten. The schema version describes
    this file format; report_revision is a consistency token, not report history.
    """
    if not result["exportable"]:
        raise SelectionError("Export refused: " + "; ".join(result["issues"]))
    with output.open("x") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
