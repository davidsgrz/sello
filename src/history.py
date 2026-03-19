"""SELLO — History Manager: stores verification results for audit trail."""

import json
import os
from datetime import datetime


class HistoryManager:
    """Manages verification history stored as JSON."""

    HISTORY_DIR = os.path.expanduser("~/.sello")
    HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")

    def __init__(self):
        os.makedirs(self.HISTORY_DIR, exist_ok=True)
        if not os.path.exists(self.HISTORY_FILE):
            with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)

    def save(self, result):
        """Append a verification result to history."""
        history = self._load_all()

        entry = {
            "backup_path": result.backup_path,
            "backup_type": result.backup_type,
            "timestamp": result.timestamp,
            "duration_seconds": result.duration_seconds,
            "passed": result.passed,
            "checks_total": len(result.checks),
            "checks_passed": sum(1 for c in result.checks if c.passed),
            "checks_failed": sum(1 for c in result.checks if not c.passed),
            "certificate_path": result.certificate_path,
        }

        history.append(entry)

        # Keep last 1000 entries
        if len(history) > 1000:
            history = history[-1000:]

        with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def load(self, last=10):
        """Load last N verification results."""
        history = self._load_all()
        return history[-last:]

    def _load_all(self):
        try:
            with open(self.HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
