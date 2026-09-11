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
    print_nginx_inspection_table,
    print_projects_table,
    print_success_summary,
    print_systemd_services_table,
    step_error,
    step_info,
    step_success,
    step_warn,
)
from core.firewall_manager import FirewallManager
from core.installer import PackageInstaller
from core.nginx_inspector import NginxInspector
from core.nginx_manager import NginxManager
from core.os_detector import OSDetector
from core.service_manager import ServiceManager
from core.ssl_manager import SSLManager
from models.server_config import (
    ProjectState,
    RouteConfig,
    ServerConfig,
    SystemdServiceConfig,
    SystemdServiceState,
)
from utils.dns import DNSHelper
from utils.storage import StateManager
from utils.validator import DomainValidator, PathValidator, PortValidator

app = typer.Typer(
    name="nginx-cli",
    help="Production-Grade Nginx + SSL + Firewall Automation CLI for FastAPI & Backend Services.",
    add_completion=False,
)


def _normalize_bool(val: object, default: bool = False) -> bool:
    """Safely convert Typer OptionInfo or raw boolean to a Python bool."""
    if isinstance(val, bool):
        return val
    try:
        from typer.models import OptionInfo
        if isinstance(val, OptionInfo):
            if isinstance(val.default, bool):
                return val.default
            return default
    except Exception:
        pass
    return default


