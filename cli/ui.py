"""Rich-based terminal UI formatting, banners, step indicators, and tables."""

from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from models.server_config import ProjectState, ServerConfig

console = Console()


def print_banner() -> None:
    """Print stylish application banner."""
    banner_text = (
        "[bold cyan]⚡ Nginx + SSL DevOps Automation Suite ⚡[/bold cyan]\n"
        "[dim]Production-Grade Reverse Proxy, Certbot SSL, & Firewall Manager[/dim]"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def step_success(message: str) -> None:
    """Print step success indicator."""
    console.print(f"  [bold green][✔][/bold green] {message}")


def step_error(message: str) -> None:
    """Print step failure indicator."""
    console.print(f"  [bold red][✖][/bold red] {message}")


def step_warn(message: str) -> None:
    """Print step warning indicator."""
    console.print(f"  [bold yellow][!][/bold yellow] {message}")


def step_info(message: str) -> None:
    """Print step info indicator."""
    console.print(f"  [bold cyan][•][/bold cyan] {message}")


def print_config_preview(config_content: str, title: str = "Nginx Configuration Preview") -> None:
    """Render syntax-highlighted Nginx configuration."""
    syntax = Syntax(config_content, "nginx", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=f"[bold green]{title}[/bold green]", border_style="green"))


def print_success_summary(
    config: ServerConfig,
    public_ip: str,
    target_file: str,
    local_ip: Optional[str] = None,
) -> None:
    """Print formatted final output with access URLs and DNS setup instructions."""
    console.print()
    console.print(Panel("[bold green]🎉 Deployment & Configuration Succeeded![/bold green]", border_style="green"))

    # Access URLs Table
    url_table = Table(title="🌐 Active Access Endpoints", border_style="cyan", show_header=True)
    url_table.add_column("Route Name", style="bold white")
    url_table.add_column("Path", style="yellow")
    url_table.add_column("Upstream Backend", style="magenta")
    url_table.add_column("Access URL (Public / Domain)", style="bold green")
    if local_ip and local_ip != "127.0.0.1":
        url_table.add_column("LAN Access URL (Local Network)", style="bold cyan")

    for route in config.routes:
        if config.ssl_enabled and config.domain:
            proto = "https"
            host = config.domain
        else:
            proto = "http"
            host = config.domain if config.domain else public_ip

        access_url = f"{proto}://{host}{route.path}"
        if local_ip and local_ip != "127.0.0.1":
            lan_url = f"http://{local_ip}{route.path}"
            url_table.add_row(route.name, route.path, route.target_url, access_url, lan_url)
        else:
            url_table.add_row(route.name, route.path, route.target_url, access_url)

    console.print(url_table)

    # DNS Instructions (if domain is configured)
    if config.domain:
        dns_panel = (
            f"[bold yellow]DNS Setup Guidance:[/bold yellow]\n"
            f"  [bold]Record Type:[/bold]  A Record\n"
            f"  [bold]Host / Name:[/bold]  {config.domain}\n"
            f"  [bold]Points to:[/bold]    {public_ip}\n"
            f"  [bold]TTL:[/bold]          300 (or Automatic)\n\n"
            f"[dim]Note: Ensure your domain's A-record is saved with your DNS registrar (Cloudflare, Route53, Namecheap, etc.)[/dim]"
        )
        console.print(Panel(dns_panel, title="📡 DNS Configuration", border_style="yellow"))

    console.print(f"[bold cyan]📁 Config File Location:[/bold cyan] {target_file}")
    console.print(f"[bold cyan]🔄 To reload manually:[/bold cyan] sudo systemctl reload nginx")
    console.print()


def print_projects_table(projects: List[ProjectState]) -> None:
    """Display list of registered projects, codes, and their routes in a Rich Table."""
    if not projects:
        console.print("[yellow]No projects currently configured in registry.[/yellow]")
        return

    table = Table(title="📋 Configured Nginx Projects", border_style="cyan", show_header=True)
    table.add_column("Project Code", style="bold green")
    table.add_column("Project Name", style="bold cyan")
    table.add_column("Domain / Host", style="yellow")
    table.add_column("SSL", style="green")
    table.add_column("Routes", style="magenta")
    table.add_column("Config File", style="white")
    table.add_column("Last Updated", style="dim")

    for p in projects:
        routes_summary = ", ".join([f"{r.path} ➔ {r.backend_host}:{r.backend_port}" for r in p.routes])
        ssl_str = f"✔ {p.ssl_type.title()}" if p.ssl_enabled else "✖ Disabled"
        table.add_row(
            f"[bold green]{p.project_code}[/bold green]",
            p.project_name,
            p.domain or "(default IP)",
            ssl_str,
            routes_summary or "/",
            p.config_file_path,
            p.updated_at,
        )

    console.print(table)


