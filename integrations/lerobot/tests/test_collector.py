"""MCP transport-independent paging and stale-evidence safeguards."""

import asyncio
import copy
import json

import pytest
from typer.testing import CliRunner

from kalanos_mcp_lerobot.cli import app
from kalanos_mcp_lerobot.collector import MCPToolError, fetch_selection_pages, payload
from kalanos_mcp_lerobot.selection import SelectionError


IDENTITY = {
    "report_id": "report",
    "report_revision": "etag",
    "dataset": "@k/hf/org/data",
    "source_ref": "org/data",
    "dataset_revision": "a" * 40,
    "source_dataset_revision": "a" * 40,
}


def page(after, length, total=3, next_after=None):
    """Build a deliberately short response independent of the requested limit."""
    return {
        **IDENTITY,
        "view": "selection",
        "episodes": [
            {"episode_id": f"episode_{i:06d}"} for i in range(after, after + length)
        ],
        "page": {
            "after": after,
            "limit": 100,
            "total_episodes": total,
            "next_after": next_after,
        },
    }


class Client:
    """Return queued tool payloads while recording requested offsets/revisions."""

    def __init__(self, values):
        """Copy test fixtures so production code cannot alter later assertions."""
        self.values = copy.deepcopy(values)
        self.calls = []

    async def call_tool(self, name, arguments):
        """Return the next successful or explicitly erroneous tool result."""
        self.calls.append((name, arguments))
        value = self.values.pop(0)
        return {"structuredContent": value, "isError": "error" in value}


def run(client, **kwargs):
    """Run one asynchronous collection without a pytest async plugin."""
    return asyncio.run(fetch_selection_pages(client, "org/data", **kwargs))


def test_short_pages_follow_exact_returned_cursor():
    """An undersized response never makes the collector skip episode positions."""
    client = Client([IDENTITY, page(0, 1, next_after=1), page(1, 2), IDENTITY])
    value = run(client)
    assert [p["page"]["after"] for p in value["pages"]] == [0, 1]
    assert [args["after"] for name, args in client.calls if name == "get_findings"] == [
        0,
        1,
    ]
    assert client.calls[-1][1]["report_revision"] == "etag"


def test_stale_attempt_is_discarded_and_recollected():
    """A final stale token restarts from episode zero, never mixing generations."""
    new = {**IDENTITY, "report_revision": "new"}
    new_page = {**page(0, 3), "report_revision": "new"}
    client = Client(
        [IDENTITY, page(0, 3), {"error": "stale_revision"}, new, new_page, new]
    )
    value = run(client)
    assert value["report"]["report_revision"] == "new"
    assert len(value["pages"]) == 1
    assert value["pages"][0]["report_revision"] == "new"


def test_stale_retry_limit():
    """Repeated stale evidence fails after the configured complete restart."""
    client = Client(
        [IDENTITY, {"error": "stale_revision"}, IDENTITY, {"error": "stale_revision"}]
    )
    with pytest.raises(MCPToolError, match="stale_revision"):
        run(client)
    assert len(client.calls) == 4


def test_output_limit_reduces_request_without_skipping():
    """Only explicit output-size errors permit a smaller read request."""
    client = Client([IDENTITY, {"error": "output_exceeds_limit"}, page(0, 3), IDENTITY])
    run(client)
    calls = [args for name, args in client.calls if name == "get_findings"]
    assert [(x["after"], x["limit"]) for x in calls] == [(0, 100), (0, 50)]


@pytest.mark.parametrize(
    "mutation",
    [
        "gap",
        "duplicate",
        "partial",
        "no_progress",
        "mixed_revision",
        "missing_cursor",
        "truncated",
        "bool_cursor",
        "bool_total",
        "final_identity",
    ],
)
def test_invalid_collection_refused(mutation):
    """Ambiguous pagination and inconsistent provenance never produce a bundle."""
    first, current = page(0, 3), dict(IDENTITY)
    if mutation == "gap":
        first["page"]["after"] = 1
    elif mutation == "duplicate":
        first["episodes"][1] = first["episodes"][0]
    elif mutation == "partial":
        first["episodes"] = first["episodes"][:2]
    elif mutation == "no_progress":
        first["episodes"] = []
        first["page"]["next_after"] = 0
    elif mutation == "mixed_revision":
        first["report_revision"] = "other"
    elif mutation == "missing_cursor":
        del first["page"]["next_after"]
    elif mutation == "truncated":
        first["page"]["truncated"] = True
    elif mutation == "bool_cursor":
        first["page"]["next_after"] = True
    elif mutation == "bool_total":
        first["page"]["total_episodes"] = True
    elif mutation == "final_identity":
        current["source_ref"] = "other/data"
    with pytest.raises(SelectionError):
        run(Client([IDENTITY, first, current]))


def test_tool_failure_is_not_retried():
    """Permissions and operational errors cannot become an alternate-flow retry."""
    client = Client([IDENTITY, {"error": "forbidden"}])
    with pytest.raises(MCPToolError, match="forbidden"):
        run(client)
    assert len(client.calls) == 2


def test_text_payload_fallback_and_failure():
    """SDK text fallback is supported but tool-error envelopes remain failures."""
    assert (
        payload({"content": [{"type": "text", "text": json.dumps(IDENTITY)}]})
        == IDENTITY
    )
    with pytest.raises(MCPToolError):
        payload({"content": [{"type": "text", "text": "{}"}], "isError": True})


def test_fetch_cli_does_not_write_partial_output(monkeypatch, tmp_path):
    """Failed fetches leave no artifact that resembles a complete bundle."""

    async def fail(*args, **kwargs):
        """Simulate a server-side failure before complete collection."""
        raise SelectionError("Incomplete inventory")

    monkeypatch.setattr("kalanos_mcp_lerobot.collector.collect", fail)
    out = tmp_path / "bundle.json"
    result = CliRunner().invoke(app, ["fetch", "org/data", "-o", str(out)])
    assert result.exit_code == 2
    assert not out.exists()


def test_fetch_cli_refuses_overwrite_before_network(monkeypatch, tmp_path):
    """Existing outputs are protected without starting another collection."""

    async def forbidden(*args, **kwargs):
        """Fail if a network collection is attempted."""
        raise AssertionError("network should not be called")

    monkeypatch.setattr("kalanos_mcp_lerobot.collector.collect", forbidden)
    out = tmp_path / "bundle.json"
    out.write_text("keep")
    result = CliRunner().invoke(app, ["fetch", "org/data", "-o", str(out)])
    assert result.exit_code == 2
    assert out.read_text() == "keep"


def test_initialization_stall_has_deadline():
    """SSE keepalives cannot keep a never-initialized session alive forever."""
    from kalanos_mcp_lerobot.collector import initialize_and_fetch

    class Stalled:
        """A transport whose initialize request never receives an answer."""

        async def initialize(self):
            """Remain pending until the collection deadline cancels the request."""
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        asyncio.run(initialize_and_fetch(Stalled(), "org/data", timeout_seconds=0.01))