@app.command(name="setup", help="Interactively configure and deploy Nginx reverse proxy with SSL and Firewall rules.")
def setup(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (e.g. fastapi-app)"),
    executable: Optional[str] = typer.Option(None, "--executable", "-e", help="Backend executable path/command"),
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Backend host/IP (e.g. 127.0.0.1, 0.0.0.0, or LAN IP)"),
    port: Optional[int] = typer.Option(None, "--port", help="Backend port number (e.g. 8000)"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain name (optional, e.g. api.example.com)"),
    route: Optional[str] = typer.Option(None, "--route", "-r", help="Nginx route location path (default: /)"),
    ssl: Optional[bool] = typer.Option(None, "--ssl/--no-ssl", help="Enable SSL HTTPS certificate"),
    self_signed: bool = typer.Option(False, "--self-signed", "--ssl-ip", help="Use OpenSSL Self-Signed certificate with IP SAN for Public/LAN IP"),
    email: Optional[str] = typer.Option(None, "--email", "-m", help="Email for Let's Encrypt notifications"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without modifying system files"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-y", help="Run non-interactively with provided flags"),
):
    """Guided wizard to set up Nginx reverse proxy, Certbot SSL, firewall, and multi-service routing."""
    dry_run = _normalize_bool(dry_run, default=False)
    non_interactive = _normalize_bool(non_interactive, default=False)
    self_signed = _normalize_bool(self_signed, default=False)
    if not isinstance(ssl, bool):
        ssl = None

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
            "[bold cyan]Enter Domain Name[/bold cyan] [dim](optional, e.g. api.example.com - leave empty if using IP/LAN)[/dim]",
            default="",
        ).strip()
        if not domain:
            domain = None

    if domain:
        if not DomainValidator.is_valid_domain(domain):
            step_warn(f"Warning: '{domain}' does not follow standard domain syntax. Proceeding.")
        else:
            step_success(f"Domain configured: {domain}")

    # 4. SSL Setup Prompt
    ssl_type = "self-signed" if self_signed else "letsencrypt"
    if ssl is None:
        if non_interactive:
            ssl = bool(domain) or self_signed
        else:
            ssl = Confirm.ask("[bold cyan]Enable SSL (HTTPS) Certificate?[/bold cyan]", default=bool(domain) or self_signed)
            if ssl:
                if domain:
                    console.print("\n[bold cyan]Select SSL Provider:[/bold cyan]")
                    console.print(f"  [bold]1.[/bold] 🌐 [bold]Let's Encrypt SSL[/bold] (Trusted, Auto-renewing for domain '{domain}')")
                    console.print(f"  [bold]2.[/bold] 🔒 [bold]Self-Signed SSL[/bold] (OpenSSL with SAN for IP / Local testing)")
                    ssl_opt = Prompt.ask("Choose SSL type", choices=["1", "2"], default="1")
                    ssl_type = "letsencrypt" if ssl_opt == "1" else "self-signed"
                else:
                    public_ip = DNSHelper.get_public_ip() or DNSHelper.get_local_ip()
                    console.print(f"\n[bold cyan]No domain entered. You can use a Self-Signed SSL certificate for your Public/LAN IP ({public_ip}):[/bold cyan]")
                    console.print("  [bold]1.[/bold] 🔒 [bold]Self-Signed SSL for IP[/bold] (OpenSSL with SAN IP)")
                    console.print("  [bold]2.[/bold] 🌐 [bold]Enter Domain for Let's Encrypt SSL[/bold]")
                    console.print("  [bold]3.[/bold] ❌ [bold]Disable SSL (HTTP only)[/bold]")
                    ssl_opt = Prompt.ask("Choose SSL option", choices=["1", "2", "3"], default="1")

                    if ssl_opt == "1":
                        ssl_type = "self-signed"
                    elif ssl_opt == "2":
                        domain = Prompt.ask("Enter Domain Name for Let's Encrypt (e.g. api.example.com)").strip()
                        if domain and DomainValidator.is_valid_domain(domain):
                            ssl_type = "letsencrypt"
                            step_success(f"Domain configured: {domain}")
                        else:
                            step_warn("Invalid domain. Falling back to Self-Signed IP SSL.")
                            ssl_type = "self-signed"
                            domain = None
                    else:
                        ssl = False

    if ssl and ssl_type == "letsencrypt" and email is None and not non_interactive:
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
        ssl_type=ssl_type,
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
    if ssl:
        if ssl_type == "self-signed":
            target_ip = domain or DNSHelper.get_public_ip() or DNSHelper.get_local_ip() or "127.0.0.1"
            step_info(f"Generating Self-Signed SSL Certificate with IP SAN for {target_ip}...")
            cert_ok, cert_logs, cert_path, key_path = ssl_mgr.generate_ip_self_signed_cert(
                ip_address=target_ip, project_name=project
            )
            if cert_ok and cert_path and key_path:
                server_config.ssl_cert_path = cert_path
                server_config.ssl_key_path = key_path
                step_success(f"Self-Signed SSL certificate generated: {cert_path}")
            else:
                for log in cert_logs:
                    step_warn(log)
                server_config.ssl_enabled = False
        elif domain:
            step_info(f"Provisioning Let's Encrypt SSL certificate for domain: {domain}...")
            cert_ok, cert_logs, cert_path, key_path = ssl_mgr.request_certificate(domain=domain, email=email)
            if cert_ok and cert_path and key_path:
                server_config.ssl_cert_path = cert_path
                server_config.ssl_key_path = key_path
                step_success(f"Let's Encrypt SSL certificate acquired: {cert_path}")
            else:
                for log in cert_logs:
                    step_warn(log)
                step_warn("SSL acquisition failed or skipped. Falling back to HTTP configuration.")
                server_config.ssl_enabled = False

    # Step D: Configure SELinux (for RHEL / Rocky / CentOS / Fedora)
    selinux_ok, selinux_msg = service_mgr.configure_selinux_for_nginx()
    if "Enabled" in selinux_msg or "already enabled" in selinux_msg:
        step_success(f"SELinux: {selinux_msg}")

    # Step E: Apply Nginx Config (Write, Validate nginx -t, Rollback on fail, Reload)
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
    dry_run = _normalize_bool(dry_run, default=False)
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
    """Show comprehensive status of OS, Nginx service, firewall, IP, and active Nginx virtual hosts."""
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

    # Scan and display all active system Nginx configurations & listening ports
    inspector = NginxInspector()
    scan = inspector.scan_all_configs()
    console.print()
    print_nginx_inspection_table(scan)


