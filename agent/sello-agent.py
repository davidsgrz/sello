#!/usr/bin/env python3
"""
SELLO Agent — Remote backup verification agent.
Install on each server. Runs verifications locally and reports results to SELLO Pro.

Setup:
    1. Copy this file + src/ to the target server
    2. Configure: sello-agent setup --server https://sello.tudominio.com --key sello_xxxxx
    3. Run: sello-agent run
    4. Or add to cron: sello-agent run --cron

Usage:
    sello-agent setup --server <url> --key <api_key>
    sello-agent run [--once]
    sello-agent status
    sello-agent test
"""

import os
import sys
import json
import time
import glob
import hashlib
import urllib.request
import urllib.error
import argparse
from datetime import datetime

# Add src to path (same verification engine as CLI)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from verifier import BackupVerifier
from db_verifier import DBVerifier
from size_anomaly import SizeAnomalyDetector

AGENT_CONFIG_DIR = os.path.expanduser("~/.sello")
AGENT_CONFIG_PATH = os.path.join(AGENT_CONFIG_DIR, "agent.json")

BANNER = """
\033[1;36m╔═══════════════════════════════════════════╗
║       🔒  SELLO Agent  v0.2.0            ║
║       Remote Backup Verification          ║
╚═══════════════════════════════════════════╝\033[0m
"""


def load_agent_config():
    if not os.path.exists(AGENT_CONFIG_PATH):
        return None
    with open(AGENT_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_agent_config(config):
    os.makedirs(AGENT_CONFIG_DIR, exist_ok=True)
    with open(AGENT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def api_request(server_url, endpoint, data=None, api_key=None, method="GET"):
    """Make an API request to the SELLO Pro server."""
    url = f"{server_url.rstrip('/')}{endpoint}"

    if data:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    else:
        body = None

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key or "",
            "User-Agent": "sello-agent/0.2.0",
        }
    )

    try:
        response = urllib.request.urlopen(req, timeout=30)
        return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            detail = json.loads(error_body).get("detail", error_body)
        except Exception:
            detail = error_body
        raise RuntimeError(f"HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Conexión fallida: {e.reason}")


def cmd_setup(args):
    """Configure the agent."""
    print(BANNER)

    server_url = args.server.rstrip("/")
    api_key = args.key

    print(f"  Configurando agente...")
    print(f"  Servidor: {server_url}")

    # Test connection
    print(f"  Probando conexión...", end=" ", flush=True)
    try:
        result = api_request(server_url, "/health")
        if result.get("status") == "ok":
            print(f"\033[1;32m✔ OK\033[0m (server v{result.get('version', '?')})")
        else:
            print(f"\033[1;31m✘ Respuesta inesperada\033[0m")
            sys.exit(1)
    except Exception as e:
        print(f"\033[1;31m✘ Error: {e}\033[0m")
        sys.exit(1)

    # Test API key
    print(f"  Verificando API key...", end=" ", flush=True)
    try:
        result = api_request(server_url, "/api/verify", data={
            "backup_path": "__test__",
            "backup_type": "test",
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": 0,
            "passed": True,
            "checks": [],
        }, api_key=api_key, method="POST")
        print(f"\033[1;32m✔ Autenticado como '{result.get('server_name', '?')}'\033[0m")
    except Exception as e:
        print(f"\033[1;31m✘ Error: {e}\033[0m")
        sys.exit(1)

    # Save config
    config = {
        "server_url": server_url,
        "api_key": api_key,
        "configured_at": datetime.now().isoformat(),
        "backups": [
            {
                "name": "example-daily",
                "path": "/backups/daily-*.tar.gz",
                "type": "auto",
                "enabled": False,
                "comment": "Edita este archivo para configurar tus backups"
            }
        ]
    }

    save_agent_config(config)

    print(f"\n  \033[1;32m✔ Agente configurado correctamente\033[0m")
    print(f"  Config: {AGENT_CONFIG_PATH}")
    print(f"\n  Próximos pasos:")
    print(f"    1. Edita {AGENT_CONFIG_PATH}")
    print(f"    2. Añade tus backups a la lista 'backups'")
    print(f"    3. Ejecuta: sello-agent run")
    print(f"    4. O añade a cron: */60 * * * * sello-agent run --once")
    print()


