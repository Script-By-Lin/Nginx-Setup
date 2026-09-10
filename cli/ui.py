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
    """Display list of registered projects and their routes in a Rich Table."""
    if not projects:
        console.print("[yellow]No projects currently configured in registry.[/yellow]")
        return

    table = Table(title="📋 Configured Nginx Projects", border_style="cyan", show_header=True)
    table.add_column("Project Name", style="bold cyan")
    table.add_column("Domain", style="yellow")
    table.add_column("SSL", style="green")
    table.add_column("Routes", style="magenta")
    table.add_column("Config File", style="white")
    table.add_column("Last Updated", style="dim")

    for p in projects:
        routes_summary = ", ".join([f"{r.path} ➔ :{r.backend_port}" for r in p.routes])
        ssl_str = "✔ Enabled" if p.ssl_enabled else "✖ Disabled"
        table.add_row(
            p.project_name,
            p.domain or "(default IP)",
            ssl_str,
            routes_summary or "/",
            p.config_file_path,
            p.updated_at,
        )

    console.print(table)
