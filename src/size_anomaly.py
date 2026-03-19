"""SELLO — Size Anomaly Detection: detect unusual backup size changes."""

import os
import json
from reporter import Check


class SizeAnomalyDetector:
    """Detects anomalous backup sizes by comparing with historical data."""

    HISTORY_PATH = os.path.expanduser("~/.sello/size_history.json")

    def __init__(self, max_deviation_percent=80, min_size_mb=0.001, compare_with_last=5):
        self.max_deviation = max_deviation_percent
        self.min_size_mb = min_size_mb
        self.compare_count = compare_with_last
        self._ensure_history()

    def _ensure_history(self):
        os.makedirs(os.path.dirname(self.HISTORY_PATH), exist_ok=True)
        if not os.path.exists(self.HISTORY_PATH):
            with open(self.HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _load_history(self):
        try:
            with open(self.HISTORY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_history(self, data):
        with open(self.HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def record_size(self, backup_path, size_bytes):
        """Record a backup's size for future comparison."""
        history = self._load_history()
        key = self._normalize_key(backup_path)

        if key not in history:
            history[key] = []

        history[key].append({
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 4),
            "timestamp": __import__("datetime").datetime.now().isoformat()
        })

        # Keep last 100 entries per backup
        history[key] = history[key][-100:]
        self._save_history(history)

    def check_anomaly(self, backup_path, current_size_bytes) -> Check:
        """Check if current size is anomalous compared to history."""
        history = self._load_history()
        key = self._normalize_key(backup_path)

        current_mb = current_size_bytes / (1024 * 1024)

        # Record current size
        self.record_size(backup_path, current_size_bytes)

        # Not enough history?
        entries = history.get(key, [])
        if len(entries) < 2:
            return Check(
                name="size_anomaly",
                description="Anomalía de tamaño (comparación histórica)",
                passed=True,
                message=f"Primera verificación registrada ({current_mb:.2f} MB). Se comparará en futuras ejecuciones.",
                severity="info",
                details={"current_mb": round(current_mb, 4), "history_count": len(entries)}
            )

        # Compare with last N entries (excluding current which we just added)
        previous = entries[-(self.compare_count + 1):-1]
        if not previous:
            previous = entries[:-1]

        avg_size = sum(e["size_bytes"] for e in previous) / len(previous)
        avg_mb = avg_size / (1024 * 1024)

        if avg_size == 0:
            return Check(
                name="size_anomaly",
                description="Anomalía de tamaño",
                passed=True,
                message="Historial de tamaños vacío (0 bytes). No se puede comparar.",
                severity="info"
            )

        deviation_percent = abs(current_size_bytes - avg_size) / avg_size * 100

        # Check minimum size
        if current_mb < self.min_size_mb and avg_mb > self.min_size_mb * 10:
            return Check(
                name="size_anomaly",
                description="Anomalía de tamaño",
                passed=False,
                message=f"⚠️ Backup sospechosamente pequeño: {current_mb:.4f} MB vs promedio {avg_mb:.2f} MB ({deviation_percent:.0f}% desviación). ¿Backup truncado?",
                severity="critical",
                details={
                    "current_mb": round(current_mb, 4),
                    "average_mb": round(avg_mb, 4),
                    "deviation_percent": round(deviation_percent, 1),
                    "threshold_percent": self.max_deviation,
                    "compared_with": len(previous)
                }
            )

        # Check deviation threshold
        if deviation_percent > self.max_deviation:
            direction = "mayor" if current_size_bytes > avg_size else "menor"
            return Check(
                name="size_anomaly",
                description="Anomalía de tamaño (comparación histórica)",
                passed=False,
                message=f"⚠️ Tamaño {direction} de lo normal: {current_mb:.2f} MB vs promedio {avg_mb:.2f} MB ({deviation_percent:.0f}% desviación, umbral: {self.max_deviation}%)",
                severity="warning",
                details={
                    "current_mb": round(current_mb, 4),
                    "average_mb": round(avg_mb, 4),
                    "deviation_percent": round(deviation_percent, 1),
                    "direction": direction,
                    "threshold_percent": self.max_deviation,
                    "compared_with": len(previous)
                }
            )

        return Check(
            name="size_anomaly",
            description="Anomalía de tamaño (comparación histórica)",
            passed=True,
            message=f"Tamaño normal: {current_mb:.2f} MB (promedio: {avg_mb:.2f} MB, desviación: {deviation_percent:.1f}%)",
            severity="info",
            details={
                "current_mb": round(current_mb, 4),
                "average_mb": round(avg_mb, 4),
                "deviation_percent": round(deviation_percent, 1),
                "compared_with": len(previous)
            }
        )

    def _normalize_key(self, path):
        """Normalize backup path for grouping similar backups.

        /backups/daily-20260318.tar.gz -> /backups/daily-*.tar.gz
        This groups daily backups together for comparison.
        """
        import re
        basename = os.path.basename(path)
        # Replace date-like patterns with *
        normalized = re.sub(r'\d{4}[-_]?\d{2}[-_]?\d{2}', '*', basename)
        # Replace timestamp-like patterns
        normalized = re.sub(r'\d{10,}', '*', normalized)
        return os.path.join(os.path.dirname(path), normalized)


    def get_size_trend(self, backup_path, last=10):
        """Get size trend for a backup path."""
        history = self._load_history()
        key = self._normalize_key(backup_path)
        entries = history.get(key, [])
        return entries[-last:]
