#!/usr/bin/env python3
"""
SELLO — Backup Verification & Certification Tool
Verifica que tus backups son restaurables. Genera certificados de prueba.

Usage:
    sello verify <backup_path> [--type=<type>] [--report=<format>]
    sello verify-db <dump_path> --engine=<engine> [--report=<format>]
    sello verify-vm <image_path> [--report=<format>]
    sello schedule <backup_path> --cron=<expr> [--type=<type>]
    sello report [--last=<n>]
    sello --version
    sello --help

Options:
    -h --help           Show this help
    --version           Show version
    --type=<type>       Backup type: auto, tar, restic, borg, directory, zip [default: auto]
    --engine=<engine>   DB engine: mysql, postgres, sqlite
    --report=<format>   Report format: terminal, json, html, pdf [default: terminal]
    --last=<n>          Show last N verification reports [default: 10]
    --cron=<expr>       Cron expression for scheduled verification

Examples:
    sello verify /backups/server1-2026-03-18.tar.gz
    sello verify /backups/restic-repo --type=restic
    sello verify-db /backups/mydb.sql --engine=postgres
    sello verify-db /backups/mydb.sql --engine=mysql --report=json
    sello report --last=5
"""

__version__ = "0.2.0"

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from cli import main

if __name__ == "__main__":
    main()
