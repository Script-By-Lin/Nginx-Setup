#!/usr/bin/env bash
# ==============================================================================
# Script: setup_ssl.sh
# Purpose: Requests Let's Encrypt SSL certificates for domains or generates
#          Self-Signed SSL certificates with IP SAN for Public / LAN IPs.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DOMAIN=""
IP_ADDR=""
EMAIL=""
DRY_RUN=0
WEBROOT="/var/www/certbot"

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✔]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✖]${NC} $1" >&2; }

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Options:
    -d, --domain      Domain name to issue Let's Encrypt SSL certificate for
    -i, --ip          Public IP or LAN IP address to generate self-signed SSL for
    -m, --email       Email address for Let's Encrypt renewal notifications
    -w, --webroot     Path to webroot ACME challenge directory (default: /var/www/certbot)
    --dry-run         Simulate certificate issuance
    -h, --help        Show this help message and exit

Examples:
    $(basename "$0") -d api.example.com -m admin@example.com
    $(basename "$0") -i 192.168.1.150
    $(basename "$0") --ip 77.83.241.82
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--domain)
            DOMAIN="$2"
            shift 2
            ;;
        -i|--ip)
            IP_ADDR="$2"
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

if [[ -z "$DOMAIN" && -z "$IP_ADDR" ]]; then
    log_error "Must specify either a domain (-d <domain>) or a public/LAN IP (-i <ip_address>)."
    usage
fi

SUDO=""
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        log_error "Root privileges or sudo required to manage SSL certificates."
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

# ------------------------------------------------------------------------------
# Case 1: IP Address Self-Signed Certificate with IP SAN
# ------------------------------------------------------------------------------
if [[ -n "$IP_ADDR" ]]; then
    log_info "Configuring SSL for IP Address: $IP_ADDR..."
    CERT_DIR="/etc/ssl/certs"
    KEY_DIR="/etc/ssl/private"
    CERT_PATH="${CERT_DIR}/ip_${IP_ADDR}_selfsigned.crt"
    KEY_PATH="${KEY_DIR}/ip_${IP_ADDR}_selfsigned.key"

    run_cmd "$SUDO mkdir -p $CERT_DIR $KEY_DIR"

    log_info "Generating OpenSSL certificate with Subject Alternative Name (SAN IP:$IP_ADDR)..."
    OPENSSL_CMD="$SUDO openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout $KEY_PATH -out $CERT_PATH -subj '/CN=$IP_ADDR' -addext 'subjectAltName=IP:$IP_ADDR'"
    run_cmd "$OPENSSL_CMD || $SUDO openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout $KEY_PATH -out $CERT_PATH -subj '/CN=$IP_ADDR'"

    run_cmd "$SUDO chmod 600 $KEY_PATH"
    run_cmd "$SUDO chmod 644 $CERT_PATH"

    log_success "Self-Signed IP SSL Certificate created successfully!"
    log_info "  Certificate: $CERT_PATH"
    log_info "  Private Key: $KEY_PATH"
    exit 0
fi

# ------------------------------------------------------------------------------
# Case 2: Let's Encrypt Certificate for Domain
# ------------------------------------------------------------------------------
if ! command -v certbot >/dev/null 2>&1; then
    log_error "Certbot is not installed. Please install certbot first."
    exit 1
fi

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

log_success "Let's Encrypt SSL Certificate issued for $DOMAIN:"
log_info "  Certificate: $CERT_PATH"
log_info "  Private Key: $KEY_PATH"

log_info "Testing auto-renewal mechanism..."
run_cmd "$SUDO certbot renew --dry-run"

log_success "SSL Setup Complete!"