def cmd_run(args):
    """Run verification on all configured backups and report to server."""
    config = load_agent_config()
    if not config:
        print("  \033[1;31m✘ Agente no configurado. Ejecuta: sello-agent setup\033[0m")
        sys.exit(1)

    server_url = config["server_url"]
    api_key = config["api_key"]
    backups = config.get("backups", [])

    if not args.once:
        print(BANNER)
        print(f"  Servidor: {server_url}")
        print(f"  Backups configurados: {len(backups)}")
        print()

    verifier = BackupVerifier()
    db_verifier = DBVerifier()
    anomaly = SizeAnomalyDetector()

    enabled_backups = [b for b in backups if b.get("enabled", True)]

    if not enabled_backups:
        if not args.once:
            print("  ⚠  No hay backups habilitados. Edita ~/.sello/agent.json")
        return

    results_summary = {"ok": 0, "fail": 0, "error": 0}

    for backup_cfg in enabled_backups:
        name = backup_cfg.get("name", backup_cfg["path"])
        path_pattern = backup_cfg["path"]
        backup_type = backup_cfg.get("type", "auto")
        engine = backup_cfg.get("engine")

        # Resolve glob pattern — pick most recent file
        matching_files = sorted(glob.glob(path_pattern), key=os.path.getmtime, reverse=True)

        if not matching_files:
            if not args.once:
                print(f"  ⚠  {name}: No se encontraron archivos ({path_pattern})")
            results_summary["error"] += 1
            continue

        filepath = matching_files[0]  # Most recent

        if not args.once:
            print(f"  → {name} ({os.path.basename(filepath)})...", end=" ", flush=True)

        try:
            # Run verification
            if engine:
                result = db_verifier.verify(filepath, engine)
            else:
                if backup_type == "auto":
                    backup_type = verifier.detect_type(filepath)
                result = verifier.verify(filepath, backup_type)

            # Size anomaly
            size_bytes = os.path.getsize(filepath) if os.path.isfile(filepath) else 0
            if size_bytes > 0:
                anomaly_check = anomaly.check_anomaly(filepath, size_bytes)
                result.checks.append(anomaly_check)
                if not anomaly_check.passed and anomaly_check.severity == "critical":
                    result.passed = False

            # Get checksum
            checksum = None
            for check in result.checks:
                if check.name == "checksum" and check.details:
                    checksum = check.details.get("sha256")

            # Report to server
            payload = {
                "backup_path": filepath,
                "backup_type": result.backup_type,
                "timestamp": result.timestamp,
                "duration_seconds": result.duration_seconds,
                "passed": result.passed,
                "checks": [
                    {
                        "name": c.name,
                        "description": c.description,
                        "passed": c.passed,
                        "message": c.message,
                        "severity": c.severity,
                        "details": c.details,
                    }
                    for c in result.checks
                ],
                "size_bytes": size_bytes,
                "checksum": checksum,
            }

            api_result = api_request(server_url, "/api/verify", data=payload, api_key=api_key, method="POST")

            if result.passed:
                results_summary["ok"] += 1
                if not args.once:
                    print(f"\033[1;32m✔ OK\033[0m ({result.duration_seconds}s) → reportado")
            else:
                results_summary["fail"] += 1
                if not args.once:
                    print(f"\033[1;31m✘ FAIL\033[0m ({result.duration_seconds}s) → reportado")
                    for c in result.checks:
                        if not c.passed and c.severity == "critical":
                            print(f"       └─ {c.message}")

        except Exception as e:
            results_summary["error"] += 1
            if not args.once:
                print(f"\033[1;31m✘ ERROR: {e}\033[0m")

    # Summary
    if not args.once:
        total = sum(results_summary.values())
        print(f"\n  ─────────────────────────────────")
        print(f"  Total: {total} | ✔ {results_summary['ok']} | ✘ {results_summary['fail']} | ⚠ {results_summary['error']}")
        print()


def cmd_status(args):
    """Show agent status."""
    print(BANNER)
    config = load_agent_config()

    if not config:
        print("  Estado: \033[1;31mNO CONFIGURADO\033[0m")
        print("  Ejecuta: sello-agent setup --server <url> --key <key>")
        return

    print(f"  Estado: \033[1;32mCONFIGURADO\033[0m")
    print(f"  Servidor: {config['server_url']}")
    print(f"  Config: {AGENT_CONFIG_PATH}")
    print(f"  Configurado: {config.get('configured_at', '?')}")

    backups = config.get("backups", [])
    enabled = [b for b in backups if b.get("enabled", True)]
    print(f"  Backups: {len(backups)} configurados, {len(enabled)} habilitados")

    # Test connection
    print(f"\n  Probando conexión...", end=" ", flush=True)
    try:
        result = api_request(config["server_url"], "/health")
        print(f"\033[1;32m✔ Servidor online\033[0m (v{result.get('version', '?')})")
    except Exception as e:
        print(f"\033[1;31m✘ Sin conexión: {e}\033[0m")
    print()


def cmd_test(args):
    """Run a test verification without reporting to server."""
    print(BANNER)
    config = load_agent_config()

    if not config:
        print("  \033[1;31m✘ No configurado\033[0m")
        sys.exit(1)

    backups = config.get("backups", [])
    enabled = [b for b in backups if b.get("enabled", True)]

    if not enabled:
        print("  No hay backups habilitados para testear.")
        return

    print(f"  Testeando {len(enabled)} backups (sin reportar al servidor):\n")

    verifier = BackupVerifier()

    for b in enabled:
        matching = sorted(glob.glob(b["path"]), key=os.path.getmtime, reverse=True)
        if not matching:
            print(f"  ⚠  {b['name']}: No encontrado ({b['path']})")
            continue

        filepath = matching[0]
        backup_type = b.get("type", "auto")
        if backup_type == "auto":
            backup_type = verifier.detect_type(filepath)

        print(f"  → {b['name']}: {filepath}")
        print(f"    Tipo: {backup_type}")
        print(f"    Tamaño: {os.path.getsize(filepath) / (1024*1024):.2f} MB")
        print(f"    Modificado: {datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()}")
        print()


def main():
    parser = argparse.ArgumentParser(prog="sello-agent", description="SELLO Remote Agent")
    subparsers = parser.add_subparsers(dest="command")

    setup_p = subparsers.add_parser("setup", help="Configurar agente")
    setup_p.add_argument("--server", required=True, help="URL del servidor SELLO Pro")
    setup_p.add_argument("--key", required=True, help="API key")

    run_p = subparsers.add_parser("run", help="Ejecutar verificaciones")
    run_p.add_argument("--once", action="store_true", help="Modo silencioso (para cron)")

    subparsers.add_parser("status", help="Ver estado del agente")
    subparsers.add_parser("test", help="Test sin reportar")

    args = parser.parse_args()

    if not args.command:
        print(BANNER)
        parser.print_help()
        sys.exit(0)

    commands = {
        "setup": cmd_setup,
        "run": cmd_run,
        "status": cmd_status,
        "test": cmd_test,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
