"""
SELLO Pro Server — Backend API
FastAPI server that receives verification results from remote agents,
stores them, and serves the dashboard.

Run: uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

import os
import uuid
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Database (SQLite for MVP, swap to PostgreSQL for prod) ──
import sqlite3

DB_PATH = os.environ.get("SELLO_DB_PATH", os.path.expanduser("~/.sello/server.db"))

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            key_hash TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            server_name TEXT,
            created_at TEXT NOT NULL,
            last_used TEXT,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS verifications (
            id TEXT PRIMARY KEY,
            api_key_id TEXT NOT NULL,
            server_name TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            backup_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            duration_seconds REAL,
            passed INTEGER NOT NULL,
            checks_total INTEGER,
            checks_passed INTEGER,
            checks_failed INTEGER,
            size_bytes INTEGER,
            checksum TEXT,
            certificate_json TEXT,
            checks_detail TEXT,
            FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            api_key_id TEXT NOT NULL,
            server_name TEXT NOT NULL,
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            backup_path TEXT,
            created_at TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
        );

        CREATE INDEX IF NOT EXISTS idx_verifications_timestamp ON verifications(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_verifications_server ON verifications(server_name);
        CREATE INDEX IF NOT EXISTS idx_verifications_passed ON verifications(passed);
        CREATE INDEX IF NOT EXISTS idx_alerts_read ON alerts(read);
    """)
    conn.commit()
    conn.close()

init_db()

# ── App ──
app = FastAPI(
    title="SELLO Pro API",
    description="Backup Verification & Certification Platform",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──
def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def verify_api_key(x_api_key: str = Header(...)):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, server_name FROM api_keys WHERE key_hash = ? AND active = 1",
        (hash_key(x_api_key),)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="API key inválida o inactiva")

    # Update last used
    conn = get_db()
    conn.execute("UPDATE api_keys SET last_used = ? WHERE id = ?",
                 (datetime.now().isoformat(), row["id"]))
    conn.commit()
    conn.close()

    return {"id": row["id"], "name": row["name"], "server_name": row["server_name"]}


# ── Models ──
class CheckResult(BaseModel):
    name: str
    description: str
    passed: bool
    message: str
    severity: str = "info"
    details: Optional[dict] = None

class VerificationSubmit(BaseModel):
    backup_path: str
    backup_type: str
    timestamp: str
    duration_seconds: float
    passed: bool
    checks: List[CheckResult]
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    certificate: Optional[dict] = None

class APIKeyCreate(BaseModel):
    name: str
    server_name: Optional[str] = None


# ── Endpoints ──

# Health check
@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0", "service": "sello-pro"}


# ── API Key Management ──

@app.post("/api/keys")
def create_api_key(data: APIKeyCreate):
    """Create a new API key for a server/agent."""
    raw_key = f"sello_{secrets.token_urlsafe(32)}"
    key_id = str(uuid.uuid4())

    conn = get_db()
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, name, server_name, created_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, hash_key(raw_key), data.name, data.server_name, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    return {
        "id": key_id,
        "api_key": raw_key,
        "name": data.name,
        "server_name": data.server_name,
        "message": "Guarda esta API key — no se mostrará de nuevo."
    }

