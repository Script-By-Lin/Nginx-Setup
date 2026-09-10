#!/usr/bin/env bash
# ==============================================================================
# Script: nginx_health_check.sh
# Purpose: Comprehensive diagnostic and health check tool for Nginx & Reverse Proxies.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

TARGET_HOST="127.0.0.1"
TARGET_PORT="80"

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✔]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✖]${NC} $1"; }

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Options:
    -h, --host        Target hostname or IP to test (default: 127.0.0.1)
    -p, --port        Target port to test (default: 80)
    --help            Show this help message and exit

Examples:
    $(basename "$0")
    $(basename "$0") -h api.example.com -p 443
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--host)
            TARGET_HOST="$2"
            shift 2
            ;;
        -p|--port)
            TARGET_PORT="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}         🩺 Nginx Reverse Proxy Health Check          ${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}\n"

# 1. Check if Nginx binary exists
if ! command -v nginx >/dev/null 2>&1; then
    log_error "Nginx binary is NOT installed on this system."
    exit 1
else
    NGINX_VER=$(nginx -v 2>&1)
    log_success "Nginx binary found: $NGINX_VER"
fi

# 2. Validate configuration syntax with nginx -t
SUDO=""
if [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo -n"
fi

echo ""
log_info "Testing Nginx configuration syntax (nginx -t)..."
if $SUDO nginx -t >/dev/null 2>&1; then
    log_success "Nginx configuration syntax is OK and test is successful."
else
    log_error "Nginx syntax validation FAILED. Output:"
    $SUDO nginx -t || true
fi

# 3. Check systemd service status
echo ""
log_info "Checking Nginx system service status..."
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet nginx 2>/dev/null; then
        log_success "Nginx service is ACTIVE (Running)."
    else
        log_warn "Nginx service is INACTIVE or stopped."
    fi

    if systemctl is-enabled --quiet nginx 2>/dev/null; then
        log_success "Nginx service is ENABLED on boot."
    else
        log_warn "Nginx service is DISABLED on boot."
    fi
fi

# 4. Check Listening Ports
echo ""
log_info "Checking listening network sockets for Web (80, 443)..."
if command -v ss >/dev/null 2>&1; then
    LISTENING_80=$(ss -tln | grep -w "80" || true)
    LISTENING_443=$(ss -tln | grep -w "443" || true)

    if [[ -n "$LISTENING_80" ]]; then
        log_success "Port 80 (HTTP) is actively listening."
    else
        log_warn "Port 80 is not currently listening."
    fi

    if [[ -n "$LISTENING_443" ]]; then
        log_success "Port 443 (HTTPS) is actively listening."
    else
        log_info "Port 443 (HTTPS) is not listening (Normal if SSL not enabled)."
    fi
fi

# 5. HTTP Connectivity & Response Headers
echo ""
log_info "Testing HTTP response from http://${TARGET_HOST}:${TARGET_PORT}..."
if command -v curl >/dev/null 2>&1; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://${TARGET_HOST}:${TARGET_PORT}/" || echo "000")
    if [[ "$HTTP_CODE" =~ ^(200|301|302|404)$ ]]; then
        log_success "HTTP Probe Response Code: $HTTP_CODE"
    elif [[ "$HTTP_CODE" == "502" ]]; then
        log_error "HTTP Response Code: 502 Bad Gateway (Backend service is down or not listening on configured port!)."
    elif [[ "$HTTP_CODE" == "000" ]]; then
        log_warn "Connection failed or timed out to http://${TARGET_HOST}:${TARGET_PORT}/."
    else
        log_info "HTTP Response Code: $HTTP_CODE"
    fi
fi

echo -e "\n${BOLD}${GREEN}======================================================${NC}"
echo -e "${BOLD}${GREEN}          Health Check Completed Successfully         ${NC}"
echo -e "${BOLD}${GREEN}======================================================${NC}\n"