@app.command(name="preview", help="Preview rendered Nginx configuration without applying to system.")
def preview(
    project: str = typer.Option("demo-app", "--project", "-p", help="Project name"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain name"),
    port: int = typer.Option(8000, "--port", help="Backend port"),
    route: str = typer.Option("/", "--route", "-r", help="Route path"),
    ssl: bool = typer.Option(False, "--ssl/--no-ssl", help="Simulate SSL enabled"),
):
    """Renders the template and displays syntax-highlighted output."""
    ssl = _normalize_bool(ssl, default=False)
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
    project: str = typer.Argument(..., help="Project Code (e.g. SE-001) or name of the project to remove"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate removal"),
):
    """Remove a virtualhost configuration by Project Code or name, delete state, and reload Nginx."""
    dry_run = _normalize_bool(dry_run, default=False)
    print_banner()
    state_mgr = StateManager()
    nginx_mgr = NginxManager(dry_run=dry_run)
    inspector = NginxInspector()

    # 1. Resolve project by Project Code, name, or index
    project_state = state_mgr.get_project(project)
    if project_state:
        target_name = project_state.project_name
        target_code = project_state.project_code
        target_conf = project_state.config_file_path
        ports_used = [r.backend_port for r in project_state.routes]
        step_info(f"Removing Project CODE: [bold green]{target_code}[/bold green] | [bold cyan]{target_name}[/bold cyan] ({target_conf})...")
    else:
        target_name = project
        target_code = None
        target_conf = None
        ports_used = []
        step_info(f"Removing project configuration for '{project}'...")

    # 2. Remove configuration files and reload
    rem_ok, logs = nginx_mgr.remove_config(target_name, config_file_path=target_conf)
    for log in logs:
        if "Removed" in log or "reloaded" in log:
            step_success(log)
        elif "Warning" in log:
            step_warn(log)
        else:
            step_info(log)

    # 3. Always remove from SQLite registry
    state_mgr.delete_project(project)
    if target_code:
        state_mgr.delete_project(target_code)
    if target_name:
        state_mgr.delete_project(target_name)

    step_success(f"Project '{project}' successfully decommissioned and removed from database.")


@app.command(name="inspect", help="Deep scan and inspect active Nginx virtual hosts, listening ports, and proxy targets in nginx.conf and conf.d.")
def inspect_configs():
    """Scan /etc/nginx/nginx.conf, conf.d/, sites-enabled/, and detect all active ports."""
    print_banner()
    inspector = NginxInspector()
    scan = inspector.scan_all_configs()
    print_nginx_inspection_table(scan)

    # Also detect listening network sockets
    if scan.all_listening_ports:
        console.print("\n[bold cyan]🔌 Network Port Listening Status:[/bold cyan]")
        for p in scan.all_listening_ports:
            is_listening = PortValidator.is_port_listening(p)
            proc = PortValidator.get_process_using_port(p)
            if is_listening:
                step_success(f"Port {p} is actively listening {f'({proc})' if proc else ''}")
            else:
                step_info(f"Port {p} configured in Nginx (socket idle or waiting for traffic)")


@app.command(name="enable-ssl", help="Enable or upgrade SSL for an existing project by Project Code (e.g. SE-001) or name.")
def enable_ssl(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project Code (e.g. SE-001) or project name"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain name for Let's Encrypt (optional)"),
    self_signed: bool = typer.Option(False, "--self-signed", "--ssl-ip", help="Use OpenSSL Self-Signed certificate with IP SAN for Public/LAN IP"),
    email: Optional[str] = typer.Option(None, "--email", "-m", help="Email for Let's Encrypt renewal notifications"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without modifying system files"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-y", help="Run non-interactively with provided flags"),
):
    """Enable or reconfigure SSL certificate on an existing project by Project Code (e.g. SE-001) or name."""
    dry_run = _normalize_bool(dry_run, default=False)
    non_interactive = _normalize_bool(non_interactive, default=False)
    self_signed = _normalize_bool(self_signed, default=False)

    print_banner()
    state_mgr = StateManager()
    projects = state_mgr.list_projects()

    if not projects:
        step_warn("No projects found in registry. Please run Setup (Option 1) first.")
        if not non_interactive and Confirm.ask("Do you want to run Setup now?", default=True):
            setup(dry_run=dry_run)
        return

    # If project not supplied, display projects and prompt by Project Code
    if not project:
        if non_interactive:
            project_state = projects[0]
            project = project_state.project_code
        else:
            console.print("\n[bold cyan]Registered Projects:[/bold cyan]")
            for idx, p in enumerate(projects, 1):
                ssl_status = f"[green]✔ {p.ssl_type.title()}[/green]" if p.ssl_enabled else "[yellow]✖ Disabled[/yellow]"
                console.print(
                    f"  [bold cyan]{idx}.[/bold cyan] Project CODE: [bold green]{p.project_code}[/bold green] | "
                    f"[bold white]{p.project_name}[/bold white] (Host: {p.domain or 'IP'}, SSL: {ssl_status})"
                )
            console.print()
            default_code = projects[0].project_code
            proj_choice = Prompt.ask(
                "[bold cyan]Enter Project CODE (e.g. SE-001) or Project Name[/bold cyan]",
                default=default_code,
            ).strip()
            project = proj_choice

    project_state = state_mgr.get_project(project)
    if not project_state:
        step_error(f"Project '{project}' not found in registry. Run 'nginx-cli list' to see valid project codes.")
        raise typer.Exit(code=1)

    step_info(f"Configuring SSL for Project CODE: [bold green]{project_state.project_code}[/bold green] ({project_state.project_name})")

    # SSL Provider Choice
    ssl_mgr = SSLManager(dry_run=dry_run)
    firewall_mgr = FirewallManager(dry_run=dry_run)
    nginx_mgr = NginxManager(dry_run=dry_run)

    ssl_type = "self-signed" if self_signed else "letsencrypt"
    target_domain = domain or project_state.domain

    if not non_interactive:
        console.print("\n[bold cyan]Select SSL Configuration Type:[/bold cyan]")
        console.print("  [bold]1.[/bold] 🌐 [bold]Let's Encrypt SSL[/bold] (Trusted, Auto-renewing for domain)")
        console.print("  [bold]2.[/bold] 🔒 [bold]Self-Signed SSL for Public / LAN IP[/bold] (OpenSSL with SAN IP)")

        default_choice = "2" if not target_domain else "1"
        choice = Prompt.ask("Choose SSL option", choices=["1", "2"], default=default_choice)

        if choice == "1":
            ssl_type = "letsencrypt"
            if not target_domain:
                target_domain = Prompt.ask("Enter Domain Name for Let's Encrypt (e.g. api.example.com)").strip()
                if not DomainValidator.is_valid_domain(target_domain):
                    step_warn("Invalid domain syntax. Falling back to Self-Signed IP SSL.")
                    ssl_type = "self-signed"
                    target_domain = None
            if ssl_type == "letsencrypt" and not email:
                email = Prompt.ask("[bold cyan]Enter Email for Renewal Notifications[/bold cyan] [dim](optional)[/dim]", default="").strip() or None
        else:
            ssl_type = "self-signed"

    # Provision Certificate
    cert_path = None
    key_path = None

    if ssl_type == "self-signed":
        target_ip = target_domain or DNSHelper.get_public_ip() or DNSHelper.get_local_ip() or "127.0.0.1"
        step_info(f"Generating Self-Signed SSL Certificate with IP SAN for {target_ip}...")
        cert_ok, cert_logs, cert_path, key_path = ssl_mgr.generate_ip_self_signed_cert(
            ip_address=target_ip, project_name=project_state.project_name
        )
        if not cert_ok or not cert_path or not key_path:
            for log in cert_logs:
                step_error(log)
            raise typer.Exit(code=1)
        step_success(f"Self-Signed SSL certificate generated: {cert_path}")
    else:
        if not target_domain:
            step_error("Domain name is required for Let's Encrypt SSL.")
            raise typer.Exit(code=1)
        step_info(f"Requesting Let's Encrypt SSL certificate for domain '{target_domain}'...")
        cert_ok, cert_logs, cert_path, key_path = ssl_mgr.request_certificate(domain=target_domain, email=email)
        if not cert_ok or not cert_path or not key_path:
            for log in cert_logs:
                step_error(log)
            raise typer.Exit(code=1)
        step_success(f"Let's Encrypt SSL certificate acquired: {cert_path}")

    # Open Firewall Port 443
    fw_ok, fw_logs = firewall_mgr.open_ports(ports=[443], include_standard_web=True)
    if fw_ok:
        step_success("Firewall: Port 443 (HTTPS) opened.")
    else:
        for log in fw_logs:
            step_warn(log)

    # Build and Apply Updated ServerConfig
    server_config = ServerConfig(
        project_name=project_state.project_name,
        domain=target_domain,
        server_name=target_domain if target_domain else "_",
        listen_port=project_state.listen_port,
        ssl_listen_port=project_state.ssl_port,
        ssl_enabled=True,
        ssl_type=ssl_type,
        ssl_email=email,
        ssl_cert_path=cert_path,
        ssl_key_path=key_path,
        ssl_redirect=True,
        routes=project_state.routes,
    )

    apply_ok, apply_logs, target_file = nginx_mgr.apply_config(server_config)
    if apply_ok:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        project_state.ssl_enabled = True
        project_state.ssl_type = ssl_type
        project_state.ssl_cert_path = cert_path
        project_state.ssl_key_path = key_path
        project_state.ssl_email = email
        project_state.domain = target_domain
        project_state.updated_at = now_str
        state_mgr.save_project(project_state)

        step_success(f"SSL successfully enabled for Project CODE: [bold green]{project_state.project_code}[/bold green] ({project_state.project_name})")
        public_ip = DNSHelper.get_public_ip() or "YOUR_SERVER_IP"
        local_ip = DNSHelper.get_local_ip()
        print_success_summary(config=server_config, public_ip=public_ip, target_file=target_file, local_ip=local_ip)
    else:
        for log in apply_logs:
            step_error(log)
        raise typer.Exit(code=1)


