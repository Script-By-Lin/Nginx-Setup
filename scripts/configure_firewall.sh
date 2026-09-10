#!/usr/bin/env bash
# ==============================================================================
# Script: configure_firewall.sh
# Purpose: Detects active Linux firewall and opens ports (80, 443, and backend ports).
# ==============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DRY_RUN=0
PORTS=(80 443)

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✔]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✖]${NC} $1" >&2; }

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS] [EXTRA_PORTS...]

Arguments:
    EXTRA_PORTS       Space or comma-separated list of additional ports (e.g. 8000 8001)

Options:
    -p, --ports       Comma-separated list of ports to open (e.g. -p 8000,8001)
    -d, --dry-run     Simulate firewall changes without executing
    -h, --help        Show this help message and exit

Examples:
    $(basename "$0") 8000
    $(basename "$0") -p 8000,8001,8002
    $(basename "$0") --dry-run 8000
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
        -p|--ports)
            IFS=',' read -r -a input_ports <<< "$2"
            PORTS+=("${input_ports[@]}")
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                PORTS+=("$1")
            else
                log_error "Unknown argument: $1"
                usage
            fi
            shift
            ;;
    esac
done

# Deduplicate and sort ports
UNIQUE_PORTS=($(echo "${PORTS[@]}" | tr ' ' '\n' | sort -n -u | tr '\n' ' '))

SUDO=""
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        log_error "Root privileges or sudo required to configure firewall rules."
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

log_info "Detecting active firewall..."

FIREWALL_TYPE="none"
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet ufw 2>/dev/null; then
        FIREWALL_TYPE="ufw"
    elif systemctl is-active --quiet firewalld 2>/dev/null; then
        FIREWALL_TYPE="firewalld"
    elif systemctl is-active --quiet iptables 2>/dev/null; then
        FIREWALL_TYPE="iptables"
    fi
fi

if [[ "$FIREWALL_TYPE" == "none" ]]; then
    if command -v ufw >/dev/null 2>&1 && $SUDO -n ufw status 2>/dev/null | grep -qi "status: active"; then
        FIREWALL_TYPE="ufw"
    elif command -v firewall-cmd >/dev/null 2>&1 && $SUDO -n firewall-cmd --state >/dev/null 2>&1; then
        FIREWALL_TYPE="firewalld"
    elif command -v iptables >/dev/null 2>&1 && $SUDO -n iptables -L -n 2>/dev/null | grep -q "ACCEPT"; then
        FIREWALL_TYPE="iptables"
    fi
fi

log_info "Active firewall detected: $FIREWALL_TYPE"
log_info "Configuring rules for ports: ${UNIQUE_PORTS[*]}"

case "$FIREWALL_TYPE" in
    ufw)
        for port in "${UNIQUE_PORTS[@]}"; do
            run_cmd "$SUDO ufw allow ${port}/tcp"
        done
        log_success "UFW firewall rules updated."
        ;;
    firewalld)
        run_cmd "$SUDO firewall-cmd --permanent --add-service=http"
        run_cmd "$SUDO firewall-cmd --permanent --add-service=https"
        for port in "${UNIQUE_PORTS[@]}"; do
            if [[ "$port" -ne 80 && "$port" -ne 443 ]]; then
                run_cmd "$SUDO firewall-cmd --permanent --add-port=${port}/tcp"
            fi
        done
        run_cmd "$SUDO firewall-cmd --reload"
        log_success "Firewalld rules updated and reloaded."
        ;;
    iptables)
        for port in "${UNIQUE_PORTS[@]}"; do
            if ! $SUDO iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
                run_cmd "$SUDO iptables -I INPUT -p tcp --dport ${port} -j ACCEPT"
            fi
        done
        log_success "iptables rules configured."
        ;;
    none)
        log_warn "No active firewall service detected (UFW, Firewalld, or iptables). Skipping port configuration."
        ;;
esac

log_success "Firewall configuration finished for ports: ${UNIQUE_PORTS[*]}"
