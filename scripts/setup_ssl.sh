#!/usr/bin/env bash
# ==============================================================================
# Script: setup_ssl.sh
# Purpose: Requests and automates Let's Encrypt SSL certificates using Certbot.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DOMAIN=""
EMAIL=""
DRY_RUN=0
WEBROOT="/var/www/certbot"

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✔]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✖]${NC} $1" >&2; }

usage() {
    cat << EOF
Usage: $(basename "$0") -d <domain> [OPTIONS]

Options:
    -d, --domain      Domain name to issue SSL certificate for (required)
    -m, --email       Email address for Let's Encrypt urgent notices & lost key recovery
    -w, --webroot     Path to webroot ACME challenge directory (default: /var/www/certbot)
    --dry-run         Simulate certificate request
    -h, --help        Show this help message and exit

Examples:
    $(basename "$0") -d api.example.com -m admin@example.com
    $(basename "$0") -d example.com --dry-run
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--domain)
            DOMAIN="$2"
            shift 2
            ;;
        -m|--email)
            EMAIL="$2"
            shift 2
            ;;
        -w|--webroot)
            WEBROOT="$2"
            shift 2
            ;;
        --dry-run)
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

if [[ -z "$DOMAIN" ]]; then
    log_error "Domain name is required. Use -d <domain>."
    exit 1
fi

SUDO=""
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        log_error "Root privileges or sudo required to request SSL certificates."
        exit 1
    fi
fi

if ! command -v certbot >/dev/null 2>&1; then
    log_error "Certbot is not installed. Please install certbot first."
    exit 1
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

log_info "Checking DNS resolution for domain: $DOMAIN..."
if command -v getent >/dev/null 2>&1; then
    if getent ahostsv4 "$DOMAIN" >/dev/null 2>&1; then
        RESOLVED_IP=$(getent ahostsv4 "$DOMAIN" | head -n 1 | awk '{print $1}')
        log_success "Domain '$DOMAIN' resolves to IPv4: $RESOLVED_IP"
    else
        log_warn "Could not resolve domain '$DOMAIN' via DNS. Certbot validation may fail if DNS is not propagated yet."
    fi
fi

# Ensure webroot directory exists
run_cmd "$SUDO mkdir -p $WEBROOT"
run_cmd "$SUDO chmod -R 755 $WEBROOT"

# Construct certbot command
CERTBOT_CMD="$SUDO certbot certonly --webroot -w $WEBROOT -d $DOMAIN --non-interactive --agree-tos"

if [[ -n "$EMAIL" && "$EMAIL" =~ @ ]]; then
    CERTBOT_CMD="$CERTBOT_CMD -m $EMAIL"
else
    CERTBOT_CMD="$CERTBOT_CMD --register-unsafely-without-email"
fi

if [[ $DRY_RUN -eq 1 ]]; then
    CERTBOT_CMD="$CERTBOT_CMD --dry-run"
fi

log_info "Requesting Let's Encrypt certificate for $DOMAIN..."
run_cmd "$CERTBOT_CMD"

CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
KEY_PATH="/etc/letsencrypt/live/$DOMAIN/privkey.pem"

log_success "SSL Certificate issued for $DOMAIN:"
log_info "  Certificate: $CERT_PATH"
log_info "  Private Key: $KEY_PATH"

log_info "Testing auto-renewal mechanism..."
run_cmd "$SUDO certbot renew --dry-run"

log_success "SSL Setup Complete!"
