#!/usr/bin/env bash
# ==============================================================================
# Script: install_dependencies.sh
# Purpose: Auto-detects Linux distribution and installs Nginx, Certbot & Plugins.
# ==============================================================================

set -euo pipefail

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

DRY_RUN=0

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✔]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✖]${NC} $1" >&2; }

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Options:
    -d, --dry-run     Simulate installation without modifying the system
    -h, --help        Show this help message and exit
EOF
    exit 0
}

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Check sudo / root
SUDO=""
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        log_error "Root privileges or sudo required to install system packages."
        exit 1
    fi
fi

run_cmd() {
    local cmd="$*"
    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "[DRY-RUN] Would execute: $cmd"
    else
        log_info "Executing: $cmd"
        eval "$cmd"
    fi
}

log_info "Detecting Operating System distribution..."

if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    ID_LIKE="${ID_LIKE:-}"
else
    log_error "/etc/os-release not found. Cannot determine Linux distribution."
    exit 1
fi

log_info "Detected OS: ${PRETTY_NAME:-$DISTRO_ID} (ID: $DISTRO_ID, ID_LIKE: $ID_LIKE)"

# Package installation per distribution family
if [[ "$DISTRO_ID" =~ ^(ubuntu|debian|linuxmint|pop|kali)$ ]] || [[ "$ID_LIKE" =~ (debian|ubuntu) ]]; then
    log_info "Using APT package manager..."
    run_cmd "$SUDO apt-get update -y"
    run_cmd "$SUDO apt-get install -y nginx certbot python3-certbot-nginx"

elif [[ "$DISTRO_ID" =~ ^(rocky|centos|rhel|almalinux|fedora|ol|amzn)$ ]] || [[ "$ID_LIKE" =~ (rhel|fedora|centos) ]]; then
    log_info "Using DNF/YUM package manager..."
    PKG_MGR="dnf"
    if ! command -v dnf >/dev/null 2>&1; then
        PKG_MGR="yum"
    fi
    run_cmd "$SUDO $PKG_MGR install -y epel-release || true"
    run_cmd "$SUDO $PKG_MGR install -y nginx certbot python3-certbot-nginx"

elif [[ "$DISTRO_ID" =~ ^(arch|cachyos|manjaro|endeavouros|artix)$ ]] || [[ "$ID_LIKE" =~ arch ]]; then
    log_info "Using Pacman package manager..."
    run_cmd "$SUDO pacman -Sy --noconfirm --needed nginx certbot certbot-nginx"

elif [[ "$DISTRO_ID" =~ ^alpine$ ]]; then
    log_info "Using APK package manager..."
    run_cmd "$SUDO apk update"
    run_cmd "$SUDO apk add nginx certbot certbot-nginx"

elif [[ "$DISTRO_ID" =~ ^(opensuse|sles)$ ]] || [[ "$ID_LIKE" =~ suse ]]; then
    log_info "Using Zypper package manager..."
    run_cmd "$SUDO zypper --non-interactive install nginx certbot python3-certbot-nginx"

else
    log_error "Unsupported distribution: $DISTRO_ID ($ID_LIKE)."
    exit 1
fi

# Ensure webroot certbot challenge directory exists
log_info "Ensuring /var/www/certbot directory exists for ACME challenges..."
run_cmd "$SUDO mkdir -p /var/www/certbot"
run_cmd "$SUDO chmod -R 755 /var/www/certbot"

log_success "All dependencies (Nginx, Certbot, certbot-nginx) installed successfully!"