@app.command(name="service-setup", help="Configure, install, and auto-enable a systemd service unit to run on boot.")
def service_setup(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Service unit name (e.g. fastapi)"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="Service description"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Execution user (e.g. nginx, root)"),
    working_dir: Optional[str] = typer.Option(None, "--working-dir", "-w", help="Working directory path"),
    exec_start: Optional[str] = typer.Option(None, "--exec", "-e", help="ExecStart startup command"),
    restart: str = typer.Option("always", "--restart", help="Restart policy (always, on-failure)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without modifying system"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-y", help="Run non-interactively"),
):
    """Interactively generate systemd unit file, enable on boot, and start the service."""
    dry_run = _normalize_bool(dry_run, default=False)
    non_interactive = _normalize_bool(non_interactive, default=False)
    print_banner()

    if not name:
        if non_interactive:
            name = "fastapi"
        else:
            name = Prompt.ask("[bold cyan]Enter Service Name[/bold cyan] [dim](e.g. fastapi)[/dim]", default="fastapi").strip()

    if not description:
        if non_interactive:
            description = "FastAPI App"
        else:
            description = Prompt.ask("[bold cyan]Enter Service Description[/bold cyan]", default="FastAPI App").strip()

    if not user:
        if non_interactive:
            user = "nginx"
        else:
            user = Prompt.ask("[bold cyan]Enter Execution User[/bold cyan] [dim](e.g. nginx, root, www-data)[/dim]", default="nginx").strip()

    if not working_dir:
        default_dir = os.getcwd()
        if non_interactive:
            working_dir = default_dir
        else:
            working_dir = Prompt.ask("[bold cyan]Enter Working Directory[/bold cyan]", default=default_dir).strip()

    if not exec_start:
        if non_interactive:
            exec_start = "/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000"
        else:
            exec_start = Prompt.ask(
                "[bold cyan]Enter ExecStart Command[/bold cyan]",
                default="/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000",
            ).strip()

    config = SystemdServiceConfig(
        service_name=name,
        description=description,
        user=user,
        working_dir=working_dir,
        exec_start=exec_start,
        restart=restart,
    )

    service_mgr = ServiceManager(dry_run=dry_run)
    state_mgr = StateManager()

    step_info(f"Generating systemd service unit '/etc/systemd/system/{config.service_name}.service'...")
    success, logs, unit_path = service_mgr.create_systemd_service(config)

    for log in logs:
        if "written" in log or "started" in log or "Enabled" in log or "Executed" in log:
            step_success(log)
        elif "Warning" in log:
            step_warn(log)
        else:
            step_info(log)

    if success or dry_run:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state_obj = SystemdServiceState(
            service_name=config.service_name,
            description=config.description,
            user=config.user,
            working_dir=config.working_dir,
            exec_start=config.exec_start,
            restart=config.restart,
            service_file_path=unit_path,
            created_at=now_str,
            updated_at=now_str,
            is_enabled=True,
            is_active=True,
        )
        state_mgr.save_service(state_obj)
        step_success(f"Systemd service [bold green]{config.service_name}.service[/bold green] successfully deployed & enabled for boot autostart.")
    else:
        step_error(f"Failed to configure systemd service unit {config.service_name}.service")


