#!/usr/bin/env bash
# ==============================================================================
# Script: backup_restore.sh
# Purpose: Nginx configuration backup, snapshotting, listing, and restoration.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

BACKUP_DIR="${BACKUP_DIR:-/var/backups/nginx_setup}"
NGINX_DIR="/etc/nginx"

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✔]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✖]${NC} $1" >&2; }

usage() {
    cat << EOF
Usage: $(basename "$0") <COMMAND> [OPTIONS]

Commands:
    backup            Create a full snapshot backup of /etc/nginx
    list              List all available backups
    restore <FILE>    Restore /etc/nginx from specified backup archive
    help              Show this help message

Options:
    -d, --dir <DIR>   Custom backup storage directory (default: /var/backups/nginx_setup)
EOF
    exit 0
}

SUDO=""
if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        log_error "Root privileges or sudo required to manage Nginx backups."
        exit 1
    fi
fi

COMMAND="${1:-help}"
shift || true

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dir)
            BACKUP_DIR="$2"
            shift 2
            ;;
        *)
            RESTORE_TARGET="$1"
            shift
            ;;
    esac
done

case "$COMMAND" in
    backup)
        TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
        $SUDO mkdir -p "$BACKUP_DIR"
        BACKUP_FILE="${BACKUP_DIR}/nginx_backup_${TIMESTAMP}.tar.gz"
        log_info "Creating Nginx configuration backup snapshot..."
        $SUDO tar -czf "$BACKUP_FILE" -C /etc nginx
        log_success "Backup created successfully at: $BACKUP_FILE"
        ;;

    list)
        log_info "Listing available Nginx backups in $BACKUP_DIR:"
        if [[ ! -d "$BACKUP_DIR" ]]; then
            log_warn "Backup directory $BACKUP_DIR does not exist yet."
            exit 0
        fi
        $SUDO ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null || log_warn "No backups found."
        ;;

    restore)
        if [[ -z "${RESTORE_TARGET:-}" ]]; then
            log_error "Please specify a backup file to restore. Example: $(basename "$0") restore /var/backups/nginx_setup/nginx_backup_20260911_120000.tar.gz"
            exit 1
        fi

        if [[ ! -f "$RESTORE_TARGET" ]]; then
            log_error "Backup file '$RESTORE_TARGET' does not exist."
            exit 1
        fi

        log_warn "Restoring /etc/nginx from $RESTORE_TARGET..."
        $SUDO tar -xzf "$RESTORE_TARGET" -C /etc

        log_info "Validating restored configuration with 'nginx -t'..."
        if $SUDO nginx -t; then
            log_success "Restored configuration is valid. Reloading Nginx..."
            $SUDO systemctl reload nginx 2>/dev/null || $SUDO nginx -s reload
            log_success "Restoration completed successfully!"
        else
            log_error "Restored configuration failed syntax validation! Please check backup contents."
            exit 1
        fi
        ;;

    help|*)
        usage
        ;;
esac
