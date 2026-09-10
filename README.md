# ⚡ Nginx + SSL DevOps Automation Suite (`nginx-cli`)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Nginx](https://img.shields.io/badge/nginx-%23009639.svg?logo=nginx&logoColor=white)](https://nginx.org)
[![Let's Encrypt](https://img.shields.io/badge/Let's%20Encrypt-003A70?logo=letsencrypt&logoColor=white)](https://letsencrypt.org)

Production-grade, extensible CLI automation tool that configures **Nginx Reverse Proxies**, provisions **Let's Encrypt SSL certificates (Certbot)**, manages **Firewall rules (UFW, Firewalld, iptables)**, supports **multi-service routing**, and ensures zero-downtime reloads with **automated backups & rollback**.

---

## 🎯 Features

- 🐧 **Automatic OS Detection**: Intelligently identifies Linux distribution (`Ubuntu/Debian`, `Rocky/CentOS/RHEL/AlmaLinux`, `Arch/CachyOS/Manjaro`, `Alpine`, `openSUSE`) and applies the correct Nginx directories (`sites-available` / `conf.d` / `http.d`).
- 📦 **Automated Dependency Provisioning**: Detects and installs `nginx`, `certbot`, and `certbot-nginx` via the native package manager (`apt`, `dnf`, `pacman`, `apk`, `zypper`).
- 🧙‍♂️ **Interactive Guided Wizard**: Step-by-step wizard prompting for project name, backend paths, ports, domains, routes, and SSL.
- 🔒 **Automated SSL (HTTPS)**: Validates DNS propagation, requests certificates via Certbot, configures Mozilla Intermediate TLS ciphers, HTTP/2, OCSP stapling, and 301 HTTP-to-HTTPS redirect.
- 🛡️ **Firewall Management**: Automatically detects active firewalls (`ufw`, `firewalld`, `iptables`) and opens required web (`80`, `443`) and backend ports.
- 🔀 **Multi-Service Microservice Routing**: Mount multiple backend applications on different route prefixes (e.g. `/` ➔ `:8000`, `/api/` ➔ `:8001`, `/auth/` ➔ `:8002`).
- ⚡ **WebSockets & Buffer Tuning**: Built-in WebSocket upgrade headers (`Upgrade`, `Connection "upgrade"`), optimized proxy buffers, and timeouts.
- 🛡️ **Safety, Backups & Instant Rollback**: Atomic writes with timestamped backups (`.bak.<timestamp>`). Automatically executes `nginx -t` validation and rolls back immediately if syntax errors occur.
- 🧪 **Dry-Run & Preview**: Live syntax-highlighted Nginx configuration preview before applying changes.

---

## 🧱 Project Architecture

```
Nginx_Setup/
├── cli/
│   ├── __init__.py
│   ├── main.py              # Typer CLI entrypoint & commands
│   └── ui.py                # Rich UI formatting, banners, tables, indicators
├── core/
│   ├── __init__.py
│   ├── os_detector.py       # OS detection (/etc/os-release) & path configuration
│   ├── installer.py         # Multi-distro package installer
│   ├── nginx_manager.py     # Jinja2 rendering, atomic writes, validation, rollback & reload
│   ├── ssl_manager.py       # Certbot SSL certificate automation & DNS verification
│   ├── firewall_manager.py  # UFW, Firewalld, and iptables port manager
│   └── service_manager.py   # Systemd service lifecycle management & backend unit generator
├── scripts/
│   ├── install_dependencies.sh  # Standalone distro package installer (Nginx, Certbot)
│   ├── configure_firewall.sh    # Standalone firewall port configuration (UFW, Firewalld, iptables)
│   ├── setup_ssl.sh             # Standalone Certbot Let's Encrypt automated setup
│   ├── nginx_health_check.sh    # Comprehensive Nginx & reverse proxy health checker
│   └── backup_restore.sh        # Nginx configuration snapshot backup & restore utility
├── models/
│   ├── __init__.py
│   └── server_config.py     # Pydantic v2 schemas and validation models
├── templates/
│   └── nginx.conf.j2        # Production-grade Nginx Jinja2 template
├── utils/
│   ├── __init__.py
│   ├── system.py            # Subprocess execution, dry-run support, sudo handler
│   ├── backup.py            # Timestamped backup & safe rollback manager
│   ├── validator.py         # Network ports, executables, domains, and route validators
│   ├── dns.py               # Public IP detection & DNS A-record resolution checker
│   └── storage.py           # Persistent SQLite project registry (ACID compliant, survives VM reboots)
├── tests/                   # Comprehensive pytest unit and integration test suite
├── nginx-cli                # Executable launcher script
├── pyproject.toml           # Python package configuration
├── requirements.txt         # Dependencies
└── README.md
```

---

## 🚀 Installation & Quickstart

### Prerequisites
- Python 3.9+
- Linux Operating System (Ubuntu, Debian, Rocky, RHEL, CentOS, Arch, CachyOS, Alpine, openSUSE)

### 1. Clone & Setup
```bash
git clone https://github.com/Script-By-Lin/Nginx-Setup.git
cd Nginx-Setup

# Install dependencies
pip install -r requirements.txt
```

### 2. Make CLI Executable
```bash
chmod +x ./nginx-cli
```

---

## 💻 CLI Commands & Usage

### 🎯 Interactive Numbered Menu Mode (Easiest)
Simply run `./nginx-cli` without arguments (or `./nginx-cli menu`) to open the interactive menu where you can select any action by entering a number:

```bash
./nginx-cli
```

```text
╭─────────────────────────────────────────────────────────────────╮
│ ⚡ Nginx + SSL DevOps Automation Suite ⚡                       │
│ Production-Grade Reverse Proxy, Certbot SSL, & Firewall Manager │
╰─────────────────────────────────────────────────────────────────╯

Please select an action by number:

  1. 🚀 Setup New Reverse Proxy (Interactive Wizard)
  2. ➕ Add Service / Route (Append route to existing project)
  3. 🔒 Enable / Upgrade SSL for Project (by Project CODE: SE-001)
  4. 📋 List Registered Projects & Routes
  5. 🩺 System Status & Diagnostics
  6. 🔍 Preview Nginx Configuration (Dry-run)
  7. 🧪 Test Nginx Configuration Syntax (nginx -t)
  8. 🗑️  Remove / Decommission a Project
  9. ❌ Exit

Enter option number [1-9]: 3
```

---

### 1. Interactive Setup Wizard (`setup`)
Run the interactive wizard directly:
```bash
./nginx-cli setup
```

#### Non-Interactive / Scripted Mode
Automate deployments with flags:
```bash
# Domain with Let's Encrypt SSL
sudo ./nginx-cli setup \
  --project fastapi-prod \
  --domain api.example.com \
  --port 8000 \
  --route / \
  --ssl \
  --email admin@example.com \
  --non-interactive

# Public IP / LAN IP with Self-Signed SSL (HTTPS on port 443)
sudo ./nginx-cli setup \
  --project ip-app \
  --host 0.0.0.0 \
  --port 8000 \
  --route / \
  --ssl \
  --self-signed \
  --non-interactive

# IP-Only / Local Proxy (HTTP only, without SSL)
sudo ./nginx-cli setup \
  --project internal-app \
  --port 8001 \
  --route / \
  --no-ssl \
  --non-interactive
```

---

### 2. Add Service / Route (`add-service`)
Append another backend service or route prefix to an existing project configuration:
```bash
sudo ./nginx-cli add-service \
  --project SE-001 \
  --path /api2/ \
  --port 8002
```

---

### 3. Enable or Upgrade SSL for Existing Project (`enable-ssl`)
Enable SSL (Let's Encrypt or Self-Signed IP certificate) for an already deployed project using its **Project CODE** (e.g. `SE-001`) or project name:
```bash
# Interactive mode (prompts for Project CODE and SSL provider)
sudo ./nginx-cli enable-ssl

# Scripted mode with Let's Encrypt
sudo ./nginx-cli enable-ssl --project SE-001 --domain api.example.com --email admin@example.com --non-interactive

# Scripted mode with Self-Signed IP SAN certificate
sudo ./nginx-cli enable-ssl --project SE-001 --self-signed --non-interactive
```

---

### 4. List Registered Projects (`list`)
View all configured projects with their **Project CODE** (`SE-001`, `SE-002`, ...), active domains, routes, and SSL statuses:
```bash
./nginx-cli list
```

---

### 5. System Diagnostics & Status (`status`)
Inspect OS distribution, package manager, Nginx systemd service status, firewall status, and public IP:
```bash
./nginx-cli status
```

---

### 5. Preview Configuration (`preview`)
Preview generated Nginx configurations with syntax highlighting without touching `/etc/nginx`:
```bash
./nginx-cli preview --project demo --domain api.demo.com --port 8000 --route / --ssl
```

---

### 6. Test Nginx Syntax (`test-config`)
Run `nginx -t` validation with structured output:
```bash
./nginx-cli test-config
```

---

### 7. Remove Project (`remove`)
Safely decommission a virtual host, clean up configuration and symlinks, and reload Nginx:
```bash
sudo ./nginx-cli remove fastapi-prod
```

---

## 🛠️ Standalone Essential Bash Scripts

For low-level DevOps automation, container pipelines, or direct shell usage, dedicated scripts are provided in `scripts/`:

### 1. Package Installation (`install_dependencies.sh`)
Auto-detects OS and installs Nginx, Certbot, and plugins:
```bash
sudo ./scripts/install_dependencies.sh
# or dry-run
./scripts/install_dependencies.sh --dry-run
```

### 2. Firewall Port Configuration (`configure_firewall.sh`)
Detects active firewall (`UFW`, `Firewalld`, `iptables`) and opens web (80, 443) and backend ports:
```bash
sudo ./scripts/configure_firewall.sh 8000 8001
sudo ./scripts/configure_firewall.sh -p 8000,8001,8002 --dry-run
```

### 3. Automated SSL Setup (`setup_ssl.sh`)
Verifies DNS and provisions Let's Encrypt certificates via Certbot:
```bash
sudo ./scripts/setup_ssl.sh -d api.example.com -m admin@example.com
```

### 4. Nginx Reverse Proxy Health Check (`nginx_health_check.sh`)
Comprehensive diagnostic for Nginx syntax, running services, listening ports, and HTTP probe status:
```bash
./scripts/nginx_health_check.sh
./scripts/nginx_health_check.sh -h api.example.com -p 443
```

### 5. Snapshot Backup & Restoration (`backup_restore.sh`)
Snapshot `/etc/nginx`, list backups, or restore previous configuration:
```bash
# Create backup snapshot
sudo ./scripts/backup_restore.sh backup

# List backups
sudo ./scripts/backup_restore.sh list

# Restore from snapshot
sudo ./scripts/backup_restore.sh restore /var/backups/nginx_setup/nginx_backup_20260911_120000.tar.gz
```


## 🔒 Production Nginx Template Features

The Jinja2 template (`templates/nginx.conf.j2`) includes industry-standard security and performance directives:
- **HTTP-to-HTTPS 301 Redirection**: Automatic redirect with ACME challenge exemption.
- **Modern TLS**: TLSv1.2 & TLSv1.3 with Mozilla Intermediate cipher suites.
- **Security Headers**: HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, `Referrer-Policy`.
- **WebSocket Support**: Full support for real-time applications (FastAPI WebSockets, Socket.IO).
- **Gzip Compression**: Optimized compression for JSON, HTML, CSS, and JavaScript.
- **Client Body Limits & Buffer Tuning**: Configurable `client_max_body_size` and proxy buffer sizes.

---

## 🧪 Running Tests

Execute the comprehensive test suite with `pytest`:
```bash
python3 -m pytest tests/ -v
```

All unit and integration tests mock system commands, allowing 100% test coverage without requiring root privileges.

---

## 📄 License

This project is licensed under the MIT License.
