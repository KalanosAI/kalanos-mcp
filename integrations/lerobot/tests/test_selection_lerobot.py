"""LeRobot receives exactly the pinned, explicitly passing episode subset."""

import copy
import hashlib
import json
import subprocess

import polars as pl
import pytest
from pydantic import ValidationError
from test_selection import commit, payload
from typer.testing import CliRunner

from kalanos_mcp_lerobot.cli import app
from kalanos_mcp_lerobot.selection import (
    FindingsPage,
    SelectionError,
    export_manifest,
    preview,
)
from kalanos_mcp_lerobot.selection_lerobot import lerobot_input


@pytest.fixture
def selected(tmp_path):
    """Build a genuine local v3 Git source and a mixed-decision selection."""
    root = tmp_path / "data"
    meta = root / "meta"
    (meta / "episodes/chunk-000").mkdir(parents=True)
    (meta / "info.json").write_text(
        json.dumps({"codebase_version": "v3.0", "total_episodes": 4})
    )
    pl.DataFrame({"episode_index": [0, 1, 2, 3]}).write_parquet(
        meta / "episodes/chunk-000/file-000.parquet"
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "remote",
            "add",
            "origin",
            "https://huggingface.co/datasets/org/data",
        ],
        check=True,
    )
    revision = commit(root)
    value = payload(revision)
    value["source_dataset_revision"] = revision
    manifest = preview([FindingsPage.model_validate(value)], root)
    path = tmp_path / "selection.json"
    export_manifest(manifest, path)
    return root, path, manifest


def test_handoff_uses_pinned_identity_and_pass_only(selected):
    """No display position, branch name, or nonpassing episode reaches LeRobot."""
    root, path, manifest = selected
    result = lerobot_input(path, root)
    assert result["dataset"] == {
        "repo_id": "org/data",
        "root": str(root.resolve()),
        "revision": manifest["source_dataset_revision"],
        "episodes": [0],
    }
    assert (
        result["selection"]["manifest_sha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert result["selection"]["report_revision"] == manifest["report_revision"]
    assert result["selection"]["counts"]["excluded"] == 3


def test_qualified_ids_supported(selected):
    """The exact repo basename and full commit may qualify an episode ID."""
    root, path, manifest = selected
    manifest["episodes"][0]["episode_id"] = (
        f"data@{manifest['source_dataset_revision']}::episode_000000"
    )
    path.write_text(json.dumps(manifest))
    assert lerobot_input(path, root)["dataset"]["episodes"] == [0]


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "review",
        "unknown",
        "blocked",
        "duplicate",
        "wrong_id",
        "wrong_source",
        "bad_counts",
        "bad_coverage",
        "unknown_schema",
        "not_exportable",
        "override",
        "branch",
        "short_commit",
        "missing_inventory",
        "unmapped",
        "issue",
        "bool_index",
        "float_index",
        "policy",
        "mapping",
        "wrong_revision",
        "wrong_origin",
        "changed_meta",
    ],
)
def test_invalid_manifest_or_source_refused(selected, mutation):
    """Invalid or edited inputs fail closed instead of selecting all episodes."""
    root, path, original = selected
    value = copy.deepcopy(original)
    episode = value["episodes"][0]
    if mutation == "empty":
        value["episodes"] = []
        value["counts"].update(selected=0, excluded=4, unknown=2)
    elif mutation in {"review", "unknown", "blocked"}:
        episode["decision"] = mutation
    elif mutation == "duplicate":
        value["episodes"].append(copy.deepcopy(episode))
        value["counts"].update(selected=2, excluded=2, unknown=0)
    elif mutation == "wrong_id":
        episode["episode_id"] = "episode_000001"
    elif mutation == "wrong_source":
        episode["episode_id"] = (
            f"other@{value['source_dataset_revision']}::episode_000000"
        )
    elif mutation == "bad_counts":
        value["counts"]["selected"] = 2
    elif mutation == "bad_coverage":
        value["coverage"]["local_episodes"] = 3
    elif mutation == "unknown_schema":
        value["schema_version"] = "future"
    elif mutation == "not_exportable":
        value["exportable"] = False
    elif mutation == "override":
        value["policy"]["overrides"] = [{"include": 1}]
    elif mutation in {"branch", "short_commit"}:
        value["source_dataset_revision"] = "main" if mutation == "branch" else "abcdef0"
    elif mutation == "missing_inventory":
        value["coverage"]["missing_source_indices"] = [2]
    elif mutation == "unmapped":
        value["counts"]["unmapped"] = 1
    elif mutation == "issue":
        value["issues"] = ["Incomplete"]
    elif mutation == "bool_index":
        episode["source_episode_index"] = False
    elif mutation == "float_index":
        episode["source_episode_index"] = 0.0
    elif mutation == "policy":
        value["policy"]["include_decisions"] = ["pass", "review"]
    elif mutation == "mapping":
        episode["mapping_verification"] = "candidate_requires_verification"
    elif mutation == "wrong_revision":
        value["source_dataset_revision"] = value["dataset_revision"] = "a" * 40
    elif mutation == "wrong_origin":
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "remote",
                "set-url",
                "origin",
                "https://huggingface.co/datasets/other/data",
            ],
            check=True,
        )
    elif mutation == "changed_meta":
        (root / "meta/info.json").write_text("{}")
    path.write_text(json.dumps(value))
    with pytest.raises((SelectionError, ValidationError)):
        lerobot_input(path, root)


