"""SELLO — Backup Verifier Engine for file-based backups."""

import os
import sys
import time
import hashlib
import tarfile
import zipfile
import tempfile
import shutil
import subprocess
import json
from datetime import datetime, timezone
from pathlib import Path

from reporter import VerificationResult, Check


class BackupVerifier:
    """Verifies file-based backups (tar, zip, directory, restic, borg)."""

    def detect_type(self, path):
        """Auto-detect backup type from path."""
        if os.path.isdir(path):
            # Check for restic repo markers
            if os.path.exists(os.path.join(path, "config")) and os.path.exists(os.path.join(path, "keys")):
                return "restic"
            # Check for borg repo
            if os.path.exists(os.path.join(path, "README")) and os.path.exists(os.path.join(path, "data")):
                return "borg"
            return "directory"

        name = path.lower()
        if name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
            return "tar"
        elif name.endswith(".zip"):
            return "zip"
        else:
            # Try tar anyway
            try:
                tarfile.open(path)
                return "tar"
            except Exception:
                pass
            try:
                zipfile.ZipFile(path)
                return "zip"
            except Exception:
                pass
            return "unknown"

    def verify(self, path, backup_type):
        """Run full verification suite on a backup."""
        start_time = time.time()
        checks = []

        # 1. Existence & readability
        checks.append(self._check_exists(path))
        checks.append(self._check_readable(path))

        if not all(c.passed for c in checks):
            return self._build_result(path, backup_type, checks, start_time)

        # 2. Size check
        checks.append(self._check_size(path))

        # 3. Freshness check
        checks.append(self._check_freshness(path))

        # 4. Type-specific checks
        if backup_type == "tar":
            checks.extend(self._verify_tar(path))
        elif backup_type == "zip":
            checks.extend(self._verify_zip(path))
        elif backup_type == "directory":
            checks.extend(self._verify_directory(path))
        elif backup_type == "restic":
            checks.extend(self._verify_restic(path))
        elif backup_type == "borg":
            checks.extend(self._verify_borg(path))
        else:
            checks.append(Check(
                name="type_detection",
                description="Detección de tipo de backup",
                passed=False,
                message=f"Tipo de backup no reconocido: {backup_type}",
                severity="critical"
            ))

        # 5. Checksum generation
        if os.path.isfile(path):
            checks.append(self._generate_checksum(path))

        return self._build_result(path, backup_type, checks, start_time)

    def _check_exists(self, path):
        exists = os.path.exists(path)
        return Check(
            name="exists",
            description="El backup existe en disco",
            passed=exists,
            message="Archivo encontrado" if exists else f"No encontrado: {path}",
            severity="critical"
        )

    def _check_readable(self, path):
        readable = os.access(path, os.R_OK)
        return Check(
            name="readable",
            description="El backup es legible",
            passed=readable,
            message="Permisos de lectura OK" if readable else "Sin permisos de lectura",
            severity="critical"
        )

    def _check_size(self, path):
        if os.path.isfile(path):
            size = os.path.getsize(path)
        else:
            size = sum(
                os.path.getsize(os.path.join(dirpath, filename))
                for dirpath, _, filenames in os.walk(path)
                for filename in filenames
            )

        size_mb = size / (1024 * 1024)
        is_empty = size == 0

        return Check(
            name="size",
            description="El backup tiene contenido",
            passed=not is_empty,
            message=f"Tamaño: {size_mb:.2f} MB" if not is_empty else "El backup está vacío (0 bytes)",
            severity="critical",
            details={"size_bytes": size, "size_mb": round(size_mb, 2)}
        )

    def _check_freshness(self, path):
        mtime = os.path.getmtime(path)
        age_hours = (time.time() - mtime) / 3600
        age_days = age_hours / 24

        if age_days <= 1:
            age_str = f"{age_hours:.1f} horas"
        else:
            age_str = f"{age_days:.1f} días"

        # Warn if older than 7 days, fail if older than 30
        if age_days > 30:
            return Check(
                name="freshness",
                description="Antigüedad del backup",
                passed=True,  # Don't fail, just warn
                message=f"⚠️  Backup antiguo: {age_str}. Considera hacer uno nuevo.",
                severity="warning",
                details={"age_hours": round(age_hours, 1), "age_days": round(age_days, 1)}
            )

        return Check(
            name="freshness",
            description="Antigüedad del backup",
            passed=True,
            message=f"Antigüedad: {age_str}",
            severity="info",
            details={"age_hours": round(age_hours, 1), "age_days": round(age_days, 1)}
        )

    def _generate_checksum(self, path):
        """Generate SHA-256 checksum of backup file."""
        try:
            sha256 = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            checksum = sha256.hexdigest()
            return Check(
                name="checksum",
                description="Checksum SHA-256 generado",
                passed=True,
                message=f"SHA-256: {checksum[:16]}...{checksum[-8:]}",
                severity="info",
                details={"sha256": checksum}
            )
        except Exception as e:
            return Check(
                name="checksum",
                description="Checksum SHA-256",
                passed=False,
                message=f"Error generando checksum: {e}",
                severity="warning"
            )

    # ── TAR verification ──

    def _verify_tar(self, path):
        checks = []

        # Can we open it?
        try:
            with tarfile.open(path, "r:*") as tar:
                members = tar.getmembers()
                checks.append(Check(
                    name="tar_integrity",
                    description="Integridad del archivo tar",
                    passed=True,
                    message=f"Archivo tar válido. {len(members)} entradas.",
                    severity="critical",
                    details={"entry_count": len(members)}
                ))

                # Count files vs dirs
                files = [m for m in members if m.isfile()]
                dirs = [m for m in members if m.isdir()]
                total_size = sum(m.size for m in files)

                checks.append(Check(
                    name="tar_contents",
                    description="Contenido del archivo",
                    passed=len(files) > 0,
                    message=f"{len(files)} archivos, {len(dirs)} directorios, {total_size / (1024*1024):.2f} MB descomprimido",
                    severity="critical",
                    details={
                        "file_count": len(files),
                        "dir_count": len(dirs),
                        "uncompressed_size_mb": round(total_size / (1024*1024), 2)
                    }
                ))

                # Try extracting a sample to temp dir
                checks.append(self._try_extract_tar_sample(tar, members))

        except tarfile.TarError as e:
            checks.append(Check(
                name="tar_integrity",
                description="Integridad del archivo tar",
                passed=False,
                message=f"Archivo tar corrupto o inválido: {e}",
                severity="critical"
            ))
        except Exception as e:
            checks.append(Check(
                name="tar_integrity",
                description="Integridad del archivo tar",
                passed=False,
                message=f"Error inesperado: {e}",
                severity="critical"
            ))

        return checks

    def _try_extract_tar_sample(self, tar, members):
        """Try extracting first few files to verify they're readable."""
        sample_files = [m for m in members if m.isfile()][:5]
        if not sample_files:
            return Check(
                name="tar_extract_test",
                description="Test de extracción",
                passed=True,
                message="No hay archivos para extraer (solo directorios)",
                severity="info"
            )

        tmpdir = tempfile.mkdtemp(prefix="sello_")
        try:
            for member in sample_files:
                tar.extract(member, path=tmpdir)

            extracted = []
            for member in sample_files:
                full_path = os.path.join(tmpdir, member.name)
                if os.path.exists(full_path):
                    extracted.append(member.name)

            return Check(
                name="tar_extract_test",
                description="Test de extracción (muestra)",
                passed=len(extracted) == len(sample_files),
                message=f"{len(extracted)}/{len(sample_files)} archivos extraídos correctamente",
                severity="critical",
                details={"extracted_files": extracted}
            )
        except Exception as e:
            return Check(
                name="tar_extract_test",
                description="Test de extracción (muestra)",
                passed=False,
                message=f"Error extrayendo: {e}",
                severity="critical"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── ZIP verification ──

    def _verify_zip(self, path):
        checks = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                # Test CRC integrity
                bad_files = zf.testzip()

                if bad_files is None:
                    info_list = zf.infolist()
                    files = [i for i in info_list if not i.is_dir()]
                    total_size = sum(i.file_size for i in files)

                    checks.append(Check(
                        name="zip_integrity",
                        description="Integridad CRC del ZIP",
                        passed=True,
                        message=f"CRC OK. {len(files)} archivos, {total_size / (1024*1024):.2f} MB descomprimido",
                        severity="critical",
                        details={"file_count": len(files), "uncompressed_size_mb": round(total_size/(1024*1024), 2)}
                    ))

                    # Try extracting sample
                    checks.append(self._try_extract_zip_sample(zf, files))
                else:
                    checks.append(Check(
                        name="zip_integrity",
                        description="Integridad CRC del ZIP",
                        passed=False,
                        message=f"Archivos corruptos detectados. Primer archivo malo: {bad_files}",
                        severity="critical"
                    ))

        except zipfile.BadZipFile as e:
            checks.append(Check(
                name="zip_integrity",
                description="Integridad del ZIP",
                passed=False,
                message=f"Archivo ZIP inválido: {e}",
                severity="critical"
            ))

        return checks

    def _try_extract_zip_sample(self, zf, files):
        sample = files[:5]
        tmpdir = tempfile.mkdtemp(prefix="sello_")
        try:
            for info in sample:
                zf.extract(info, path=tmpdir)

            count = sum(1 for info in sample if os.path.exists(os.path.join(tmpdir, info.filename)))
            return Check(
                name="zip_extract_test",
                description="Test de extracción (muestra)",
                passed=count == len(sample),
                message=f"{count}/{len(sample)} archivos extraídos correctamente",
                severity="critical"
            )
        except Exception as e:
            return Check(
                name="zip_extract_test",
                description="Test de extracción (muestra)",
                passed=False,
                message=f"Error extrayendo: {e}",
                severity="critical"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── Directory verification ──

    def _verify_directory(self, path):
        checks = []
        file_count = 0
        dir_count = 0
        total_size = 0
        errors = []

        for dirpath, dirnames, filenames in os.walk(path):
            dir_count += len(dirnames)
            for fname in filenames:
                file_count += 1
                fpath = os.path.join(dirpath, fname)
                try:
                    total_size += os.path.getsize(fpath)
                    # Try reading first 1KB
                    with open(fpath, "rb") as f:
                        f.read(1024)
                except Exception as e:
                    errors.append(f"{fpath}: {e}")

        checks.append(Check(
            name="dir_scan",
            description="Escaneo del directorio de backup",
            passed=file_count > 0,
            message=f"{file_count} archivos, {dir_count} subdirectorios, {total_size/(1024*1024):.2f} MB",
            severity="critical",
            details={"file_count": file_count, "dir_count": dir_count, "total_size_mb": round(total_size/(1024*1024), 2)}
        ))

        if errors:
            checks.append(Check(
                name="dir_readability",
                description="Legibilidad de archivos",
                passed=False,
                message=f"{len(errors)} archivos no legibles",
                severity="warning",
                details={"errors": errors[:10]}
            ))
        else:
            checks.append(Check(
                name="dir_readability",
                description="Legibilidad de archivos",
                passed=True,
                message="Todos los archivos son legibles",
                severity="info"
            ))

        return checks

    # ── Restic verification ──

    def _verify_restic(self, path):
        checks = []

        # Check if restic is installed
        restic_bin = shutil.which("restic")
        if not restic_bin:
            checks.append(Check(
                name="restic_available",
                description="restic está instalado",
                passed=False,
                message="restic no encontrado en PATH. Instálalo: apt install restic",
                severity="critical"
            ))
            return checks

        # Run restic check
        try:
            result = subprocess.run(
                ["restic", "-r", path, "check", "--no-lock"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, "RESTIC_PASSWORD": os.environ.get("RESTIC_PASSWORD", "")}
            )

            if result.returncode == 0:
                checks.append(Check(
                    name="restic_check",
                    description="restic check (integridad del repositorio)",
                    passed=True,
                    message="Repositorio restic íntegro",
                    severity="critical"
                ))
            else:
                checks.append(Check(
                    name="restic_check",
                    description="restic check (integridad del repositorio)",
                    passed=False,
                    message=f"Errores detectados: {result.stderr.strip()[:200]}",
                    severity="critical"
                ))
        except subprocess.TimeoutExpired:
            checks.append(Check(
                name="restic_check",
                description="restic check",
                passed=False,
                message="Timeout: la verificación tardó más de 5 minutos",
                severity="warning"
            ))
        except Exception as e:
            checks.append(Check(
                name="restic_check",
                description="restic check",
                passed=False,
                message=f"Error ejecutando restic: {e}",
                severity="critical"
            ))

        # List snapshots
        try:
            result = subprocess.run(
                ["restic", "-r", path, "snapshots", "--json", "--no-lock"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "RESTIC_PASSWORD": os.environ.get("RESTIC_PASSWORD", "")}
            )

            if result.returncode == 0:
                snapshots = json.loads(result.stdout)
                checks.append(Check(
                    name="restic_snapshots",
                    description="Snapshots disponibles",
                    passed=len(snapshots) > 0,
                    message=f"{len(snapshots)} snapshots encontrados",
                    severity="critical",
                    details={"snapshot_count": len(snapshots)}
                ))
        except Exception:
            pass

        return checks

    # ── Borg verification ──

    def _verify_borg(self, path):
        checks = []

        borg_bin = shutil.which("borg")
        if not borg_bin:
            checks.append(Check(
                name="borg_available",
                description="borg está instalado",
                passed=False,
                message="borg no encontrado en PATH. Instálalo: apt install borgbackup",
                severity="critical"
            ))
            return checks

        try:
            result = subprocess.run(
                ["borg", "check", path],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, "BORG_PASSPHRASE": os.environ.get("BORG_PASSPHRASE", "")}
            )

            checks.append(Check(
                name="borg_check",
                description="borg check (integridad del repositorio)",
                passed=result.returncode == 0,
                message="Repositorio borg íntegro" if result.returncode == 0
                        else f"Errores: {result.stderr.strip()[:200]}",
                severity="critical"
            ))
        except subprocess.TimeoutExpired:
            checks.append(Check(
                name="borg_check",
                description="borg check",
                passed=False,
                message="Timeout: la verificación tardó más de 5 minutos",
                severity="warning"
            ))

        return checks

    def _build_result(self, path, backup_type, checks, start_time):
        elapsed = time.time() - start_time
        passed = all(c.passed for c in checks if c.severity == "critical")

        return VerificationResult(
            backup_path=path,
            backup_type=backup_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(elapsed, 2),
            passed=passed,
            checks=checks,
            certificate_path=None
        )
