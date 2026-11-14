"""CLI Handlers for Local Media Library Management Commands."""

import sys
from rich.console import Console
from rich.table import Table

from nova.library.catalog import MediaLibraryCatalog
from nova.library.cleanup import cleanup_library
from nova.library.prefetch import prefetch_niche_media

console = Console()


def handle_library_cli(args) -> None:
    """Dispatches `python -m nova library [list|prefetch|clean|stats]`."""
    catalog = MediaLibraryCatalog()
    action = getattr(args, "library_action", "list") or "list"

    if action == "list":
        _list_library(catalog, limit=getattr(args, "limit", 20), niche=getattr(args, "niche", ""))
    elif action == "prefetch":
        _prefetch_library(
            niche=getattr(args, "niche", "ai_tech"),
            limit=getattr(args, "limit", 2),
            media_type=getattr(args, "media_type", "video"),
        )
    elif action == "clean":
        _clean_library(
            max_gb=getattr(args, "max_gb", 20),
            dry_run=getattr(args, "dry_run", False),
        )
    elif action == "stats":
        _show_library_stats(catalog)
    else:
        console.print(f"[red]Unknown library action: {action}[/red]")
        sys.exit(1)


def _list_library(catalog: MediaLibraryCatalog, limit: int = 25, niche: str = "") -> None:
    assets = catalog.list_assets(limit=limit, niche=niche)
    if not assets:
        console.print("\n[yellow]Local media library is currently empty. Run `python -m nova library prefetch` to build it.[/yellow]\n")
        return

    table = Table(title=f"Local Media Library Assets ({len(assets)} shown)", show_lines=True)
    table.add_column("Asset ID", style="cyan", width=20)
    table.add_column("Provider", style="white", width=16)
    table.add_column("Type", justify="center", width=8)
    table.add_column("Title", style="white", max_width=32)
    table.add_column("License", style="dim", width=14)
    table.add_column("Size (MB)", justify="right", width=10)
    table.add_column("Uses", justify="right", width=6)
    table.add_column("Protected", justify="center", width=10)

    for a in assets:
        size_mb = round(a["file_size_bytes"] / (1024 * 1024), 2)
        prot_disp = "[green]YES[/green]" if a["is_protected"] else "[dim]NO[/dim]"
        table.add_row(
            a["asset_id"],
            a["provider"],
            a["media_type"],
            a["title"][:32],
            a["license_id"],
            f"{size_mb} MB",
            str(a["usage_count"]),
            prot_disp,
        )

    console.print(table)


def _prefetch_library(niche: str = "ai_tech", limit: int = 2, media_type: str = "video") -> None:
    console.print(f"\n[bold cyan]📥 Starting background prefetch for niche '{niche}' ({limit} per theme)...[/bold cyan]")
    count = prefetch_niche_media(niche=niche, limit_per_theme=limit, media_type=media_type)
    console.print(f"[bold green]✓ Successfully prefetched and catalogued {count} licensed assets into local library![/bold green]\n")


def _clean_library(max_gb: float = 20.0, dry_run: bool = False) -> None:
    max_bytes = int(max_gb * 1024 * 1024 * 1024)
    mode_disp = " (DRY RUN)" if dry_run else ""
    console.print(f"\n[bold cyan]🧹 Checking local library storage against cap: {max_gb} GB{mode_disp}...[/bold cyan]")
    evicted, freed = cleanup_library(max_bytes=max_bytes, dry_run=dry_run)
    freed_mb = round(freed / (1024 * 1024), 2)
    console.print(f"[bold green]✓ Cleanup complete: Evicted {evicted} assets, freed {freed_mb} MB.[/bold green]\n")


def _show_library_stats(catalog: MediaLibraryCatalog) -> None:
    stats = catalog.get_stats()
    table = Table(title="Local Media Library Storage & Index Stats", show_lines=True)
    table.add_column("Metric", style="cyan", width=25)
    table.add_column("Value", style="bold white", width=25)

    table.add_row("Total Indexed Assets", str(stats["total_assets"]))
    table.add_row("Total Disk Usage (MB)", f"{stats['total_size_mb']} MB")
    table.add_row("Total Disk Usage (GB)", f"{stats['total_size_gb']} GB")
    table.add_row("Videos in Catalog", str(stats["videos_count"]))
    table.add_row("Images in Catalog", str(stats["images_count"]))
    table.add_row("Audio Tracks in Catalog", str(stats["audio_count"]))

    console.print(table)
