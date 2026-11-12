"""Smoke checks assert loader results, not just successful construction."""

import sys
from types import SimpleNamespace

import pytest
from test_selection_lerobot import selected as selected

from kalanos_mcp_lerobot.selection import SelectionError
from kalanos_mcp_lerobot.smoke import smoke_selection


class Dataset:
    """Small loader double used only to test result checks without video costs."""

    def __init__(self, revision, values):
        """Expose the fields consumed by the real-loader validation path."""
        self.revision = revision
        self.hf_dataset = {"episode_index": values}
        self.meta = SimpleNamespace(
            total_episodes=4, total_frames=8, episodes=[{"length": 2}] * 4
        )

    def __getitem__(self, pos):
        """Return a row with an explicit source episode identity."""
        return {"episode_index": self.hf_dataset["episode_index"][pos], "task": "Test"}


def install_loader(
    monkeypatch, manifest, *, values=None, revision=None, version="0.7.0"
):
    """Substitute only optional external imports, retaining real manifest checks."""

    def factory(**kwargs):
        """Assert the adapter forwards the pinned subset into the loader."""
        assert kwargs["episodes"] == [0]
        assert kwargs["revision"] == manifest["source_dataset_revision"]
        return Dataset(
            revision or kwargs["revision"], [0, 0] if values is None else values
        )

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(constants=SimpleNamespace(HF_HUB_OFFLINE=True)),
    )
    monkeypatch.setitem(
        sys.modules,
        "lerobot.datasets.lerobot_dataset",
        SimpleNamespace(LeRobotDataset=factory),
    )
    monkeypatch.setattr(
        "kalanos_mcp_lerobot.smoke.importlib.metadata.version", lambda name: version
    )


def test_smoke_checks_ids_counts_and_samples(selected, monkeypatch):
    """Valid loader results preserve provenance and record sampled frame facts."""
    root, path, manifest = selected
    install_loader(monkeypatch, manifest)
    result = smoke_selection(path, root)
    assert result["loaded_frames"] == 2
    assert result["excluded_source_indices"] == [1, 2, 3]
    assert len(result["sampled_frames"]) == 2
    assert result["offline"]


@pytest.mark.parametrize("values", [[0], [0, 1], []])
def test_wrong_loaded_inventory_is_rejected(selected, monkeypatch, values):
    """Missing frames, extra episodes and empty loads cannot pass a smoke check."""
    root, path, manifest = selected
    install_loader(monkeypatch, manifest, values=values)
    with pytest.raises(SelectionError, match="episode IDs or frame counts"):
        smoke_selection(path, root)


def test_loader_revision_change_is_rejected(selected, monkeypatch):
    """The real loader must keep the exact revision it was given."""
    root, path, manifest = selected
    install_loader(monkeypatch, manifest, revision="changed")
    with pytest.raises(SelectionError, match="revision differs"):
        smoke_selection(path, root)


def test_untested_runtime_version_is_rejected(selected, monkeypatch):
    """The optional smoke command states rather than assumes runtime compatibility."""
    root, path, manifest = selected
    install_loader(monkeypatch, manifest, version="0.6.0")
    with pytest.raises(SelectionError, match="validated with LeRobot 0.7.0"):
        smoke_selection(path, root)
