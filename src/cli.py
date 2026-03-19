"""SELLO CLI v0.2.0 — Command-line interface with notifications, watch, verify-all."""

import argparse
import sys
import os
import glob
import time
from datetime import datetime

from verifier import BackupVerifier
from db_verifier import DBVerifier
from reporter import Reporter, VerificationResult
from certificate import CertificateGenerator
from history import HistoryManager
from notifier import Notifier
from size_anomaly import SizeAnomalyDetector
from config import load_config, save_default_config

BANNER = """
\033[1;36m╔═══════════════════════════════════════════╗
║          🔒  S E L L O  v0.2.0           ║
║   Backup Verification & Certification    ║
╚═══════════════════════════════════════════╝\033[0m
"""


def main():
    parser = argparse.ArgumentParser(
        prog="sello",
        description="SELLO — Verifica que tus backups son restaurables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  sello verify /backups/server1.tar.gz
  sello verify-db /backups/dump.sql --engine mysql
  sello verify-all /backups/
  sello watch /backups/ --interval 3600
  sello diff /backups/backup1.tar.gz /backups/backup2.tar.gz
  sello trend /backups/daily.tar.gz
  sello report --last 5
  sello init
        """
    )
    parser.add_argument("--version", action="version", version="sello 0.2.0")

    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # verify
    verify_p = subparsers.add_parser("verify", help="Verificar un backup")
    verify_p.add_argument("backup_path")
    verify_p.add_argument("--type", choices=["auto", "tar", "restic", "borg", "directory", "zip"], default="auto")
    verify_p.add_argument("--report", choices=["terminal", "json", "html"], default="terminal")
    verify_p.add_argument("--notify", action="store_true", help="Enviar notificación si falla")

    # verify-db
    db_p = subparsers.add_parser("verify-db", help="Verificar un dump de base de datos")
    db_p.add_argument("dump_path")
    db_p.add_argument("--engine", required=True, choices=["mysql", "postgres", "sqlite"])
    db_p.add_argument("--report", choices=["terminal", "json", "html"], default="terminal")
    db_p.add_argument("--notify", action="store_true")

    # verify-all
    all_p = subparsers.add_parser("verify-all", help="Verificar todos los backups en un directorio")
    all_p.add_argument("directory", help="Directorio con backups")
    all_p.add_argument("--pattern", default="*", help="Patrón glob (default: *)")
    all_p.add_argument("--report", choices=["terminal", "json", "html"], default="terminal")
    all_p.add_argument("--notify", action="store_true")
    all_p.add_argument("--recursive", "-r", action="store_true")

    # watch
    watch_p = subparsers.add_parser("watch", help="Monitorizar directorio continuamente")
    watch_p.add_argument("directory")
    watch_p.add_argument("--interval", type=int, default=3600, help="Segundos (default: 3600)")
    watch_p.add_argument("--pattern", default="*.tar.gz,*.zip,*.sql,*.sql.gz,*.db")
    watch_p.add_argument("--notify", action="store_true")

    # diff
    diff_p = subparsers.add_parser("diff", help="Comparar dos backups")
    diff_p.add_argument("backup_a")
    diff_p.add_argument("backup_b")

    # report
    report_p = subparsers.add_parser("report", help="Ver historial")
    report_p.add_argument("--last", type=int, default=10)
    report_p.add_argument("--failed", action="store_true", help="Solo fallidos")
    report_p.add_argument("--export", choices=["json", "html"])

    # init
    subparsers.add_parser("init", help="Crear configuración inicial")

    # trend
    trend_p = subparsers.add_parser("trend", help="Tendencia de tamaño")
    trend_p.add_argument("backup_path")
    trend_p.add_argument("--last", type=int, default=10)

    args = parser.parse_args()

    if not args.command:
        print(BANNER)
        parser.print_help()
        sys.exit(0)

    report_format = getattr(args, "report", "terminal")
    export_format = getattr(args, "export", None)
    quiet = report_format == "json" or export_format == "json"

    if not quiet:
        print(BANNER)

    config = load_config()
    history = HistoryManager()
    notifier = _build_notifier(args, config)

    commands = {
        "verify": lambda: run_verify(args, history, quiet, notifier),
        "verify-db": lambda: run_verify_db(args, history, quiet, notifier),
        "verify-all": lambda: run_verify_all(args, history, quiet, notifier),
        "watch": lambda: run_watch(args, history, config, notifier),
        "diff": lambda: run_diff(args),
        "report": lambda: run_report(args, history),
        "init": lambda: run_init(),
        "trend": lambda: run_trend(args),
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        cmd_fn()


def _build_notifier(args, config):
    if not getattr(args, "notify", False):
        return None
    notif_config = config.get("notifications", {})
    active = {}
    for ch in ["telegram", "slack", "email"]:
        c = notif_config.get(ch, {})
        if c.get("enabled", False):
            active[ch] = c
    active["notify_on"] = notif_config.get("notify_on", "failure")
    return Notifier(active)


def _do_verify_file(backup_path, backup_type, history, notifier=None, report_format="terminal", quiet=False):
    """Core file verification with size anomaly."""
    reporter = Reporter()
    verifier = BackupVerifier()
    anomaly = SizeAnomalyDetector()

    result = verifier.verify(backup_path, backup_type)

    # Size anomaly
    size_bytes = 0
    for check in result.checks:
        if check.name == "size" and check.details:
            size_bytes = check.details.get("size_bytes", 0)
            break
    if size_bytes > 0:
        anomaly_check = anomaly.check_anomaly(backup_path, size_bytes)
        result.checks.append(anomaly_check)
        if not anomaly_check.passed and anomaly_check.severity == "critical":
            result.passed = False

    history.save(result)

    if result.passed:
        cert = CertificateGenerator()
        result.certificate_path = cert.generate(result)

    if not quiet:
        reporter.output(result, format=report_format)

    if notifier:
        sent = notifier.notify(result)
        if sent and not quiet:
            reporter.print_info(f"Notificaciones enviadas: {', '.join(sent)}")

    return result


def run_verify(args, history, quiet=False, notifier=None):
    reporter = Reporter()
    backup_path = os.path.abspath(args.backup_path)

    if not os.path.exists(backup_path):
        if not quiet:
            reporter.print_error(f"No se encuentra: {backup_path}")
        sys.exit(1)

    if not quiet:
        reporter.print_header(f"Verificando backup: {backup_path}")

    verifier = BackupVerifier()
    backup_type = args.type
    if backup_type == "auto":
        backup_type = verifier.detect_type(backup_path)
        if not quiet:
            reporter.print_info(f"Tipo detectado: {backup_type}")

    # For direct verify command, always output (even JSON)
    result = _do_verify_file(backup_path, backup_type, history, notifier, args.report, quiet=False)
    sys.exit(0 if result.passed else 1)


def run_verify_db(args, history, quiet=False, notifier=None):
    reporter = Reporter()
    verifier = DBVerifier()
    dump_path = os.path.abspath(args.dump_path)

    if not os.path.exists(dump_path):
        if not quiet:
            reporter.print_error(f"No se encuentra: {dump_path}")
        sys.exit(1)

    if not quiet:
        reporter.print_header(f"Verificando dump DB: {dump_path}")
        reporter.print_info(f"Motor: {args.engine}")

    result = verifier.verify(dump_path, args.engine)

    # Size anomaly
    anomaly = SizeAnomalyDetector()
    anomaly_check = anomaly.check_anomaly(dump_path, os.path.getsize(dump_path))
    result.checks.append(anomaly_check)

    history.save(result)
    if result.passed:
        cert = CertificateGenerator()
        result.certificate_path = cert.generate(result)

    reporter.output(result, format=args.report)

    if notifier:
        sent = notifier.notify(result)
        if sent and not quiet:
            reporter.print_info(f"Notificaciones enviadas: {', '.join(sent)}")

    sys.exit(0 if result.passed else 1)


def run_verify_all(args, history, quiet=False, notifier=None):
    reporter = Reporter()
    directory = os.path.abspath(args.directory)

    if not os.path.isdir(directory):
        reporter.print_error(f"No es un directorio: {directory}")
        sys.exit(1)

    reporter.print_header(f"Verificando todos los backups en: {directory}")

    if args.recursive:
        files = glob.glob(os.path.join(directory, "**", args.pattern), recursive=True)
    else:
        files = glob.glob(os.path.join(directory, args.pattern))

    files = sorted(f for f in files if os.path.isfile(f) and not os.path.basename(f).startswith("."))

    if not files:
        reporter.print_info(f"No se encontraron archivos con patrón '{args.pattern}'")
        sys.exit(0)

    reporter.print_info(f"{len(files)} archivos encontrados\n")

    verifier = BackupVerifier()
    passed = 0
    failed = 0

    for filepath in files:
        backup_type = verifier.detect_type(filepath)
        print(f"  → {os.path.basename(filepath)} ({backup_type})...", end=" ", flush=True)

        result = _do_verify_file(filepath, backup_type, history, notifier, quiet=True)

        if result.passed:
            passed += 1
            print(f"\033[1;32m✔ OK\033[0m ({result.duration_seconds}s)")
        else:
            failed += 1
            print(f"\033[1;31m✘ FAIL\033[0m")
            for c in result.checks:
                if not c.passed and c.severity == "critical":
                    print(f"       └─ {c.message}")

    print(f"\n\033[1;37m{'─' * 50}\033[0m")
    print(f"  Total: {len(files)} | \033[1;32m✔ {passed}\033[0m | \033[1;31m✘ {failed}\033[0m\n")
    sys.exit(0 if failed == 0 else 1)


def run_watch(args, history, config, notifier=None):
    reporter = Reporter()
    directory = os.path.abspath(args.directory)
    interval = args.interval
    patterns = [p.strip() for p in args.pattern.split(",")]

    reporter.print_header(f"Monitorizando: {directory}")
    reporter.print_info(f"Intervalo: {interval}s ({interval/3600:.1f}h)")
    reporter.print_info(f"Patrones: {', '.join(patterns)}")
    reporter.print_info("Ctrl+C para detener\n")

    seen = {}

    try:
        while True:
            all_files = []
            for pattern in patterns:
                all_files.extend(glob.glob(os.path.join(directory, "**", pattern), recursive=True))
            all_files = sorted(set(f for f in all_files if os.path.isfile(f)))

            new_or_changed = []
            for f in all_files:
                mtime = os.path.getmtime(f)
                if f not in seen or seen[f] != mtime:
                    new_or_changed.append(f)
                    seen[f] = mtime

            if new_or_changed:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n  \033[1;36m[{ts}]\033[0m {len(new_or_changed)} backup(s) nuevos/modificados:")

                verifier = BackupVerifier()
                for filepath in new_or_changed:
                    backup_type = verifier.detect_type(filepath)
                    print(f"    → {os.path.basename(filepath)}...", end=" ", flush=True)
                    result = _do_verify_file(filepath, backup_type, history, notifier, quiet=True)
                    if result.passed:
                        print(f"\033[1;32m✔ OK\033[0m ({result.duration_seconds}s)")
                    else:
                        print(f"\033[1;31m✘ FAIL\033[0m")
                        for c in result.checks:
                            if not c.passed and c.severity == "critical":
                                print(f"       └─ {c.message}")
            else:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"  [{ts}] Sin cambios.", end="\r", flush=True)

            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n\n  Detenido. {len(seen)} backups monitorizados.")


def run_diff(args):
    import hashlib
    reporter = Reporter()
    path_a = os.path.abspath(args.backup_a)
    path_b = os.path.abspath(args.backup_b)

    for p in [path_a, path_b]:
        if not os.path.exists(p):
            reporter.print_error(f"No se encuentra: {p}")
            sys.exit(1)

    reporter.print_header("Comparación de backups")

    def file_hash(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    size_a = os.path.getsize(path_a)
    size_b = os.path.getsize(path_b)
    hash_a = file_hash(path_a)
    hash_b = file_hash(path_b)
    mtime_a = datetime.fromtimestamp(os.path.getmtime(path_a)).strftime("%Y-%m-%d %H:%M")
    mtime_b = datetime.fromtimestamp(os.path.getmtime(path_b)).strftime("%Y-%m-%d %H:%M")

    name_a = os.path.basename(path_a)[:28]
    name_b = os.path.basename(path_b)[:28]

    print(f"  {'':20} {name_a:<30} {name_b:<30}")
    print(f"  {'─'*20} {'─'*30} {'─'*30}")
    print(f"  {'Tamaño':<20} {size_a/(1024*1024):.2f} MB{'':<22} {size_b/(1024*1024):.2f} MB")
    print(f"  {'Modificado':<20} {mtime_a:<30} {mtime_b:<30}")
    print(f"  {'SHA-256':<20} {hash_a[:24]}...   {hash_b[:24]}...")

    identical = hash_a == hash_b
    if identical:
        print(f"\n  \033[1;32m✔ Los backups son IDÉNTICOS\033[0m")
    else:
        diff_pct = abs(size_a - size_b) / max(size_a, size_b, 1) * 100
        print(f"\n  \033[1;33m≠ Los backups son DIFERENTES\033[0m (tamaño: {diff_pct:.1f}% diferencia)")
    print()


def run_report(args, history):
    reporter = Reporter()
    results = history.load(last=args.last)

    if getattr(args, "failed", False):
        results = [r for r in results if not r["passed"]]

    if not results:
        reporter.print_info("No hay verificaciones registradas.")
        return

    export = getattr(args, "export", None)
    if export == "json":
        import json
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    elif export == "html":
        _export_history_html(results)
        return

    reporter.print_header(f"Últimas {len(results)} verificaciones")
    reporter.print_history(results)


def _export_history_html(results):
    rows = ""
    for r in results:
        color = "#22c55e" if r["passed"] else "#ef4444"
        status = "✔ OK" if r["passed"] else "✘ FAIL"
        rows += f'<tr><td>{r["timestamp"][:19]}</td><td>{r["backup_type"]}</td><td style="font-size:0.85em">{r["backup_path"]}</td><td style="color:{color};font-weight:bold">{status}</td></tr>\n'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>SELLO — Historial</title>
<style>body{{font-family:system-ui;max-width:1000px;margin:40px auto;padding:0 20px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f5f5f5;font-weight:600}}</style></head>
<body><h1>🔒 SELLO — Historial de Verificaciones</h1>
<table><tr><th>Fecha</th><th>Tipo</th><th>Backup</th><th>Estado</th></tr>{rows}</table>
<p style="color:#999;font-size:0.8em">Exportado {datetime.now().isoformat()}</p></body></html>"""
    filename = f"sello-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Historial exportado: {filename}")


