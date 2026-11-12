"""Selection must prove page completeness, provenance, and LeRobot identity."""

import copy
import json
import subprocess

import polars as pl
import pytest
from typer.testing import CliRunner

from kalanos_mcp_lerobot.cli import app
from kalanos_mcp_lerobot.selection import (
    FindingsPage,
    SelectionError,
    export_manifest,
    load_pages,
    local_episode_indices,
    preview,
)


@pytest.fixture
def source(tmp_path):
    """Create a real pinned source checkout, without network access."""
    root = tmp_path / "dataset"
    (root / "meta").mkdir(parents=True)
    (root / "meta/info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 4})
    )
    (root / "meta/episodes.jsonl").write_text(
        "".join(json.dumps({"episode_index": i}) + "\n" for i in range(4))
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
    return root, revision


def commit(root):
    """Commit fixture metadata using only command-scoped identity settings."""
    subprocess.run(["git", "-C", str(root), "add", "meta"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Fixture",
        ],
        check=True,
    )
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def payload(revision):
    """Return a complete selection view containing every decision state."""
    return {
        "report_id": "report-1",
        "report_revision": '"etag-one"',
        "source_ref": "org/data",
        "dataset_revision": revision,
        "inventory_complete": True,
        "counts": {
            "total": 4,
            "pass_count": 1,
            "review": 1,
            "blocked": 1,
            "unknown": 1,
            "inventory_complete": True,
        },
        "view": "selection",
        "episodes": [
            {
                "episode_id": f"episode_{i:06d}",
                "source_episode_index": i,
                "source_episode_index_status": "candidate_requires_verification",
                "decision": decision,
                "reasons": [{"reference": 1, "text": None, "resolved": False}],
                "reasons_complete": False,
            }
            for i, decision in enumerate(["pass", "review", "blocked", "unknown"])
        ],
        "page": {"after": 0, "limit": 4, "total_episodes": 4, "next_after": None},
    }


def test_preview_and_export(source, tmp_path):
    """Pass-only selection preserves provenance, policy and unresolved reasons."""
    root, revision = source
    result = preview([FindingsPage.model_validate(payload(revision))], root)
    assert result["counts"] == {
        "selected": 1,
        "excluded": 3,
        "review": 1,
        "unknown": 1,
        "blocked": 1,
        "unmapped": 0,
    }
    assert result["exportable"]
    assert result["episodes"][0]["source_episode_index"] == 0
    assert result["episodes"][0]["reasons"][0]["resolved"] is False
    out = tmp_path / "manifest.json"
    export_manifest(result, out)
    assert json.loads(out.read_text())["report_revision"] == '"etag-one"'
    with pytest.raises(FileExistsError):
        export_manifest(result, out)


def test_complete_pagination_and_missing_pages(source):
    """Short pages are legal but omitted tails cannot export."""
    root, revision = source
    first = payload(revision)
    second = copy.deepcopy(first)
    first["episodes"] = first["episodes"][:1]
    first["page"]["next_after"] = 1
    second["episodes"] = second["episodes"][1:]
    second["page"]["after"] = 1
    pages = [FindingsPage.model_validate(p) for p in [first, second]]
    assert preview(pages, root)["exportable"]
    partial = preview(pages[:1], root)
    assert not partial["exportable"]
    assert partial["coverage"]["missing_source_indices"] == [1, 2, 3]
    with pytest.raises(SelectionError, match="Export refused"):
        export_manifest(partial, root / "must-not-exist.json")


@pytest.mark.parametrize(
    "field", ["source_ref", "dataset_revision", "report_id", "report_revision"]
)
def test_mixed_provenance_refused(source, field):
    """Every provenance field is pinned across all pages."""
    root, revision = source
    first = payload(revision)
    second = copy.deepcopy(first)
    first["episodes"] = first["episodes"][:2]
    first["page"]["next_after"] = 2
    second["episodes"] = second["episodes"][2:]
    second["page"]["after"] = 2
    second[field] = "different"
    with pytest.raises(SelectionError, match="Mixed"):
        preview([FindingsPage.model_validate(p) for p in [first, second]], root)


@pytest.mark.parametrize(
    "mutation",
    [
        "numeric_id",
        "wrong_index",
        "missing_index",
        "duplicate_id",
        "gap",
        "truncated",
        "inventory_incomplete",
    ],
)
def test_unsafe_input(source, mutation):
    """Unsafe mappings and incomplete scopes cannot silently select episodes."""
    root, revision = source
    value = payload(revision)
    if mutation == "numeric_id":
        value["episodes"][0]["episode_id"] = "0"
    elif mutation == "wrong_index":
        value["episodes"][0]["source_episode_index"] = 1
    elif mutation == "missing_index":
        value["episodes"][0]["episode_id"] = "opaque"
        value["episodes"][0]["source_episode_index"] = None
    elif mutation == "duplicate_id":
        value["episodes"][1] = value["episodes"][0]
    elif mutation == "gap":
        value["page"]["after"] = 1
    elif mutation == "truncated":
        value["page"]["truncated"] = True
    else:
        value["inventory_complete"] = False
    if mutation in {"duplicate_id", "gap", "wrong_index"}:
        with pytest.raises(SelectionError):
            preview([FindingsPage.model_validate(value)], root)
    else:
        assert not preview([FindingsPage.model_validate(value)], root)["exportable"]


def test_local_mutation_and_revision_refused(source):
    """Matching names and index numbers do not establish a pinned dataset."""
    root, revision = source
    with pytest.raises(SelectionError, match="HEAD"):
        local_episode_indices(root, "org/data", "0" * 40)
    with pytest.raises(SelectionError, match="origin"):
        local_episode_indices(root, "org/other", revision)
    with pytest.raises(SelectionError, match="immutable"):
        local_episode_indices(root, "org/data", "main")
    (root / "meta/episodes.jsonl").write_text('{"episode_index":99}\n')
    with pytest.raises(SelectionError, match="differs"):
        local_episode_indices(root, "org/data", revision)


def test_v3_metadata(source):
    """Read source indices from actual v3 parquet metadata, including sparse IDs."""
    root, _ = source
    (root / "meta/info.json").write_text(
        json.dumps({"codebase_version": "v3.0", "total_episodes": 2})
    )
    (root / "meta/episodes").mkdir()
    pl.DataFrame({"episode_index": [3, 9]}).write_parquet(
        root / "meta/episodes/file-000.parquet"
    )
    revision = commit(root)
    assert local_episode_indices(root, "org/data", revision) == {3, 9}


def test_duplicate_local_indices(source):
    """Duplicate index metadata is never a usable mapping."""
    root, _ = source
    (root / "meta/episodes.jsonl").write_text('{"episode_index":0}\n' * 4)
    revision = commit(root)
    with pytest.raises(SelectionError, match="Duplicate"):
        local_episode_indices(root, "org/data", revision)


def test_stale_error_and_envelopes(source, tmp_path):
    """Preserve MCP errors rather than treating stale pages as empty success."""
    _, revision = source
    path = tmp_path / "pages.json"
    path.write_text(
        json.dumps(
            {
                "isError": True,
                "structuredContent": {"error": {"code": "stale_revision"}},
            }
        )
    )
    with pytest.raises(SelectionError, match="stale_revision"):
        load_pages([path])
    path.write_text(json.dumps([{"structuredContent": payload(revision)}]))
    assert len(load_pages([path])) == 1


def test_cli_end_to_end(source, tmp_path):
    """Exercise the registered preview/export commands with saved MCP results."""
    root, revision = source
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps(payload(revision)))
    runner = CliRunner()
    result = runner.invoke(app, ["preview", str(pages), "--dataset", str(root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["counts"]["selected"] == 1
    output = tmp_path / "manifest.json"
    result = runner.invoke(
        app,
        ["export", str(pages), "--dataset", str(root), "-o", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()


def test_full_published_source_revision(source):
    """A published full source revision resolves a compatible legacy short token."""
    root, revision = source
    value = payload(revision[:7])
    value["source_dataset_revision"] = revision
    result = preview([FindingsPage.model_validate(value)], root)
    assert result["exportable"]
    assert result["dataset_revision"] == revision[:7]
    assert result["source_dataset_revision"] == revision
    value["dataset_revision"] = "0" * 7
    with pytest.raises(SelectionError, match="disagree"):
        preview([FindingsPage.model_validate(value)], root)


def test_short_revision_alone_refused(source):
    """A short local hash match cannot prove the report's immutable source."""
    root, revision = source
    with pytest.raises(SelectionError, match="immutable"):
        preview([FindingsPage.model_validate(payload(revision[:7]))], root)


def test_prefixed_canonical_ids_and_collisions(source):
    """Canonical suffixes need explicit matching indices; collisions fail closed."""
    root, revision = source
    value = payload(revision)
    value["episodes"][0]["episode_id"] = f"data@{revision}::episode_000000"
    assert preview([FindingsPage.model_validate(value)], root)["exportable"]
    value["episodes"][1]["episode_id"] = "different::episode_000000"
    value["episodes"][1]["source_episode_index"] = 0
    with pytest.raises(SelectionError, match="Duplicate"):
        preview([FindingsPage.model_validate(value)], root)


@pytest.mark.parametrize("mutation", ["missing", "wrong_total", "wrong_decisions"])
def test_inventory_counts(source, mutation):
    """Validate assessed inventory independently of pagination metadata."""
    root, revision = source
    value = payload(revision)
    if mutation == "missing":
        del value["counts"]
        assert not preview([FindingsPage.model_validate(value)], root)["exportable"]
    else:
        if mutation == "wrong_total":
            value["counts"]["total"] += 1
        else:
            value["counts"]["pass_count"] += 1
            value["counts"]["unknown"] -= 1
        with pytest.raises(SelectionError, match="counts"):
            preview([FindingsPage.model_validate(value)], root)


def test_lfs_metadata_verification(source):
    """Materialized LFS metadata must match its committed digest and size."""
    import hashlib

    root, _ = source
    path = root / "meta/episodes.jsonl"
    original = path.read_bytes()
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{hashlib.sha256(original).hexdigest()}\n"
        f"size {len(original)}\n"
    )
    path.write_text(pointer)
    revision = commit(root)
    path.write_bytes(original)
    assert local_episode_indices(root, "org/data", revision) == set(range(4))
    path.write_bytes(original + b"\n")
    with pytest.raises(SelectionError, match="LFS"):
        local_episode_indices(root, "org/data", revision)


def test_report_bundle(source, tmp_path):
    """The live MCP example bundle pins its report and each findings page."""
    _, revision = source
    value = payload(revision)
    report = {
        key: value[key]
        for key in ("source_ref", "dataset_revision", "report_id", "report_revision")
    }
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"report": report, "pages": [value]}))
    assert len(load_pages([path])) == 1
    report["report_revision"] = "stale"
    path.write_text(json.dumps({"report": report, "pages": [value]}))
    with pytest.raises(SelectionError, match="Bundle report provenance"):
        load_pages([path])


@pytest.mark.parametrize(
    "root_prefix",
    [
        "wrong@{revision}",
        "data@0000000000000000000000000000000000000000",
        "nested::data@{revision}",
        "recording",
    ],
)
def test_qualified_id_root_must_match_source(source, root_prefix):
    """A candidate suffix cannot prove a different or nested container identity."""
    root, revision = source
    value = payload(revision)
    prefix = root_prefix.format(revision=revision)
    value["episodes"][0]["episode_id"] = f"{prefix}::episode_000000"
    result = preview([FindingsPage.model_validate(value)], root)
    assert not result["exportable"]
    assert result["counts"]["unmapped"] == 1
    assert result["counts"]["selected"] == 0
