"""SELLO — Notifications: alert when backups fail verification."""

import json
import os
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

from reporter import VerificationResult


class Notifier:
    """Sends notifications via Telegram, Slack, or email."""

    def __init__(self, config=None):
        """
        config dict example:
        {
            "telegram": {"bot_token": "xxx", "chat_id": "123"},
            "slack": {"webhook_url": "https://hooks.slack.com/..."},
            "email": {"to": "admin@empresa.com", "from": "sello@empresa.com"},
            "notify_on": "failure"  # "failure", "always", "never"
        }
        """
        self.config = config or {}
        self.notify_on = self.config.get("notify_on", "failure")

    def should_notify(self, result: VerificationResult) -> bool:
        if self.notify_on == "never":
            return False
        if self.notify_on == "always":
            return True
        if self.notify_on == "failure":
            return not result.passed
        return False

    def notify(self, result: VerificationResult):
        """Send notification through all configured channels."""
        if not self.should_notify(result):
            return []

        sent = []

        if "telegram" in self.config:
            try:
                self._send_telegram(result)
                sent.append("telegram")
            except Exception as e:
                print(f"  ⚠ Error enviando Telegram: {e}")

        if "slack" in self.config:
            try:
                self._send_slack(result)
                sent.append("slack")
            except Exception as e:
                print(f"  ⚠ Error enviando Slack: {e}")

        if "email" in self.config:
            try:
                self._send_email(result)
                sent.append("email")
            except Exception as e:
                print(f"  ⚠ Error enviando email: {e}")

        return sent

    def _build_message(self, result: VerificationResult) -> str:
        status = "🔒 VERIFICADO" if result.passed else "🔓 FALLIDO"
        failed_checks = [c for c in result.checks if not c.passed and c.severity == "critical"]

        msg = f"SELLO — Backup {status}\n"
        msg += f"📁 {result.backup_path}\n"
        msg += f"📋 Tipo: {result.backup_type}\n"
        msg += f"⏱ Duración: {result.duration_seconds}s\n"
        msg += f"📅 {result.timestamp}\n"

        if failed_checks:
            msg += f"\n❌ {len(failed_checks)} checks fallidos:\n"
            for c in failed_checks:
                msg += f"  • {c.description}: {c.message}\n"

        return msg

    def _send_telegram(self, result: VerificationResult):
        tg = self.config["telegram"]
        token = tg["bot_token"]
        chat_id = tg["chat_id"]
        message = self._build_message(result)

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode()

        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)

    def _send_slack(self, result: VerificationResult):
        webhook = self.config["slack"]["webhook_url"]
        message = self._build_message(result)

        color = "#22c55e" if result.passed else "#ef4444"

        payload = json.dumps({
            "attachments": [{
                "color": color,
                "title": f"SELLO — Backup {'Verificado' if result.passed else 'FALLIDO'}",
                "text": message,
                "footer": "SELLO Backup Verification",
                "ts": int(datetime.now().timestamp())
            }]
        }).encode()

        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)

    def _send_email(self, result: VerificationResult):
        email_cfg = self.config["email"]
        to_addr = email_cfg["to"]
        subject = f"SELLO: Backup {'OK' if result.passed else 'FAILED'} — {os.path.basename(result.backup_path)}"
        body = self._build_message(result)

        # Use system mail command
        process = subprocess.run(
            ["mail", "-s", subject, to_addr],
            input=body, text=True, timeout=30,
            capture_output=True
        )

        if process.returncode != 0:
            raise RuntimeError(f"mail command failed: {process.stderr}")
