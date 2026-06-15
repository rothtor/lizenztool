from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .config import AppConfig, expand_filename, load_config
from .metadata import read_metadata, strip_exif, write_metadata
from .overlay import render_overlay
from .prompts import confirm_or_edit, prompt_manual

app = typer.Typer(help="Add license overlays to images.")
console = Console()


@app.command()
def process(
    images: Annotated[list[Path], typer.Argument(help="Image file(s) to process.")],
    output_dir: Annotated[Path | None, typer.Option("--output-dir", "-o", help="Output directory.")] = None,
    config_path: Annotated[Path | None, typer.Option("--config", "-c", help="Path to config TOML file.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview only, do not save.")] = False,
    batch: Annotated[bool, typer.Option("--batch", help="Apply same license to all images (confirm once).")] = False,
) -> None:
    cfg = load_config(config_path)

    valid = [p for p in images if _check(p)]
    if not valid:
        raise typer.Exit(1)

    shared_info = None
    if batch:
        console.print(f"[bold]Batch mode:[/bold] {len(valid)} image(s). Enter license info once.\n")
        info = read_metadata(valid[0])
        shared_info = confirm_or_edit(info) if not info.is_empty() else prompt_manual()

    for idx, image_path in enumerate(valid, start=1):
        console.rule(f"[bold]{image_path.name}[/bold]")
        info = shared_info if batch else _resolve_info(image_path)

        out_path = _output_path(image_path, output_dir, idx, len(valid), cfg)
        console.print(f"  Overlay text: [green]{info.overlay_text()}[/green]")
        console.print(f"  Output:       [cyan]{out_path}[/cyan]")
        console.print(f"  Strip EXIF:   [cyan]{cfg.output.strip_exif}[/cyan]")

        if not dry_run:
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
            render_overlay(image_path, info, out_path, style=cfg.style)
            if cfg.output.strip_exif:
                try:
                    strip_exif(out_path)
                except Exception:
                    console.print("  [yellow]Warning: EXIF strip failed (exiftool missing?)[/yellow]")
            if cfg.output.write_license_meta:
                write_metadata(out_path, info)
            console.print("  [bold green]Done.[/bold green]")
        else:
            console.print("  [yellow]Dry run — nothing saved.[/yellow]")


def _check(p: Path) -> bool:
    if not p.exists():
        console.print(f"[red]File not found:[/red] {p}")
        return False
    if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}:
        console.print(f"[red]Unsupported format:[/red] {p}")
        return False
    return True


def _resolve_info(image_path: Path):
    info = read_metadata(image_path)
    return confirm_or_edit(info) if not info.is_empty() else prompt_manual()


def _output_path(image_path: Path, output_dir: Path | None, idx: int, total: int, cfg: AppConfig) -> Path:
    width = len(str(total))
    counter = f"{idx:0{width}}"
    name = expand_filename(cfg.output.filename_pattern, counter) + image_path.suffix.lower()
    base = output_dir if output_dir else image_path.parent
    return base / name


