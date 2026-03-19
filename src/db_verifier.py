"""SELLO — Database Dump Verifier."""

import os
import re
import time
import tempfile
import subprocess
import shutil
from datetime import datetime, timezone

from reporter import VerificationResult, Check


class DBVerifier:
    """Verifies database dump files (MySQL, PostgreSQL, SQLite)."""

    def verify(self, dump_path, engine):
        start_time = time.time()
        checks = []

        # Basic file checks
        checks.append(self._check_file(dump_path))
        if not checks[-1].passed:
            return self._build_result(dump_path, engine, checks, start_time)

        checks.append(self._check_size(dump_path))

        # Detect if compressed
        is_compressed, compression = self._detect_compression(dump_path)
        if is_compressed:
            checks.append(Check(
                name="compression",
                description="Compresión detectada",
                passed=True,
                message=f"Archivo comprimido con {compression}",
                severity="info"
            ))

        # Engine-specific verification
        if engine == "mysql":
            checks.extend(self._verify_mysql(dump_path, is_compressed, compression))
        elif engine == "postgres":
            checks.extend(self._verify_postgres(dump_path, is_compressed, compression))
        elif engine == "sqlite":
            checks.extend(self._verify_sqlite(dump_path))

        return self._build_result(dump_path, engine, checks, start_time)

    def _check_file(self, path):
        exists = os.path.exists(path) and os.path.isfile(path)
        return Check(
            name="file_exists",
            description="El dump existe",
            passed=exists,
            message="Archivo encontrado" if exists else "Archivo no encontrado",
            severity="critical"
        )

    def _check_size(self, path):
        size = os.path.getsize(path)
        size_mb = size / (1024 * 1024)
        return Check(
            name="size",
            description="Tamaño del dump",
            passed=size > 0,
            message=f"Tamaño: {size_mb:.2f} MB",
            severity="critical",
            details={"size_bytes": size, "size_mb": round(size_mb, 2)}
        )

    def _detect_compression(self, path):
        name = path.lower()
        if name.endswith(".gz") or name.endswith(".gzip"):
            return True, "gzip"
        elif name.endswith(".bz2"):
            return True, "bzip2"
        elif name.endswith(".xz"):
            return True, "xz"
        elif name.endswith(".zst") or name.endswith(".zstd"):
            return True, "zstd"

        # Check magic bytes
        try:
            with open(path, "rb") as f:
                header = f.read(4)
                if header[:2] == b'\x1f\x8b':
                    return True, "gzip"
                elif header[:3] == b'BZh':
                    return True, "bzip2"
                elif header[:6] == b'\xfd7zXZ\x00':
                    return True, "xz"
        except Exception:
            pass

        return False, None

    def _read_file_content(self, path, is_compressed, compression, max_bytes=None):
        """Read file content using pure Python — cross-platform (no cat/zcat)."""
        import gzip
        import bz2
        import lzma

        try:
            if not is_compressed:
                with open(path, "rb") as f:
                    return f.read(max_bytes) if max_bytes else f.read()
            elif compression == "gzip":
                with gzip.open(path, "rb") as f:
                    return f.read(max_bytes) if max_bytes else f.read()
            elif compression == "bzip2":
                with bz2.open(path, "rb") as f:
                    return f.read(max_bytes) if max_bytes else f.read()
            elif compression == "xz":
                with lzma.open(path, "rb") as f:
                    return f.read(max_bytes) if max_bytes else f.read()
            elif compression == "zstd":
                # zstd not in stdlib — fallback to reading raw
                with open(path, "rb") as f:
                    return f.read(max_bytes) if max_bytes else f.read()
            else:
                with open(path, "rb") as f:
                    return f.read(max_bytes) if max_bytes else f.read()
        except Exception as e:
            raise RuntimeError(f"Error leyendo {path}: {e}")

    # ── MySQL verification ──

    def _verify_mysql(self, path, is_compressed, compression):
        checks = []

        # Parse SQL content using pure Python (cross-platform)
        try:
            # Read header first (8KB) for format detection
            content_start_bytes = self._read_file_content(path, is_compressed, compression, max_bytes=8192)
            content_start = content_start_bytes.decode("utf-8", errors="replace")

            # Look for MySQL dump markers
            has_mysql_marker = "MySQL dump" in content_start or "mysqldump" in content_start.lower()
            has_create = "CREATE TABLE" in content_start.upper() or "CREATE DATABASE" in content_start.upper()

            checks.append(Check(
                name="mysql_format",
                description="Formato MySQL válido",
                passed=has_mysql_marker or has_create,
                message="Dump MySQL reconocido" if (has_mysql_marker or has_create)
                        else "No se reconoce como dump MySQL",
                severity="critical"
            ))

            # Read more content for deeper analysis (limit 50MB to avoid OOM)
            MAX_ANALYSIS_SIZE = 50 * 1024 * 1024
            full_bytes = self._read_file_content(path, is_compressed, compression, max_bytes=MAX_ANALYSIS_SIZE)
            full_content = full_bytes.decode("utf-8", errors="replace")
            tables = re.findall(r'CREATE TABLE\s+(?:`?(\w+)`?)', full_content, re.IGNORECASE)

            checks.append(Check(
                name="mysql_tables",
                description="Tablas encontradas en el dump",
                passed=len(tables) > 0,
                message=f"{len(tables)} tablas: {', '.join(tables[:10])}{'...' if len(tables) > 10 else ''}",
                severity="critical",
                details={"table_count": len(tables), "tables": tables[:50]}
            ))

            # Check for completeness marker
            has_completion = "Dump completed" in full_content or "-- Dump completed" in full_content
            checks.append(Check(
                name="mysql_complete",
                description="Dump completado correctamente",
                passed=has_completion,
                message="Marcador de finalización encontrado" if has_completion
                        else "⚠️  No se encontró marcador de finalización. El dump puede estar truncado.",
                severity="warning" if not has_completion else "info"
            ))

            # Try loading into temp SQLite as syntax check (basic)
            insert_count = len(re.findall(r'INSERT INTO', full_content, re.IGNORECASE))
            checks.append(Check(
                name="mysql_data",
                description="Sentencias INSERT detectadas",
                passed=insert_count > 0,
                message=f"{insert_count} sentencias INSERT encontradas",
                severity="info",
                details={"insert_count": insert_count}
            ))

        except subprocess.TimeoutExpired:
            checks.append(Check(
                name="mysql_parse",
                description="Parseo del dump MySQL",
                passed=False,
                message="Timeout: archivo demasiado grande para parseo completo",
                severity="warning"
            ))
        except Exception as e:
            checks.append(Check(
                name="mysql_parse",
                description="Parseo del dump MySQL",
                passed=False,
                message=f"Error: {e}",
                severity="critical"
            ))

        return checks

    # ── PostgreSQL verification ──

    def _verify_postgres(self, path, is_compressed, compression):
        checks = []

        try:
            # Read header for format detection
            content_start_bytes = self._read_file_content(path, is_compressed, compression, max_bytes=8192)
            content_start = content_start_bytes.decode("utf-8", errors="replace")

            # Check for pg_dump markers
            has_pg_marker = "PostgreSQL database dump" in content_start or "pg_dump" in content_start
            has_create = "CREATE TABLE" in content_start.upper()

            # Also check for custom format (binary)
            is_custom_format = content_start_bytes[:5] == b'PGDMP'

            if is_custom_format:
                checks.append(Check(
                    name="pg_format",
                    description="Formato PostgreSQL válido",
                    passed=True,
                    message="Dump PostgreSQL en formato custom (binario)",
                    severity="critical"
                ))

                # Try pg_restore --list
                checks.extend(self._verify_pg_custom(path))
                return checks

            checks.append(Check(
                name="pg_format",
                description="Formato PostgreSQL válido",
                passed=has_pg_marker or has_create,
                message="Dump PostgreSQL reconocido" if (has_pg_marker or has_create)
                        else "No se reconoce como dump PostgreSQL",
                severity="critical"
            ))

            MAX_ANALYSIS_SIZE = 50 * 1024 * 1024
            full_bytes = self._read_file_content(path, is_compressed, compression, max_bytes=MAX_ANALYSIS_SIZE)
            full_content = full_bytes.decode("utf-8", errors="replace")

            # Count tables
            tables = re.findall(r'CREATE TABLE\s+(?:(?:public|"?\w+"?)\.)?(?:"?(\w+)"?)', full_content, re.IGNORECASE)
            checks.append(Check(
                name="pg_tables",
                description="Tablas encontradas",
                passed=len(tables) > 0,
                message=f"{len(tables)} tablas: {', '.join(tables[:10])}{'...' if len(tables) > 10 else ''}",
                severity="critical",
                details={"table_count": len(tables), "tables": tables[:50]}
            ))

            # Completion check
            has_completion = "PostgreSQL database dump complete" in full_content
            checks.append(Check(
                name="pg_complete",
                description="Dump completado",
                passed=has_completion,
                message="Marcador de finalización encontrado" if has_completion
                        else "⚠️  Sin marcador de finalización. Posible truncamiento.",
                severity="warning" if not has_completion else "info"
            ))

            # COPY/INSERT count
            copy_count = len(re.findall(r'^COPY\s+', full_content, re.IGNORECASE | re.MULTILINE))
            insert_count = len(re.findall(r'INSERT INTO', full_content, re.IGNORECASE))
            data_ops = copy_count + insert_count

            checks.append(Check(
                name="pg_data",
                description="Operaciones de datos detectadas",
                passed=data_ops > 0,
                message=f"{copy_count} COPY + {insert_count} INSERT = {data_ops} operaciones de datos",
                severity="info",
                details={"copy_count": copy_count, "insert_count": insert_count}
            ))

        except subprocess.TimeoutExpired:
            checks.append(Check(
                name="pg_parse",
                description="Parseo del dump PostgreSQL",
                passed=False,
                message="Timeout: archivo demasiado grande",
                severity="warning"
            ))
        except Exception as e:
            checks.append(Check(
                name="pg_parse",
                description="Parseo del dump PostgreSQL",
                passed=False,
                message=f"Error: {e}",
                severity="critical"
            ))

        return checks

    def _verify_pg_custom(self, path):
        """Verify PostgreSQL custom format dump using pg_restore --list."""
        checks = []

        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            checks.append(Check(
                name="pg_restore_list",
                description="pg_restore disponible",
                passed=False,
                message="pg_restore no encontrado. Instala postgresql-client para verificación completa.",
                severity="warning"
            ))
            return checks

        try:
            result = subprocess.run(
                ["pg_restore", "--list", path],
                capture_output=True, text=True, timeout=60
            )

            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split("\n") if l and not l.startswith(";")]
                table_lines = [l for l in lines if "TABLE" in l]
                checks.append(Check(
                    name="pg_restore_list",
                    description="Contenido del dump (pg_restore --list)",
                    passed=True,
                    message=f"{len(lines)} objetos totales, {len(table_lines)} tablas",
                    severity="critical",
                    details={"object_count": len(lines), "table_count": len(table_lines)}
                ))
            else:
                checks.append(Check(
                    name="pg_restore_list",
                    description="Contenido del dump",
                    passed=False,
                    message=f"Error: {result.stderr.strip()[:200]}",
                    severity="critical"
                ))
        except Exception as e:
            checks.append(Check(
                name="pg_restore_list",
                description="Verificación pg_restore",
                passed=False,
                message=f"Error: {e}",
                severity="warning"
            ))

        return checks

    # ── SQLite verification ──

    def _verify_sqlite(self, path):
        checks = []

        # Check magic bytes
        try:
            with open(path, "rb") as f:
                header = f.read(16)
                is_sqlite = header[:16] == b'SQLite format 3\x00'

            checks.append(Check(
                name="sqlite_format",
                description="Formato SQLite válido",
                passed=is_sqlite,
                message="Archivo SQLite válido" if is_sqlite else "No es un archivo SQLite válido",
                severity="critical"
            ))

            if not is_sqlite:
                return checks

            # Try opening with sqlite3
            import sqlite3
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Integrity check
            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchone()[0]

            checks.append(Check(
                name="sqlite_integrity",
                description="PRAGMA integrity_check",
                passed=integrity == "ok",
                message=f"Integridad: {integrity}",
                severity="critical"
            ))

            # List tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            checks.append(Check(
                name="sqlite_tables",
                description="Tablas en la base de datos",
                passed=len(tables) > 0,
                message=f"{len(tables)} tablas: {', '.join(tables[:10])}",
                severity="critical",
                details={"table_count": len(tables), "tables": tables}
            ))

            # Row counts
            table_counts = {}
            for table in tables[:20]:
                try:
                    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                    table_counts[table] = cursor.fetchone()[0]
                except Exception:
                    table_counts[table] = -1

            total_rows = sum(v for v in table_counts.values() if v >= 0)
            checks.append(Check(
                name="sqlite_data",
                description="Datos en las tablas",
                passed=total_rows > 0,
                message=f"{total_rows} filas totales en {len(table_counts)} tablas",
                severity="info",
                details={"table_row_counts": table_counts}
            ))

            conn.close()

        except Exception as e:
            checks.append(Check(
                name="sqlite_verify",
                description="Verificación SQLite",
                passed=False,
                message=f"Error: {e}",
                severity="critical"
            ))

        return checks

    def _build_result(self, path, engine, checks, start_time):
        elapsed = time.time() - start_time
        passed = all(c.passed for c in checks if c.severity == "critical")

        return VerificationResult(
            backup_path=path,
            backup_type=f"db_{engine}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(elapsed, 2),
            passed=passed,
            checks=checks,
            certificate_path=None
        )
