Act as a senior DevOps engineer and Python architect.

Build a production-grade CLI application that automates Nginx + SSL setup for FastAPI or any backend services.

### 🎯 Goal

Create a fully interactive CLI tool that:

* Installs Nginx and Certbot automatically
* Detects OS and uses correct configuration paths
* Generates Nginx reverse proxy configs
* Enables HTTP + HTTPS with SSL
* Configures firewall rules
* Supports multiple backend services with routing paths
* Guides user for DNS setup

---

### 🧱 Architecture Requirements

Use clean architecture:

cli/
main.py
core/
os_detector.py
installer.py
nginx_manager.py
ssl_manager.py
firewall_manager.py
service_manager.py
templates/
nginx.conf.j2
models/
server_config.py

Use:

* Typer for CLI
* Pydantic for validation
* Subprocess for system commands

---

### ⚙️ Features

#### 1. OS Detection

* Detect OS using `/etc/os-release`
* If:

  * Rocky/CentOS → use `/etc/nginx/conf.d/`
  * Arch → use `/etc/nginx/modules.d/` or `/etc/nginx/conf.d/`
  * Ubuntu → `/etc/nginx/sites-available/`

---

#### 2. Auto Installation

Install if not present:

* nginx
* certbot
* python-certbot-nginx

Use correct package manager:

* Rocky → dnf
* Arch → pacman
* Ubuntu → apt

---

#### 3. Interactive Input

Ask user:

* Project name
* Backend executable path
  (example: /home/user/project/.venv/bin/uvicorn main:app)
* Backend port (e.g. 8000)
* Domain (optional)
* Route path (e.g. /api1/)
* Enable SSL? (yes/no)

---

#### 4. Generate Nginx Config

Features:

* Reverse proxy to localhost:PORT
* Support multiple routes:

Example:
location /api1/ {
proxy_pass http://127.0.0.1:8001/;
}

* Support domain OR public IP

---

#### 5. Write Config

* Save config file to correct path
* Validate with:
  nginx -t
* Reload:
  systemctl reload nginx

---

#### 6. Firewall Detection

Detect:

* firewalld
* ufw
* iptables

Open:

* 80
* 443
* user backend port

---

#### 7. SSL Setup

If domain exists:

* Run certbot automatically
* Enable HTTPS redirect

---

#### 8. Multi-Service Support

After first setup:

Ask:
"Do you want to add another service?"

If yes:

* repeat input
* append config

---

#### 9. Systemd Check

* Ensure nginx is:

  * enabled
  * running

If not:

* start + enable

---

#### 10. Success Output

Print:

* Access URLs:
  http://your-ip/api1/
  https://your-domain/api1/

* DNS Instructions:
  A record → your public IP

---

### 🔐 Safety

* Validate paths exist
* Validate ports are free
* Backup old configs before overwrite

---

### 🧪 Bonus Features

* Dry run mode
* Config preview before apply
* Rollback if nginx test fails

---

### 🎨 UX Requirements

* Clean CLI output
* Step-by-step progress:
  [✔] Nginx Installed
  [✔] Config Written
  [✔] SSL Enabled

---

### 📦 Final Output

Produce:

* Full project code
* Ready-to-run CLI
* Example usage:
  nginx-cli setup
  nginx-cli add-service

---

Make the code production-ready, modular, and extensible.