def print_nginx_inspection_table(scan_result) -> None:
    """Display active Nginx system configuration and port scan results."""
    if not scan_result or not scan_result.virtual_hosts:
        console.print("[yellow]No active Nginx virtual hosts found in system configuration.[/yellow]")
        return

    table = Table(title="🔍 Detected System Nginx Configurations & Listening Ports", border_style="green", show_header=True)
    table.add_column("Config File", style="cyan")
    table.add_column("Listen Ports", style="bold green")
    table.add_column("Server Names", style="yellow")
    table.add_column("SSL", style="magenta")
    table.add_column("Proxy Upstream", style="white")

    for vh in scan_result.virtual_hosts:
        ports_str = ", ".join(str(p) for p in vh.listen_ports) or "-"
        names_str = ", ".join(vh.server_names) if vh.server_names else "_"
        ssl_str = "[bold green]✔ Yes[/bold green]" if vh.ssl_enabled else "[dim]No[/dim]"
        proxy_str = ", ".join(vh.proxy_passes[:2]) if vh.proxy_passes else "-"
        if len(vh.proxy_passes) > 2:
            proxy_str += f" (+{len(vh.proxy_passes)-2} more)"

        table.add_row(
            vh.file_path,
            ports_str,
            names_str,
            ssl_str,
            proxy_str,
        )

    console.print(table)


def print_systemd_services_table(services: List[dict]) -> None:
    """Display managed systemd background services and their live status."""
    if not services:
        console.print("[yellow]No managed systemd services found in registry.[/yellow]")
        return

    table = Table(title="⚙️  Managed Systemd Services (Boot Auto-Start Enabled)", border_style="cyan", show_header=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Service Name", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="yellow")
    table.add_column("User", style="magenta")
    table.add_column("Status", justify="center")
    table.add_column("Boot Autostart", justify="center")
    table.add_column("ExecStart Command", style="dim")
    table.add_column("Unit File Path", style="dim")

    for idx, s in enumerate(services, 1):
        is_active = s.get("is_active", False)
        is_enabled = s.get("is_enabled", False)
        active_state = s.get("active_state", "unknown")

        if is_active:
            status_str = "[bold green]🟢 Active[/bold green]"
        elif active_state == "failed":
            status_str = "[bold red]🔴 Failed[/bold red]"
        else:
            status_str = f"[yellow]⚪ {active_state.title()}[/yellow]"

        enabled_str = "[bold green]🟢 Enabled[/bold green]" if is_enabled else "[dim]⚪ Disabled[/dim]"

        name = s.get("service_name", "")
        if not name.endswith(".service"):
            unit_display = f"{name}.service"
        else:
            unit_display = name

        table.add_row(
            str(idx),
            f"[bold cyan]{unit_display}[/bold cyan]",
            s.get("description", "-"),
            s.get("user", "root"),
            status_str,
            enabled_str,
            s.get("exec_start", "-"),
            s.get("service_file_path", f"/etc/systemd/system/{unit_display}"),
        )

    console.print(table)


def print_unit_preview(content: str, title: str = "Systemd Service Unit Preview") -> None:
    """Display syntax-highlighted systemd unit file preview."""
    syntax = Syntax(content, "ini", theme="monokai", line_numbers=True)
    panel = Panel(syntax, title=f"[bold green]{title}[/bold green]", border_style="cyan")
    console.print(panel)


def print_main_menu() -> None:
    """Display the beautifully formatted and perfectly aligned interactive menu."""
    console.print("[bold yellow]Please select an action by number:[/bold yellow]\n")

    def render_section(title: str, items: list) -> None:
        console.print(f"[bold cyan]─── {title} " + "─" * max(2, 60 - len(title)) + "[/bold cyan]")
        table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 1), show_edge=False)
        table.add_column(style="bold cyan", justify="right", width=4)
        table.add_column(justify="center", width=3)
        table.add_column(style="bold white")
        for num, icon, text in items:
            table.add_row(f"{num}.", icon, text)
        console.print(table)

    items_nginx = [
        (1, "🚀", "Setup New Reverse Proxy [dim](Interactive Wizard)[/dim]"),
        (2, "➕", "Add Service / Route [dim](Append route to existing project)[/dim]"),
        (3, "🔒", "Enable / Upgrade SSL for Project [dim](by Project CODE: SE-001)[/dim]"),
        (4, "📋", "List Registered Projects & Routes"),
        (5, "🔍", "Preview Nginx Configuration [dim](Dry-run)[/dim]"),
        (6, "🧪", "Test Nginx Configuration Syntax [dim](nginx -t)[/dim]"),
        (7, "🗑️", "Remove / Decommission an Nginx Project"),
    ]

    items_systemd = [
        (8, "⚙️", "Create & Auto-Enable Systemd Service [dim](FastAPI, Flask, etc.)[/dim]"),
        (9, "📑", "List & Monitor Managed Systemd Services"),
        (10, "▶️", "Control Systemd Service [dim](Start, Stop, Restart, Status, Logs)[/dim]"),
        (11, "🗑️", "Remove / Decommission a Systemd Service"),
    ]

    items_diag = [
        (12, "🔍", "Inspect Active Nginx Virtual Hosts & Ports [dim](nginx.conf & conf.d)[/dim]"),
        (13, "🩺", "System Status & Diagnostics"),
    ]

    items_exit = [
        (14, "❌", "[bold red]Exit[/bold red]"),
    ]

    render_section("🌐 Nginx Reverse Proxy Management", items_nginx)
    console.print()
    render_section("⚙️  Systemd Background Services (Auto-Start on Boot)", items_systemd)
    console.print()
    render_section("🩺 Diagnostics & Inspection", items_diag)
    console.print()
    render_section("🚪 Exit", items_exit)
    console.print()





