"""SELLO — Reporter: output formatting for verification results."""

import json
import sys
import os
import platform
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime, timezone


def _enable_ansi_windows():
    """Enable ANSI escape codes on Windows 10+ terminals."""
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Enable VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

_enable_ansi_windows()


@dataclass
class Check:
    name: str
    description: str
    passed: bool
    message: str
    severity: str = "info"  # critical, warning, info
    details: Optional[dict] = None


@dataclass
class VerificationResult:
    backup_path: str
    backup_type: str
    timestamp: str
    duration_seconds: float
    passed: bool
    checks: List[Check]
    certificate_path: Optional[str] = None


class Reporter:
    """Formats and outputs verification results."""

    ICONS = {
        True: "\033[1;32m✔\033[0m",   # Green check
        False: "\033[1;31m✘\033[0m",   # Red cross
        "warning": "\033[1;33m⚠\033[0m",  # Yellow warning
    }

    def print_header(self, text):
        print(f"\n\033[1;37m{'─' * 50}\033[0m")
        print(f"\033[1;37m  {text}\033[0m")
        print(f"\033[1;37m{'─' * 50}\033[0m\n")

    def print_info(self, text):
        print(f"  \033[0;36mℹ\033[0m  {text}")

    def print_error(self, text):
        print(f"  \033[1;31m✘\033[0m  {text}")

    def output(self, result: VerificationResult, format="terminal"):
        if format == "terminal":
            self._output_terminal(result)
        elif format == "json":
            self._output_json(result)
        elif format == "html":
            self._output_html(result)

    def _output_terminal(self, result: VerificationResult):
        # Print each check
        for check in result.checks:
            if check.severity == "warning" and check.passed:
                icon = self.ICONS["warning"]
            else:
                icon = self.ICONS[check.passed]

            print(f"  {icon}  \033[1m{check.description}\033[0m")
            print(f"     {check.message}")
            print()

        # Summary
        print(f"\033[1;37m{'─' * 50}\033[0m")

        critical_checks = [c for c in result.checks if c.severity == "critical"]
        passed_count = sum(1 for c in critical_checks if c.passed)
        total_count = len(critical_checks)

        if result.passed:
            print(f"\n  \033[1;32m🔒 BACKUP VERIFICADO\033[0m")
            print(f"     {passed_count}/{total_count} checks críticos pasados")
        else:
            print(f"\n  \033[1;31m🔓 BACKUP NO VERIFICADO\033[0m")
            failed = [c for c in critical_checks if not c.passed]
            print(f"     {len(failed)} checks críticos fallaron:")
            for c in failed:
                print(f"       • {c.description}: {c.message}")

        print(f"\n     Duración: {result.duration_seconds}s")
        print(f"     Timestamp: {result.timestamp}")

        if result.certificate_path:
            print(f"     Certificado: {result.certificate_path}")

        print()

    def _output_json(self, result: VerificationResult):
        output = {
            "sello_version": "0.1.0",
            "backup_path": result.backup_path,
            "backup_type": result.backup_type,
            "timestamp": result.timestamp,
            "duration_seconds": result.duration_seconds,
            "passed": result.passed,
            "certificate_path": result.certificate_path,
            "checks": [
                {
                    "name": c.name,
                    "description": c.description,
                    "passed": c.passed,
                    "message": c.message,
                    "severity": c.severity,
                    "details": c.details
                }
                for c in result.checks
            ]
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))

    def _output_html(self, result: VerificationResult):
        checks_html = ""
        for check in result.checks:
            icon = "✔" if check.passed else "✘"
            color = "#22c55e" if check.passed else "#ef4444"
            if check.severity == "warning" and check.passed:
                icon = "⚠"
                color = "#eab308"

            checks_html += f"""
            <div style="padding:12px;border-left:3px solid {color};margin-bottom:8px;background:#f8f9fa">
                <strong style="color:{color}">{icon} {check.description}</strong><br>
                <span style="color:#666">{check.message}</span>
            </div>
            """

        status_color = "#22c55e" if result.passed else "#ef4444"
        status_text = "🔒 BACKUP VERIFICADO" if result.passed else "🔓 BACKUP NO VERIFICADO"

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>SELLO — Informe de Verificación</title>
    <style>
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }}
        h1 {{ color: #1a1a1a; border-bottom: 2px solid #e5e7eb; padding-bottom: 16px; }}
        .status {{ background: {status_color}; color: white; padding: 16px 24px; border-radius: 8px; font-size: 1.2em; font-weight: bold; margin: 24px 0; }}
        .meta {{ color: #666; font-size: 0.9em; margin-bottom: 24px; }}
        .meta span {{ margin-right: 24px; }}
    </style>
</head>
<body>
    <h1>🔒 SELLO — Informe de Verificación</h1>
    <div class="meta">
        <span><strong>Backup:</strong> {result.backup_path}</span><br>
        <span><strong>Tipo:</strong> {result.backup_type}</span>
        <span><strong>Fecha:</strong> {result.timestamp}</span>
        <span><strong>Duración:</strong> {result.duration_seconds}s</span>
    </div>
    <div class="status">{status_text}</div>
    <h2>Checks realizados</h2>
    {checks_html}
    <hr>
    <p style="color:#999;font-size:0.8em">Generado por SELLO v0.1.0 — {result.timestamp}</p>
</body>
</html>"""

        # Save to file
        filename = f"sello-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Informe HTML generado: {filename}")

    def print_history(self, results):
        """Print history table."""
        print(f"  {'Fecha':<22} {'Tipo':<12} {'Backup':<35} {'Estado'}")
        print(f"  {'─'*22} {'─'*12} {'─'*35} {'─'*10}")

        for r in results:
            icon = "\033[1;32m✔ OK\033[0m" if r["passed"] else "\033[1;31m✘ FAIL\033[0m"
            path = r["backup_path"]
            if len(path) > 33:
                path = "..." + path[-30:]
            print(f"  {r['timestamp']:<22} {r['backup_type']:<12} {path:<35} {icon}")

        print()