def test_cli_stdout_and_exclusive_output(selected, tmp_path):
    """CLI emits JSON, refuses overwrites, and has no LeRobot dependency."""
    root, path, _ = selected
    runner = CliRunner()
    args = ["handoff", str(path), "--dataset", str(root)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["dataset"]["episodes"] == [0]
    out = tmp_path / "loader.json"
    assert runner.invoke(app, [*args, "-o", str(out)]).exit_code == 0
    saved = out.read_bytes()
    assert runner.invoke(app, [*args, "-o", str(out)]).exit_code == 2
    assert out.read_bytes() == saved


def test_v2_requires_new_revision_and_reassessment(selected):
    """The adapter does not silently convert a v2 selection for a v3 loader."""
    root, path, manifest = selected
    (root / "meta/info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 4})
    )
    (root / "meta/episodes.jsonl").write_text(
        "".join(json.dumps({"episode_index": i}) + "\n" for i in range(4))
    )
    revision = commit(root)
    manifest["dataset_revision"] = manifest["source_dataset_revision"] = revision
    path.write_text(json.dumps(manifest))
    with pytest.raises(SelectionError, match="converted and reassessed"):
        lerobot_input(path, root)


@pytest.mark.parametrize("indices", [[0, 1, 2, 4], [1, 0, 2, 3]])
def test_v3_loader_order_is_required(selected, indices):
    """The loader indexes episode metadata by row, not by a searched ID column."""
    root, path, manifest = selected
    pl.DataFrame({"episode_index": indices}).write_parquet(
        root / "meta/episodes/chunk-000/file-000.parquet"
    )
    revision = commit(root)
    manifest["dataset_revision"] = manifest["source_dataset_revision"] = revision
    path.write_text(json.dumps(manifest))
    with pytest.raises(SelectionError, match="contiguous source-index order"):
        lerobot_input(path, root)


def test_v3_loader_shard_layout_is_required(selected):
    """Files outside the loader's one-chunk-deep glob must not verify a mapping."""
    root, path, manifest = selected
    shard = root / "meta/episodes/chunk-000/file-000.parquet"
    nested = shard.parent / "extra"
    nested.mkdir()
    shard.rename(nested / shard.name)
    revision = commit(root)
    manifest["dataset_revision"] = manifest["source_dataset_revision"] = revision
    path.write_text(json.dumps(manifest))
    with pytest.raises(SelectionError, match="meta/episodes/<chunk>/<file>"):
        lerobot_input(path, root)


@pytest.mark.parametrize(
    "field", ["exportable", "require_complete_report", "require_verified_mapping"]
)
def test_boolean_flags_do_not_accept_numbers(selected, field):
    """JSON number 1 is not explicit boolean confirmation of selection checks."""
    root, path, manifest = selected
    target = manifest if field == "exportable" else manifest["policy"]
    target[field] = 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError):
        lerobot_input(path, root)