@app.command(name="service-list", help="List and inspect all managed systemd services and their live status.")
def service_list():
    """List all managed systemd background services and their live status."""
    print_banner()
    state_mgr = StateManager()
    service_mgr = ServiceManager()

    services = state_mgr.list_services()
    if not services:
        console.print("[yellow]No managed systemd services found in registry.[/yellow]")
        return

    enriched = []
    for s in services:
        live = service_mgr.get_systemd_service_status(s.service_name)
        enriched.append({
            "service_name": s.service_name,
            "description": s.description,
            "user": s.user,
            "working_dir": s.working_dir,
            "exec_start": s.exec_start,
            "is_active": live.get("is_active", False),
            "is_enabled": live.get("is_enabled", False),
            "active_state": live.get("active_state", "unknown"),
            "service_file_path": s.service_file_path,
        })

    print_systemd_services_table(enriched)


@app.command(name="service-remove", help="Stop, disable, and decommission a systemd service unit.")
def service_remove(
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Service name or index to remove"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without modifying system files"),
    non_interactive: bool = typer.Option(False, "--non-interactive", "-y", help="Run non-interactively"),
):
    """Stop, disable boot autostart, delete unit file, and daemon-reload a systemd service."""
    dry_run = _normalize_bool(dry_run, default=False)
    non_interactive = _normalize_bool(non_interactive, default=False)
    print_banner()

    state_mgr = StateManager()
    services = state_mgr.list_services()

    if not service:
        if not services:
            step_warn("No systemd services found in registry to remove.")
            return
        console.print("\n[bold cyan]Select Systemd Service to Remove:[/bold cyan]")
        for idx, s in enumerate(services, 1):
            console.print(f"  [bold cyan]{idx}.[/bold cyan] [bold white]{s.service_name}.service[/bold white] ({s.description}) - [dim]{s.service_file_path}[/dim]")
        if non_interactive:
            service = services[0].service_name
        else:
            service = Prompt.ask("Enter Service Name or Number to remove").strip()

    target_svc = state_mgr.get_service(service)
    target_name = target_svc.service_name if target_svc else service

    if not non_interactive:
        if not Confirm.ask(f"[bold red]Are you sure you want to stop, disable, and remove service '{target_name}.service'?[/bold red]", default=False):
            console.print("[yellow]Service removal cancelled.[/yellow]")
            return

    step_info(f"Decommissioning service '{target_name}.service'...")
    service_mgr = ServiceManager(dry_run=dry_run)
    ok, logs = service_mgr.remove_systemd_service(target_name)

    for log in logs:
        if "Stopped" in log or "Disabled" in log or "Removed" in log or "Executed" in log:
            step_success(log)
        elif "Warning" in log:
            step_warn(log)
        else:
            step_info(log)

    state_mgr.delete_service(target_name)
    step_success(f"Systemd service '{target_name}.service' removed, boot autostart disabled, and daemon reloaded.")


