"""Main CLI entry point for Nginx + SSL DevOps Automation Suite."""

import datetime
import os
import sys
from typing import List, Optional
import typer
from rich.prompt import Confirm, IntPrompt, Prompt

from cli.ui import (
    console,
    print_banner,
    print_config_preview,
    print_projects_table,
    print_success_summary,
    step_error,
    step_info,
    step_success,
    step_warn,
)
from core.firewall_manager import FirewallManager
from core.installer import PackageInstaller
from core.nginx_manager import NginxManager
from core.os_detector import OSDetector
from core.service_manager import ServiceManager
from core.ssl_manager import SSLManager
from models.server_config import ProjectState, RouteConfig, ServerConfig
from utils.dns import DNSHelper
from utils.storage import StateManager
from utils.validator import DomainValidator, PathValidator, PortValidator

app = typer.Typer(
    name="nginx-cli",
    help="Production-Grade Nginx + SSL + Firewall Automation CLI for FastAPI & Backend Services.",
    add_completion=False,
)


@app.command(name="setup", help="Interactively configure and deploy Nginx reverse proxy with SSL and Firewall rules.")
def setup(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (e.g. fastapi-app)"),
    executable: Optional[str] = typer.Option(None, "--executable", "-e", help="Backend executable path/command"),
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Backend host/IP (e.g. 127.0.0.1, 0.0.0.0, or LAN IP)"),
    port: Optional[int] = typer.Option(None, "--port", help="Backend port number (e.g. 8000)"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain name (optional, e.g. api.example.com)"),
    route: Optional[str] = typer.Option(None, "--route", "-r", help="Nginx route location path (default: /)"),
    ssl: Optional[bool] = typer.Option(None, "--ssl/--no-ssl", help="Enable Let's Encrypt SSL HTTPS certificate"),
    email: Optional[str] = typer.Option(None, "--email", "-m", help="Email for Let's Encrypt notifications"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without modifying system files"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-y", help="Run non-interactively with provided flags"),
):
    """Guided wizard to set up Nginx reverse proxy, Certbot SSL, firewall, and multi-service routing."""
    print_banner()

    os_detector = OSDetector(dry_run=dry_run)
    os_info = os_detector.detect()
    installer = PackageInstaller(os_detector=os_detector, dry_run=dry_run)
    firewall_mgr = FirewallManager(dry_run=dry_run)
    ssl_mgr = SSLManager(dry_run=dry_run)
    nginx_mgr = NginxManager(os_detector=os_detector, dry_run=dry_run)
    service_mgr = ServiceManager(dry_run=dry_run)
    state_mgr = StateManager()

    step_info(f"Detected OS: [bold green]{os_info.pretty_name}[/bold green] (Family: {os_info.family.value}, Pkg: {os_info.package_manager.value})")

    # 1. Project Name
    if not project:
        if non_interactive:
            project = "app"
        else:
            project = Prompt.ask("[bold cyan]Enter Project Name[/bold cyan]", default="fastapi-app").strip()

    # 2. First Backend Route Setup
    routes: List[RouteConfig] = []
    
    if not route:
        if non_interactive:
            route = "/"
        else:
            route = Prompt.ask("[bold cyan]Enter Route Path[/bold cyan] (e.g. / or /api1/)", default="/").strip()

    if not host:
        if non_interactive:
            host = "127.0.0.1"
        else:
            host = Prompt.ask(
                "[bold cyan]Enter Backend Host / IP[/bold cyan] [dim](127.0.0.1, 0.0.0.0, or LAN IP like 192.168.x.x)[/dim]",
                default="127.0.0.1",
            ).strip()

    if not port:
        if non_interactive:
            port = 8000
        else:
            port = IntPrompt.ask("[bold cyan]Enter Backend Port[/bold cyan] (e.g. 8000)", default=8000)

    # Validate Port
    if not PortValidator.is_valid_port(port):
        step_error(f"Invalid port: {port}. Port must be between 1 and 65535.")
        raise typer.Exit(code=1)

    is_listening = PortValidator.is_port_listening(port, host=host)
    if is_listening:
        proc_info = PortValidator.get_process_using_port(port)
        step_success(f"Backend detected listening on {host}:{port} {f'({proc_info})' if proc_info else ''}")
    else:
        step_warn(f"No active service detected listening on {host}:{port} yet. (Nginx will proxy once backend starts)")

    # Backend Executable
    if executable is None and not non_interactive:
        executable = Prompt.ask(
            "[bold cyan]Enter Backend Executable Path / Command[/bold cyan] [dim](optional, e.g. /path/to/venv/bin/uvicorn main:app)[/dim]",
            default="",
        ).strip()
        if not executable:
            executable = None

    if executable:
        valid_exe, exe_msg = PathValidator.validate_executable_path(executable)
        if valid_exe:
            step_success(exe_msg)
        else:
            step_warn(f"{exe_msg} (Proceeding anyway)")

    routes.append(
        RouteConfig(
            name="primary",
            path=route,
            backend_host=host,
            backend_port=port,
            backend_executable=executable,
            websocket=True,
        )
    )

    # 3. Domain Name
    if domain is None and not non_interactive:
        domain = Prompt.ask(
            "[bold cyan]Enter Domain Name[/bold cyan] [dim](optional, leave empty for Public IP / default server)[/dim]",
            default="",
        ).strip()
        if not domain:
            domain = None

    if domain:
        if not DomainValidator.is_valid_domain(domain):
            step_warn(f"Warning: '{domain}' does not follow standard domain syntax. Proceeding.")
        else:
            step_success(f"Domain configured: {domain}")

    # 4. SSL Setup
    if ssl is None:
        if non_interactive:
            ssl = bool(domain)
        else:
            if domain:
                ssl = Confirm.ask(f"[bold cyan]Enable Let's Encrypt SSL (HTTPS) for {domain}?[/bold cyan]", default=True)
            else:
                ssl = False

    if ssl and not domain:
        step_warn("SSL requested without a domain name. Let's Encrypt requires a valid domain. SSL will be disabled.")
        ssl = False

    if ssl and email is None and not non_interactive:
        email = Prompt.ask("[bold cyan]Enter Email for Let's Encrypt Renewal Notifications[/bold cyan] [dim](optional)[/dim]", default="").strip()
        if not email:
            email = None

    # 5. Multi-Service Prompt Loop
    if not non_interactive:
        while True:
            add_more = Confirm.ask("[bold cyan]Do you want to add another backend service / route?[/bold cyan]", default=False)
            if not add_more:
                break

            svc_name = Prompt.ask("  Service Name", default=f"service_{len(routes) + 1}").strip()
            svc_route = Prompt.ask("  Route Path (e.g. /api2/ or /auth/)", default=f"/api{len(routes) + 1}/").strip()
            svc_host = Prompt.ask("  Backend Host / IP", default=host).strip()
            svc_port = IntPrompt.ask("  Backend Port", default=port + len(routes))
            svc_exe = Prompt.ask("  Backend Executable Path (optional)", default="").strip() or None

            routes.append(
                RouteConfig(
                    name=svc_name,
                    path=svc_route,
                    backend_host=svc_host,
                    backend_port=svc_port,
                    backend_executable=svc_exe,
                    websocket=True,
                )
            )
            step_success(f"Added route: {svc_route} ➔ {svc_host}:{svc_port}")

    # Build Server Config
    server_config = ServerConfig(
        project_name=project,
        domain=domain,
        server_name=domain if domain else "_",
        listen_port=80,
        ssl_listen_port=443,
        ssl_enabled=ssl,
        ssl_email=email,
        ssl_redirect=True,
        routes=routes,
    )

    # 6. Preview Config
    rendered_conf = nginx_mgr.render_config(server_config)
    print_config_preview(rendered_conf, title=f"Nginx Configuration Preview: {project}")

    if not non_interactive:
        proceed = Confirm.ask("[bold green]Apply and deploy this configuration?[/bold green]", default=True)
        if not proceed:
            console.print("[yellow]Aborted by user.[/yellow]")
            raise typer.Exit(code=0)

    console.print("\n[bold cyan]🚀 Starting Execution & System Configuration...[/bold cyan]")

    # Step A: Install Dependencies
    install_ok, install_logs = installer.install_missing()
    if install_ok:
        step_success("Nginx and Certbot packages verified and installed.")
    else:
        for log in install_logs:
            step_error(log)
        if not dry_run:
            raise typer.Exit(code=1)

    # Step B: Configure Firewall
    backend_ports = [r.backend_port for r in routes]
    fw_ok, fw_logs = firewall_mgr.open_ports(ports=backend_ports, include_standard_web=True)
    if fw_ok:
        step_success(f"Firewall rules configured (Ports 80, 443, {', '.join(str(p) for p in backend_ports)}).")
    else:
        for log in fw_logs:
            step_warn(log)

    # Step C: SSL Certificates (if enabled)
    if ssl and domain:
        step_info(f"Provisioning SSL certificate for domain: {domain}...")
        cert_ok, cert_logs, cert_path, key_path = ssl_mgr.request_certificate(domain=domain, email=email)
        if cert_ok and cert_path and key_path:
            server_config.ssl_cert_path = cert_path
            server_config.ssl_key_path = key_path
            step_success(f"SSL certificate acquired: {cert_path}")
        else:
            for log in cert_logs:
                step_warn(log)
            step_warn("SSL acquisition failed or skipped. Falling back to HTTP configuration.")
            server_config.ssl_enabled = False

    # Step D: Apply Nginx Config (Write, Validate nginx -t, Rollback on fail, Reload)
    apply_ok, apply_logs, target_file = nginx_mgr.apply_config(server_config)
    if apply_ok:
        step_success(f"Nginx configuration written and validated: {target_file}")
        step_success("Nginx service is running and reloaded.")
    else:
        for log in apply_logs:
            step_error(log)
        step_error("Deployment failed. Automated rollback restored previous state.")
        if not dry_run:
            raise typer.Exit(code=1)

    # Step E: Save Project State to Registry
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project_state = ProjectState(
        project_name=project,
        domain=domain,
        config_file_path=target_file,
        created_at=now_str,
        updated_at=now_str,
        routes=routes,
        ssl_enabled=server_config.ssl_enabled,
    )
    state_mgr.save_project(project_state)
    step_success("Project registered in state store.")

    # Step F: Final Output
    public_ip = DNSHelper.get_public_ip() or "YOUR_SERVER_IP"
    local_ip = DNSHelper.get_local_ip()
    print_success_summary(config=server_config, public_ip=public_ip, target_file=target_file, local_ip=local_ip)


@app.command(name="add-service", help="Add a new route or backend service to an existing Nginx project.")
def add_service(
    project: str = typer.Option(..., "--project", "-p", help="Target project name"),
    path: str = typer.Option(..., "--path", "-r", help="Route path (e.g. /api2/)"),
    port: int = typer.Option(..., "--port", help="Backend port number"),
    host: str = typer.Option("127.0.0.1", "--host", "-H", help="Backend target host/IP (e.g. 127.0.0.1 or LAN IP)"),
    executable: Optional[str] = typer.Option(None, "--executable", "-e", help="Backend executable path"),
    name: Optional[str] = typer.Option(None, "--name", help="Route name identifier"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate without applying"),
):
    """Appends a new route to an existing project configuration."""
    print_banner()
    state_mgr = StateManager()
    project_state = state_mgr.get_project(project)

    if not project_state:
        step_error(f"Project '{project}' not found in registry. Run 'nginx-cli list' to see available projects.")
        raise typer.Exit(code=1)

    if not PortValidator.is_valid_port(port):
        step_error(f"Invalid port: {port}")
        raise typer.Exit(code=1)

    route_name = name or f"route_{len(project_state.routes) + 1}"
    new_route = RouteConfig(
        name=route_name,
        path=path,
        backend_host=host,
        backend_port=port,
        backend_executable=executable,
        websocket=True,
    )

    # Check for duplicate route paths
    for r in project_state.routes:
        if r.path == new_route.path:
            step_warn(f"Overwriting existing route for path '{path}' (previously pointed to {r.backend_host}:{r.backend_port})")
            project_state.routes.remove(r)
            break

    project_state.routes.append(new_route)

    # Open firewall port
    firewall_mgr = FirewallManager(dry_run=dry_run)
    firewall_mgr.open_ports(ports=[port], include_standard_web=False)

    # Re-render & deploy
    nginx_mgr = NginxManager(dry_run=dry_run)
    server_config = ServerConfig(
        project_name=project_state.project_name,
        domain=project_state.domain,
        server_name=project_state.domain if project_state.domain else "_",
        listen_port=project_state.listen_port,
        ssl_listen_port=project_state.ssl_port,
        ssl_enabled=project_state.ssl_enabled,
        routes=project_state.routes,
    )

    apply_ok, logs, target_file = nginx_mgr.apply_config(server_config)
    if apply_ok:
        project_state.updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state_mgr.save_project(project_state)
        step_success(f"Added route '{path}' ➔ {host}:{port} to project '{project}'.")
        public_ip = DNSHelper.get_public_ip() or "YOUR_SERVER_IP"
        local_ip = DNSHelper.get_local_ip()
        print_success_summary(server_config, public_ip, target_file, local_ip=local_ip)
    else:
        for log in logs:
            step_error(log)
        raise typer.Exit(code=1)


@app.command(name="list", help="List all configured projects, routes, domains, and SSL status.")
def list_projects():
    """List all registered projects and routes."""
    print_banner()
    state_mgr = StateManager()
    projects = state_mgr.list_projects()
    print_projects_table(projects)


@app.command(name="status", help="Show system status, OS, Nginx service state, firewall rules, and IPs.")
def status():
    """Show comprehensive status of OS, Nginx service, firewall, and IP."""
    print_banner()
    os_info = OSDetector().detect()
    service_status = ServiceManager().get_nginx_status()
    firewall_info = FirewallManager().detect_firewall()
    public_ip = DNSHelper.get_public_ip()
    local_ip = DNSHelper.get_local_ip()

    from rich.table import Table
    table = Table(title="🔍 System & Environment Diagnostics", border_style="cyan")
    table.add_column("Component", style="bold cyan")
    table.add_column("Status / Value", style="white")

    table.add_row("Operating System", f"{os_info.pretty_name} ({os_info.family.value})")
    table.add_row("Package Manager", os_info.package_manager.value)
    table.add_row("Nginx Config Dir", os_info.nginx_conf_dir)
    table.add_row("Service Manager", os_info.service_manager)
    table.add_row(
        "Nginx Installed",
        "[bold green]Yes[/bold green]" if service_status.is_installed else "[bold red]No[/bold red]",
    )
    table.add_row(
        "Nginx Running",
        "[bold green]Active (Running)[/bold green]" if service_status.is_running else "[bold red]Inactive[/bold red]",
    )
    table.add_row(
        "Nginx Enabled",
        "[bold green]Enabled on boot[/bold green]" if service_status.is_enabled else "[yellow]Disabled[/yellow]",
    )
    table.add_row(
        "Firewall",
        f"{firewall_info.type.value.upper()} ({'[bold green]Active[/bold green]' if firewall_info.is_active else '[yellow]Inactive[/yellow]'})",
    )
    table.add_row("Public IP Address", public_ip or "Unavailable")
    table.add_row("Local Interface IP", local_ip)

    console.print(table)


@app.command(name="preview", help="Preview rendered Nginx configuration without applying to system.")
def preview(
    project: str = typer.Option("demo-app", "--project", "-p", help="Project name"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain name"),
    port: int = typer.Option(8000, "--port", help="Backend port"),
    route: str = typer.Option("/", "--route", "-r", help="Route path"),
    ssl: bool = typer.Option(False, "--ssl/--no-ssl", help="Simulate SSL enabled"),
):
    """Renders the template and displays syntax-highlighted output."""
    print_banner()
    nginx_mgr = NginxManager(dry_run=True)
    config = ServerConfig(
        project_name=project,
        domain=domain,
        server_name=domain if domain else "_",
        listen_port=80,
        ssl_listen_port=443,
        ssl_enabled=ssl,
        routes=[
            RouteConfig(
                name="primary",
                path=route,
                backend_host="127.0.0.1",
                backend_port=port,
                websocket=True,
            )
        ],
    )
    content = nginx_mgr.render_config(config)
    print_config_preview(content, title=f"Dry-Run Preview: {project}")


@app.command(name="test-config", help="Test Nginx configuration syntax with 'nginx -t'.")
def test_config():
    """Run nginx -t validation."""
    print_banner()
    nginx_mgr = NginxManager()
    res = nginx_mgr.test_config()
    if res.success:
        step_success("Nginx configuration syntax is valid.")
        console.print(f"[dim]{res.stderr or res.stdout}[/dim]")
    else:
        step_error("Nginx configuration syntax error:")
        console.print(f"[bold red]{res.stderr or res.stdout}[/bold red]")
        raise typer.Exit(code=1)


@app.command(name="remove", help="Remove an Nginx project configuration and reload Nginx.")
def remove_project(
    project: str = typer.Argument(..., help="Name of the project to remove"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate removal"),
):
    """Remove a virtualhost configuration, rollback on error, and reload Nginx."""
    print_banner()
    state_mgr = StateManager()
    nginx_mgr = NginxManager(dry_run=dry_run)

    step_info(f"Removing project configuration for '{project}'...")
    rem_ok, logs = nginx_mgr.remove_config(project)
    if rem_ok:
        state_mgr.delete_project(project)
        step_success(f"Project '{project}' successfully decommissioned and removed.")
    else:
        for log in logs:
            step_error(log)
        raise typer.Exit(code=1)


def main():
    app()


if __name__ == "__main__":
    main()