@app.get("/api/keys")
def list_api_keys():
    """List all API keys (without the actual key)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, server_name, created_at, last_used, active FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/keys/{key_id}")
def revoke_api_key(key_id: str):
    """Deactivate an API key."""
    conn = get_db()
    conn.execute("UPDATE api_keys SET active = 0 WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()
    return {"status": "revoked", "id": key_id}


# ── Verification Results ──

@app.post("/api/verify")
def submit_verification(data: VerificationSubmit, auth=Depends(verify_api_key)):
    """Submit a verification result from a remote agent."""
    verif_id = str(uuid.uuid4())

    checks_detail = json.dumps([c.dict() for c in data.checks], ensure_ascii=False)
    cert_json = json.dumps(data.certificate, ensure_ascii=False) if data.certificate else None

    conn = get_db()
    conn.execute("""
        INSERT INTO verifications
        (id, api_key_id, server_name, backup_path, backup_type, timestamp,
         duration_seconds, passed, checks_total, checks_passed, checks_failed,
         size_bytes, checksum, certificate_json, checks_detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        verif_id, auth["id"], auth["server_name"] or auth["name"],
        data.backup_path, data.backup_type, data.timestamp,
        data.duration_seconds, int(data.passed),
        len(data.checks), sum(1 for c in data.checks if c.passed),
        sum(1 for c in data.checks if not c.passed),
        data.size_bytes, data.checksum, cert_json, checks_detail
    ))

    # Create alert if failed
    if not data.passed:
        failed_checks = [c for c in data.checks if not c.passed and c.severity == "critical"]
        fail_reasons = "; ".join(c.message for c in failed_checks[:3])
        alert_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO alerts (id, api_key_id, server_name, type, message, backup_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            alert_id, auth["id"], auth["server_name"] or auth["name"],
            "critical", f"Backup fallido: {fail_reasons}",
            data.backup_path, datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()

    return {
        "id": verif_id,
        "status": "received",
        "passed": data.passed,
        "server_name": auth["server_name"] or auth["name"],
    }

@app.get("/api/verifications")
def list_verifications(
    last: int = 50,
    server: Optional[str] = None,
    passed: Optional[bool] = None
):
    """List verification results with optional filters."""
    conn = get_db()
    query = "SELECT * FROM verifications WHERE 1=1"
    params = []

    if server:
        query += " AND server_name = ?"
        params.append(server)
    if passed is not None:
        query += " AND passed = ?"
        params.append(int(passed))

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(last)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        d["passed"] = bool(d["passed"])
        if d["checks_detail"]:
            d["checks_detail"] = json.loads(d["checks_detail"])
        if d["certificate_json"]:
            d["certificate_json"] = json.loads(d["certificate_json"])
        results.append(d)

    return results

@app.get("/api/verifications/{verif_id}")
def get_verification(verif_id: str):
    """Get a single verification with full detail."""
    conn = get_db()
    row = conn.execute("SELECT * FROM verifications WHERE id = ?", (verif_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Verificación no encontrada")

    d = dict(row)
    d["passed"] = bool(d["passed"])
    if d["checks_detail"]:
        d["checks_detail"] = json.loads(d["checks_detail"])
    if d["certificate_json"]:
        d["certificate_json"] = json.loads(d["certificate_json"])
    return d


# ── Dashboard Stats ──

@app.get("/api/stats")
def get_stats():
    """Dashboard statistics."""
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) as c FROM verifications").fetchone()["c"]
    passed = conn.execute("SELECT COUNT(*) as c FROM verifications WHERE passed = 1").fetchone()["c"]
    failed = total - passed

    # Last 24h
    yesterday = (datetime.now() - timedelta(hours=24)).isoformat()
    recent_total = conn.execute(
        "SELECT COUNT(*) as c FROM verifications WHERE timestamp > ?", (yesterday,)
    ).fetchone()["c"]
    recent_passed = conn.execute(
        "SELECT COUNT(*) as c FROM verifications WHERE timestamp > ? AND passed = 1", (yesterday,)
    ).fetchone()["c"]

    # Servers
    servers = conn.execute(
        "SELECT DISTINCT server_name FROM verifications"
    ).fetchall()

    # Total data verified (sum of size_bytes)
    total_size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) as s FROM verifications WHERE timestamp > ?", (yesterday,)
    ).fetchone()["s"]

    # Unread alerts
    unread_alerts = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE read = 0"
    ).fetchone()["c"]

    conn.close()

    return {
        "total_verifications": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "last_24h": {
            "total": recent_total,
            "passed": recent_passed,
            "failed": recent_total - recent_passed,
        },
        "servers": len(servers),
        "server_names": [s["server_name"] for s in servers],
        "data_verified_bytes_24h": total_size,
        "unread_alerts": unread_alerts,
    }


# ── Alerts ──

@app.get("/api/alerts")
def list_alerts(last: int = 20, unread_only: bool = False):
    """List alerts."""
    conn = get_db()
    query = "SELECT * FROM alerts"
    params = []

    if unread_only:
        query += " WHERE read = 0"

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(last)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.put("/api/alerts/{alert_id}/read")
def mark_alert_read(alert_id: str):
    """Mark an alert as read."""
    conn = get_db()
    conn.execute("UPDATE alerts SET read = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    return {"status": "read", "id": alert_id}


# ── Server Overview ──

@app.get("/api/servers")
def list_servers():
    """List servers with their latest verification status."""
    conn = get_db()

    servers = conn.execute("""
        SELECT
            server_name,
            COUNT(*) as total_verifications,
            SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed,
            SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) as failed,
            MAX(timestamp) as last_verification,
            COALESCE(SUM(size_bytes), 0) as total_size
        FROM verifications
        GROUP BY server_name
        ORDER BY last_verification DESC
    """).fetchall()

    conn.close()

    results = []
    for s in servers:
        d = dict(s)
        # Determine status
        last_passed = None
        conn2 = get_db()
        last = conn2.execute(
            "SELECT passed FROM verifications WHERE server_name = ? ORDER BY timestamp DESC LIMIT 1",
            (d["server_name"],)
        ).fetchone()
        conn2.close()

        if last:
            d["status"] = "ok" if last["passed"] else "fail"
        else:
            d["status"] = "unknown"

        results.append(d)

    return results


# ── Size Trend ──

@app.get("/api/trends/{server_name}")
def get_size_trend(server_name: str, backup_pattern: Optional[str] = None, last: int = 30):
    """Get size trend for a server's backups."""
    conn = get_db()

    query = "SELECT backup_path, size_bytes, timestamp, passed FROM verifications WHERE server_name = ?"
    params = [server_name]

    if backup_pattern:
        query += " AND backup_path LIKE ?"
        params.append(f"%{backup_pattern}%")

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(last)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [{"backup_path": r["backup_path"], "size_bytes": r["size_bytes"],
             "size_mb": round(r["size_bytes"] / (1024*1024), 2) if r["size_bytes"] else 0,
             "timestamp": r["timestamp"], "passed": bool(r["passed"])} for r in reversed(list(rows))]


# ── Startup message ──
@app.on_event("startup")
def startup():
    print("\n🔒 SELLO Pro Server v0.2.0")
    print(f"   Database: {DB_PATH}")
    print(f"   API docs: http://localhost:8000/docs")
    print()
