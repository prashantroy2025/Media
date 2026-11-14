"""CLI Handlers for Media Provider Management Commands."""

import sys
from rich.console import Console
from rich.table import Table
import yaml

from nova.licensing.checker import LicenseComplianceEngine
from nova.providers.registry import ProviderRegistry

console = Console()


def handle_providers_cli(args) -> None:
    """Dispatches `python -m nova providers [list|test|enable|disable|stats|audit]`."""
    registry = ProviderRegistry()
    action = getattr(args, "provider_action", "list") or "list"

    if action == "list":
        _list_providers(registry)
    elif action == "test":
        _test_providers(registry, target_id=getattr(args, "target", None))
    elif action == "enable":
        _toggle_provider(getattr(args, "target", None), enable=True)
    elif action == "disable":
        _toggle_provider(getattr(args, "target", None), enable=False)
    elif action == "stats":
        _show_provider_stats(registry)
    elif action == "audit":
        _audit_providers(registry)
    else:
        console.print(f"[red]Unknown providers action: {action}[/red]")
        sys.exit(1)


def _list_providers(registry: ProviderRegistry) -> None:
    table = Table(title="Nova Autopilot - Licensed Media Providers Registry", show_lines=True)
    table.add_column("Provider ID", style="cyan", width=18)
    table.add_column("Display Name", style="white", width=26)
    table.add_column("Status", justify="center", width=16)
    table.add_column("Key Env Var", style="dim", width=22)
    table.add_column("Media Types", style="yellow", width=16)
    table.add_column("Circuit", justify="center", width=10)

    for p in registry.list_providers():
        status_raw = p["status"]
        if status_raw == "enabled":
            status_disp = "[bold green]ACTIVE (Ready)[/bold green]"
        elif status_raw == "needs_key":
            status_disp = "[bold yellow]NEEDS FREE KEY[/bold yellow]"
        elif status_raw == "needs_decision":
            status_disp = "[bold red]DECISION REQD[/bold red]"
        else:
            status_disp = "[dim]DISABLED[/dim]"

        circuit_disp = "[bold red]OPEN[/bold red]" if p["is_circuit_open"] else "[green]OK[/green]"
        key_disp = p["key_env"] or "(Keyless)"

        table.add_row(
            p["id"],
            p["name"],
            status_disp,
            key_disp,
            ", ".join(p["media_types"]),
            circuit_disp,
        )

    console.print(table)
    console.print("\n[dim]To test connectivity: [cyan]python -m nova providers test[/cyan]")
    console.print("[dim]To toggle a provider: [cyan]python -m nova providers enable|disable <id>[/cyan]\n")


def _test_providers(registry: ProviderRegistry, target_id: str | None = None) -> None:
    table = Table(title="Nova Media Providers Live Connection Test", show_lines=True)
    table.add_column("Provider", style="cyan", width=24)
    table.add_column("Result", justify="center", width=10)
    table.add_column("Response & License Clearance", style="white", width=50)

    targets = [target_id] if target_id else list(registry.providers.keys())

    for pid in targets:
        prov = registry.get_provider(pid)
        if not prov:
            console.print(f"[red]Provider '{pid}' not found.[/red]")
            continue

        ok, msg = prov.test_connection()
        res_disp = "[bold green]PASS[/bold green]" if ok else "[bold yellow]WARN[/bold yellow]"
        if pid in ("coverr", "jamendo"):
            res_disp = "[bold magenta]NOTICE[/bold magenta]"
        table.add_row(prov.name, res_disp, msg)

    console.print(table)


def _toggle_provider(provider_id: str | None, enable: bool) -> None:
    if not provider_id:
        console.print("[red]Error: Must specify provider ID (e.g. `python -m nova providers enable pexels`)[/red]")
        sys.exit(1)

    cfg_path = registry_cfg = "config/media_providers.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    provs = data.get("providers", {})
    if provider_id not in provs:
        console.print(f"[red]Provider '{provider_id}' is not in {cfg_path}[/red]")
        sys.exit(1)

    provs[provider_id]["enabled"] = enable
    data["providers"] = provs

    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)

    action_word = "Enabled" if enable else "Disabled"
    console.print(f"[bold green]✓ Successfully {action_word.lower()} provider '{provider_id}' in {cfg_path}[/bold green]")


def _show_provider_stats(registry: ProviderRegistry) -> None:
    console.print("\n[bold cyan]📊 Nova Media Providers Infrastructure Stats[/bold cyan]")
    cache_dir = registry.providers["pixabay"].cache.cache_dir
    cache_files = list(cache_dir.glob("*.json")) if cache_dir.exists() else []

    console.print(f"• Persistent Cache Entries: [green]{len(cache_files)}[/green] files at `{cache_dir}`")
    tripped = [p.name for p in registry.providers.values() if p.is_circuit_open]
    console.print(f"• Circuit Breaker Status: [green]{len(tripped)} open[/green] ({', '.join(tripped) if tripped else 'All healthy'})")
    active_count = sum(1 for p in registry.providers.values() if p.enabled)
    console.print(f"• Registered Providers: [cyan]{active_count} enabled[/cyan] / {len(registry.providers)} total\n")


def _audit_providers(registry: ProviderRegistry) -> None:
    console.print("\n[bold cyan]🛡️ Nova Media & License Compliance Audit[/bold cyan]\n")
    engine = LicenseComplianceEngine()

    test_licenses = [
        ("CC0 1.0", "openverse", True),
        ("Public Domain Mark", "wikimedia_commons", True),
        ("US Government Work", "nasa_library", True),
        ("Pixabay Content License", "pixabay", True),
        ("Pexels License", "pexels", True),
        ("CC BY 4.0", "wikimedia_commons", True),
        ("CC BY-SA 4.0", "wikimedia_commons", False),  # Copyleft - MUST BE REJECTED!
        ("CC BY-NC 4.0", "openverse", False),  # NonCommercial - MUST BE REJECTED!
        ("CC BY-ND 3.0", "flickr", False),  # NoDerivatives - MUST BE REJECTED!
        ("All Rights Reserved", "shutterstock", False),  # Proprietary - MUST BE REJECTED!
    ]

    all_passed = True
    table = Table(title="Automated License Policy Verification", show_lines=True)
    table.add_column("Raw License String", style="cyan", width=25)
    table.add_column("Expected Outcome", justify="center", width=18)
    table.add_column("Actual Outcome", justify="center", width=18)
    table.add_column("Status", justify="center", width=10)

    for lic, prov, expected in test_licenses:
        ok, _, reason = engine.evaluate(
            raw_license=lic,
            provider=prov,
            asset_id="test_01",
            landing_page="https://example.com",
            creator="Test Creator",
        )
        passed = (ok == expected)
        if not passed:
            all_passed = False
        status_disp = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        exp_disp = "[green]APPROVED[/green]" if expected else "[red]REJECTED[/red]"
        act_disp = "[green]APPROVED[/green]" if ok else "[red]REJECTED[/red]"

        table.add_row(lic, exp_disp, act_disp, status_disp)

    console.print(table)
    if all_passed:
        console.print("\n[bold green]✓ License compliance engine PASSED all strict allow-list and copyleft/NC rejection tests![/bold green]\n")
    else:
        console.print("\n[bold red]❌ License compliance engine failed some tests.[/bold red]\n")
