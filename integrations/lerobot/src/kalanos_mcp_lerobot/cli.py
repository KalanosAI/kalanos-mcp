"""Offline MCP selection preview and manifest export commands."""

import json
from pathlib import Path
from typing import Annotated

import typer
from polars.exceptions import PolarsError
from pydantic import ValidationError

from kalanos_mcp_lerobot.selection import (
    SelectionError,
    export_manifest,
    load_pages,
    preview,
)


app = typer.Typer(
    help="Collect Kalanos MCP evidence and prepare verified LeRobot selections.",
    no_args_is_help=True,
)
Pages = Annotated[
    list[Path], typer.Argument(help="Saved compact get_findings JSON pages, in order.")
]
Dataset = Annotated[
    Path,
    typer.Option(
        "--dataset", help="Pinned local HF Git checkout of the LeRobot dataset."
    ),
]


def _result(pages: list[Path], dataset: Path) -> dict:
    """Validate inputs and convert expected failures into concise CLI errors."""
    try:
        return preview(load_pages(pages), dataset)
    except (
        SelectionError,
        ValidationError,
        OSError,
        ValueError,
        KeyError,
        PolarsError,
    ) as exc:
        typer.echo(f"Selection refused: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("preview")
def preview_command(
    pages: Pages,
    dataset: Dataset,
    full: Annotated[
        bool, typer.Option(help="Include every selected episode record.")
    ] = False,
) -> None:
    """Print selected/excluded counts, mapping status, and coverage gaps as JSON."""
    result = _result(pages, dataset)
    shown = (
        result
        if full
        else {key: value for key, value in result.items() if key != "episodes"}
    )
    typer.echo(json.dumps(shown, indent=2))
    if not result["exportable"]:
        raise typer.Exit(2)


@app.command("export")
def export_command(
    pages: Pages,
    dataset: Dataset,
    output: Annotated[Path, typer.Option("--output", "-o")],
) -> None:
    """Export a new, pass-only JSON manifest after all safety checks pass."""
    result = _result(pages, dataset)
    try:
        export_manifest(result, output)
    except (SelectionError, OSError) as exc:
        typer.echo(f"Selection refused: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"Exported {result['counts']['selected']} verified episodes to {output}")


@app.command("handoff")
def lerobot_command(
    manifest: Annotated[Path, typer.Argument(help="Exported selection.v1 JSON file.")],
    dataset: Dataset,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Emit verified LeRobot dataset arguments; never download data or train."""
    from kalanos_mcp_lerobot.selection_lerobot import lerobot_input

    try:
        result = lerobot_input(manifest, dataset)
        rendered = json.dumps(result, indent=2) + "\n"
        if output is None:
            typer.echo(rendered, nl=False)
        else:
            with output.open("x") as handle:
                handle.write(rendered)
            typer.echo(f"Exported LeRobot dataset arguments to {output}")
    except (
        SelectionError,
        ValidationError,
        OSError,
        ValueError,
        KeyError,
        PolarsError,
    ) as exc:
        typer.echo(f"LeRobot handoff refused: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command("fetch")
def fetch_command(
    source: Annotated[
        str, typer.Argument(help="Public dataset source_ref, e.g. org/dataset.")
    ],
    output: Annotated[Path, typer.Option("--output", "-o")],
    endpoint: Annotated[
        str, typer.Option(help="Read-only HTTPS Kalanos MCP endpoint.")
    ] = "https://mcp.kalanos.ai/mcp",
    page_size: Annotated[int, typer.Option(min=1, max=100)] = 100,
) -> None:
    """Save every selection page from one current report revision."""
    import asyncio

    from kalanos_mcp_lerobot.collector import collect

    try:
        if output.exists():
            raise SelectionError(f"Output already exists: {output}")
        bundle = asyncio.run(collect(source, endpoint=endpoint, page_size=page_size))
        with output.open("x") as handle:
            handle.write(json.dumps(bundle, indent=2) + "\n")
    except Exception as exc:
        typer.echo(f"MCP collection refused: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        f"Collected {sum(len(p['episodes']) for p in bundle['pages'])} episodes "
        f"across {len(bundle['pages'])} pages to {output}"
    )


@app.command("smoke")
def smoke_command(
    manifest: Annotated[Path, typer.Argument(help="Exported selection.v1 JSON file.")],
    dataset: Dataset,
    output: Annotated[Path, typer.Option("--output", "-o")],
    sample_episodes: Annotated[int, typer.Option(min=1, max=20)] = 3,
) -> None:
    """Offline: verify loaded IDs/counts and decode sampled LeRobot frames."""
    from kalanos_mcp_lerobot.smoke import smoke_selection

    try:
        if output.exists():
            raise SelectionError(f"Output already exists: {output}")
        result = smoke_selection(manifest, dataset, sample_episodes=sample_episodes)
        with output.open("x") as handle:
            handle.write(json.dumps(result, indent=2) + "\n")
    except Exception as exc:
        typer.echo(f"LeRobot smoke check failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        f"Verified {result['selected_episodes']} selected episodes "
        f"and {result['loaded_frames']} frames; "
        f"decoded {len(result['sampled_frames'])} samples. Saved {output}"
    )
