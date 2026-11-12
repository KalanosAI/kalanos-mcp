"""Read complete, revision-consistent selection pages with the official MCP SDK."""

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlsplit

from kalanos_mcp_lerobot.selection import SelectionError


IDENTITY = (
    "report_id",
    "dataset",
    "source_ref",
    "dataset_revision",
    "source_dataset_revision",
    "report_revision",
)
DEFAULT_ENDPOINT = "https://mcp.kalanos.ai/mcp"


class MCPToolError(SelectionError):
    """A structured MCP error, including its retry-relevant code."""

    def __init__(self, code: str):
        """Retain the error code without interpreting dataset-authored text."""
        self.code = code
        super().__init__(f"MCP tool returned {code}")


def payload(result: Any) -> dict[str, Any]:
    """Unwrap structured MCP results without accepting tool failures as data."""
    if hasattr(result, "model_dump"):
        result = result.model_dump(by_alias=True)
    if not isinstance(result, dict):
        raise SelectionError("MCP returned a non-object envelope")
    value = result.get("structuredContent")
    if value is None:
        texts = [
            c.get("text") for c in result.get("content", []) if c.get("type") == "text"
        ]
        if not texts:
            raise SelectionError("MCP result has no structured or text payload")
        value = json.loads(texts[0])
    if not isinstance(value, dict):
        raise SelectionError("MCP payload must be an object")
    if result.get("isError") or "error" in value:
        error = value.get("error", "tool_error")
        code = (
            error.get("code", "tool_error") if isinstance(error, dict) else str(error)
        )
        raise MCPToolError(code)
    return value


async def fetch_selection_pages(
    client: Any,
    dataset: str,
    *,
    page_size: int = 100,
    restarts: int = 1,
    max_pages: int = 10000,
) -> dict[str, Any]:
    """Collect every page, following returned cursors and checking final identity.

    One stale revision discards the entire attempt before restarting. Only
    explicit output-size errors reduce page size; other failures stop the fetch.
    """
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise SelectionError("page_size must be an integer between 1 and 100")
    if type(restarts) is not int or not 0 <= restarts <= 3:
        raise SelectionError("restarts must be an integer between 0 and 3")
    if type(max_pages) is not int or max_pages < 1:
        raise SelectionError("max_pages must be a positive integer")
    for attempt in range(restarts + 1):
        try:
            report = payload(
                await client.call_tool(
                    "get_report",
                    arguments={
                        "dataset": dataset,
                        "sections": ["outcomes", "details"],
                    },
                )
            )
            if (
                not isinstance(report.get("report_revision"), str)
                or not report["report_revision"]
            ):
                raise SelectionError("Missing report revision")
            pages, seen = [], set()
            after, limit, expected_total = 0, page_size, None
            for _ in range(max_pages):
                args = {
                    "report_id": report["report_id"],
                    "report_revision": report["report_revision"],
                    "view": "selection",
                    "after": after,
                    "limit": limit,
                }
                if report.get("dataset_revision"):
                    args["dataset_revision"] = report["dataset_revision"]
                try:
                    page = payload(
                        await client.call_tool("get_findings", arguments=args)
                    )
                except MCPToolError as exc:
                    if exc.code == "output_exceeds_limit" and limit > 1:
                        limit = max(1, limit // 2)
                        continue
                    raise
                if any(page.get(key) != report.get(key) for key in IDENTITY):
                    raise SelectionError("Inconsistent page provenance")
                p, episodes = page.get("page"), page.get("episodes")
                if not isinstance(p, dict) or not isinstance(episodes, list):
                    raise SelectionError("Missing pagination or episode list")
                total, next_after = p.get("total_episodes"), p.get("next_after")
                if (
                    page.get("view") != "selection"
                    or type(p.get("after")) is not int
                    or p["after"] != after
                    or type(total) is not int
                    or total < 0
                    or "next_after" not in p
                    or p.get("truncated", False)
                    or (expected_total is not None and total != expected_total)
                    or after + len(episodes) > total
                    or len(episodes) > limit
                ):
                    raise SelectionError("Invalid or incomplete pagination")
                expected_total = total
                for episode in episodes:
                    key = (
                        episode.get("episode_id") if isinstance(episode, dict) else None
                    )
                    if not isinstance(key, str) or not key or key in seen:
                        raise SelectionError("Duplicate or missing episode ID")
                    seen.add(key)
                pages.append(page)
                if next_after is None:
                    if len(seen) != total:
                        raise SelectionError("Incomplete episode inventory")
                    current = payload(
                        await client.call_tool(
                            "get_report",
                            arguments={
                                "report_id": report["report_id"],
                                "report_revision": report["report_revision"],
                                "sections": [],
                            },
                        )
                    )
                    if any(current.get(key) != report.get(key) for key in IDENTITY):
                        raise SelectionError(
                            "Source identity changed after the final page"
                        )
                    return {"report": report, "pages": pages}
                if (
                    not episodes
                    or type(next_after) is not int
                    or next_after != after + len(episodes)
                ):
                    raise SelectionError("Invalid pagination cursor")
                after = next_after
            raise SelectionError("Page safety limit exceeded")
        except MCPToolError as exc:
            if exc.code != "stale_revision" or attempt == restarts:
                raise
    raise AssertionError("Unreachable collection state")


async def initialize_and_fetch(
    session: Any, dataset: str, *, page_size: int = 100, timeout_seconds: float = 600
) -> dict[str, Any]:
    """Bound initialization and collection, including an endpoint that stalls."""
    async with asyncio.timeout(timeout_seconds):
        await session.initialize()
        return await fetch_selection_pages(session, dataset, page_size=page_size)


async def collect(
    dataset: str, *, endpoint: str = DEFAULT_ENDPOINT, page_size: int = 100
) -> dict[str, Any]:
    """Connect to the HTTPS endpoint and fetch one complete report inventory."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise SelectionError(
            "MCP endpoint must be an HTTPS URL without embedded credentials"
        )
    key = os.environ.get("KALANOS_API_KEY")
    import httpx

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(
        headers=headers, timeout=httpx.Timeout(60, read=180), follow_redirects=False
    ) as http:
        async with streamable_http_client(endpoint, http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                return await initialize_and_fetch(session, dataset, page_size=page_size)