@app.command(name="service-control", help="Control a managed systemd service (start, stop, restart, status, logs).")
def service_control(
    service: str = typer.Option(..., "--service", "-s", help="Service name"),
    action: str = typer.Option(..., "--action", "-a", help="Action: start, stop, restart, status, logs"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without modifying system"),
):
    """Perform lifecycle actions on a managed systemd unit."""
    dry_run = _normalize_bool(dry_run, default=False)
    service_mgr = ServiceManager(dry_run=dry_run)
    ok, out = service_mgr.control_systemd_service(service, action)
    if ok:
        console.print(f"[bold green]{out}[/bold green]")
    else:
        console.print(f"[bold red]{out}[/bold red]")


@app.command(name="menu", help="Launch interactive numbered menu.")
def menu():
    """Launch the interactive numbered menu."""
    interactive_menu()


def interactive_menu():
    """Main interactive menu allowing users to select actions by number."""
    while True:
        print_banner()
        console.print("[bold yellow]Please select an action by number:[/bold yellow]\n")
        console.print("  [bold cyan]1.[/bold cyan] 🚀 [bold]Setup New Reverse Proxy[/bold] [dim](Interactive Wizard)[/dim]")
        console.print("  [bold cyan]2.[/bold cyan] ➕ [bold]Add Service / Route[/bold] [dim](Append route to existing project)[/dim]")
        console.print("  [bold cyan]3.[/bold cyan] 🔒 [bold]Enable / Upgrade SSL for Project[/bold] [dim](by Project CODE: SE-001)[/dim]")
        console.print("  [bold cyan]4.[/bold cyan] 📋 [bold]List Registered Projects & Routes[/bold]")
        console.print("  [bold cyan]5.[/bold cyan] ⚙️  [bold]Create & Auto-Enable Systemd Service[/bold] [dim](Start on Boot / Reboot)[/dim]")
        console.print("  [bold cyan]6.[/bold cyan] 📑 [bold]List & Monitor Managed Systemd Services[/bold]")
        console.print("  [bold cyan]7.[/bold cyan] 🗑️  [bold]Remove / Decommission a Systemd Service[/bold]")
        console.print("  [bold cyan]8.[/bold cyan] 🔍 [bold]Inspect Active Nginx Virtual Hosts & Ports[/bold] [dim](nginx.conf & conf.d)[/dim]")
        console.print("  [bold cyan]9.[/bold cyan] 🩺 [bold]System Status & Diagnostics[/bold]")
        console.print("  [bold cyan]10.[/bold cyan] 🔍 [bold]Preview Nginx Configuration[/bold] [dim](Dry-run)[/dim]")
        console.print("  [bold cyan]11.[/bold cyan] 🧪 [bold]Test Nginx Configuration Syntax[/bold] [dim](nginx -t)[/dim]")
        console.print("  [bold cyan]12.[/bold cyan] 🗑️  [bold]Remove / Decommission an Nginx Project[/bold]")
        console.print("  [bold cyan]13.[/bold cyan] ❌ [bold red]Exit[/bold red]\n")

        choice = Prompt.ask("[bold green]Enter option number[/bold green] [1-13]", default="1").strip()

        if choice == "1":
            setup(dry_run=False, non_interactive=False)
            break
        elif choice == "2":
            state_mgr = StateManager()
            projects = state_mgr.list_projects()
            if not projects:
                step_warn("No projects found in registry. Please run Setup (Option 1) first.")
                if not Confirm.ask("Do you want to run Setup now?", default=True):
                    continue
                setup(dry_run=False, non_interactive=False)
                break

            console.print("\n[bold cyan]Configured Projects:[/bold cyan]")
            for idx, p in enumerate(projects, 1):
                console.print(f"  [bold cyan]{idx}.[/bold cyan] Project CODE: [bold green]{p.project_code}[/bold green] | [bold white]{p.project_name}[/bold white] ({p.domain or 'IP'})")

            proj_choice = Prompt.ask("Select Project CODE (e.g. SE-001) or number", default=projects[0].project_code).strip()
            if proj_choice.isdigit() and 1 <= int(proj_choice) <= len(projects):
                target_proj = projects[int(proj_choice) - 1].project_code
            else:
                target_proj = proj_choice

            path = Prompt.ask("Enter Route Path (e.g. /api2/)", default="/api2/").strip()
            port = IntPrompt.ask("Enter Backend Port (e.g. 8002)", default=8002)
            host = Prompt.ask("Enter Backend Host / IP", default="127.0.0.1").strip()
            add_service(project=target_proj, path=path, port=port, host=host, dry_run=False)
            break
        elif choice == "3":
            enable_ssl(dry_run=False, non_interactive=False)
            break
        elif choice == "4":
            list_projects()
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "5":
            service_setup(dry_run=False, non_interactive=False)
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "6":
            service_list()
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "7":
            service_remove(dry_run=False, non_interactive=False)
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "8":
            inspect_configs()
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "9":
            status()
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "10":
            proj = Prompt.ask("Project name", default="demo-app").strip()
            dom = Prompt.ask("Domain (optional, leave empty for IP)", default="").strip() or None
            pt = IntPrompt.ask("Backend port", default=8000)
            rt = Prompt.ask("Route path", default="/").strip()
            use_ssl = Confirm.ask("Enable SSL in preview?", default=bool(dom))
            preview(project=proj, domain=dom, port=pt, route=rt, ssl=use_ssl)
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "11":
            test_config()
            if not Confirm.ask("\nReturn to main menu?", default=True):
                break
        elif choice == "12":
            state_mgr = StateManager()
            projects = state_mgr.list_projects()
            if not projects:
                step_warn("No projects found in registry to remove.")
                continue

            console.print("\n[bold cyan]Select Project to Remove:[/bold cyan]")
            for idx, p in enumerate(projects, 1):
                console.print(f"  [bold cyan]{idx}.[/bold cyan] Project CODE: [bold green]{p.project_code}[/bold green] | [bold white]{p.project_name}[/bold white] ({p.config_file_path})")

            rem_choice = Prompt.ask("Enter Project CODE (e.g. SE-001) or Name to remove").strip()
            target_obj = state_mgr.get_project(rem_choice)
            target_rem = target_obj.project_name if target_obj else rem_choice

            if Confirm.ask(f"[bold red]Are you sure you want to remove project '{target_rem}'?[/bold red]", default=False):
                remove_project(project=target_rem, dry_run=False)
            break
        elif choice in ("13", "0", "exit", "q", "quit"):
            console.print("[yellow]Goodbye![/yellow]")
            break
        else:
            step_error(f"Invalid option '{choice}'. Please enter a number from 1 to 13.")


@app.callback(invoke_without_command=True)
def default_callback(ctx: typer.Context):
    """Nginx + SSL DevOps Automation Suite."""
    if ctx.invoked_subcommand is None:
        interactive_menu()


def main():
    app()


if __name__ == "__main__":
    main()