def run_init():
    reporter = Reporter()
    path = save_default_config()
    reporter.print_info(f"Configuración creada: {path}")
    reporter.print_info("Edítala para configurar notificaciones y backups.")
    reporter.print_info("")
    reporter.print_info("Próximos pasos:")
    reporter.print_info("  1. Edita ~/.sello/config.json")
    reporter.print_info("  2. Configura Telegram/Slack/Email")
    reporter.print_info("  3. sello verify /ruta/backup.tar.gz")
    reporter.print_info("  4. sello watch /backups/ --notify")


def run_trend(args):
    reporter = Reporter()
    anomaly = SizeAnomalyDetector()
    entries = anomaly.get_size_trend(args.backup_path, last=args.last)

    if not entries:
        reporter.print_info("No hay historial de tamaños para este backup.")
        return

    reporter.print_header(f"Tendencia: {os.path.basename(args.backup_path)}")

    max_mb = max(e["size_mb"] for e in entries) or 1
    bar_width = 40

    for entry in entries:
        bar_len = int((entry["size_mb"] / max_mb) * bar_width)
        bar = "█" * bar_len + "░" * (bar_width - bar_len)
        ts = entry["timestamp"][:16]
        print(f"  {ts}  {bar}  {entry['size_mb']:.2f} MB")
    print()
