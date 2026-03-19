"""SELLO — Certificate Generator: creates tamper-evident verification certificates."""

import json
import hashlib
import os
from datetime import datetime, timezone

from reporter import VerificationResult


class CertificateGenerator:
    """Generates verification certificates (JSON with integrity hash)."""

    CERT_DIR = os.path.expanduser("~/.sello/certificates")

    def __init__(self):
        os.makedirs(self.CERT_DIR, exist_ok=True)

    def generate(self, result: VerificationResult) -> str:
        """Generate a verification certificate for a passed backup."""
        cert_data = {
            "sello_certificate": {
                "version": "0.1.0",
                "issued_at": datetime.now(timezone.utc).isoformat(),
                "backup": {
                    "path": result.backup_path,
                    "type": result.backup_type,
                    "verified_at": result.timestamp,
                    "verification_duration_seconds": result.duration_seconds,
                },
                "result": {
                    "status": "VERIFIED" if result.passed else "FAILED",
                    "checks_total": len(result.checks),
                    "checks_passed": sum(1 for c in result.checks if c.passed),
                    "checks_failed": sum(1 for c in result.checks if not c.passed),
                    "critical_checks_passed": sum(
                        1 for c in result.checks if c.severity == "critical" and c.passed
                    ),
                    "critical_checks_total": sum(
                        1 for c in result.checks if c.severity == "critical"
                    ),
                },
                "details": [
                    {
                        "check": c.name,
                        "description": c.description,
                        "passed": c.passed,
                        "message": c.message,
                        "severity": c.severity,
                    }
                    for c in result.checks
                ],
                "environment": {
                    "hostname": self._get_hostname(),
                    "user": os.environ.get("USER", "unknown"),
                },
            }
        }

        # Generate integrity hash
        cert_json = json.dumps(cert_data, sort_keys=True, ensure_ascii=False)
        integrity_hash = hashlib.sha256(cert_json.encode()).hexdigest()
        cert_data["sello_certificate"]["integrity_hash"] = integrity_hash

        # Save certificate
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_name = os.path.basename(result.backup_path).replace(".", "_")
        cert_filename = f"sello-cert-{backup_name}-{timestamp}.json"
        cert_path = os.path.join(self.CERT_DIR, cert_filename)

        with open(cert_path, "w", encoding="utf-8") as f:
            json.dump(cert_data, f, indent=2, ensure_ascii=False)

        return cert_path

    def _get_hostname(self):
        try:
            import socket
            return socket.gethostname()
        except Exception:
            return "unknown"
