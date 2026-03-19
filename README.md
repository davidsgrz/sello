# 🔒 SELLO — Backup Verification & Certification

**¿Tus backups funcionan? Demuéstralo.**

SELLO verifica automáticamente que tus backups son restaurables y genera certificados de prueba para auditorías, ciberseguros e ISO 27001.

## El problema

> "Todo el mundo hace backups. Casi nadie los prueba."

Cuando necesitas restaurar, descubres que el backup está corrupto, incompleto, o que nadie sabe cómo restaurarlo. SELLO automatiza la verificación.

## Qué hace

- **Verifica archivos**: tar.gz, zip, directorios, repositorios restic/borg
- **Verifica bases de datos**: dumps MySQL, PostgreSQL, archivos SQLite
- **Genera certificados**: JSON firmado con hash de integridad y timestamp
- **Mantiene historial**: audit trail de todas las verificaciones
- **Informes**: terminal (colores), JSON (integración CI/CD), HTML (compartir)

## Instalación

```bash
git clone https://github.com/tu-usuario/sello.git
cd sello
chmod +x sello.py
# Opcional: enlace simbólico
ln -s $(pwd)/sello.py /usr/local/bin/sello
```

No requiere dependencias externas — solo Python 3.8+.

## Uso rápido

```bash
# Verificar un backup tar.gz
python3 sello.py verify /backups/server1-2026-03-18.tar.gz

# Verificar un dump de MySQL
python3 sello.py verify-db /backups/mydb.sql --engine mysql

# Verificar un dump de PostgreSQL
python3 sello.py verify-db /backups/mydb.sql.gz --engine postgres

# Verificar una base de datos SQLite
python3 sello.py verify-db /backups/app.db --engine sqlite

# Verificar repositorio restic
RESTIC_PASSWORD=xxx python3 sello.py verify /backups/restic-repo --type restic

# Generar informe JSON (para CI/CD)
python3 sello.py verify /backups/backup.tar.gz --report json

# Generar informe HTML
python3 sello.py verify /backups/backup.tar.gz --report html

# Ver historial de verificaciones
python3 sello.py report --last 20
```

## Checks que realiza

### Backups de archivos
| Check | Descripción |
|-------|-------------|
| `exists` | El archivo/directorio existe |
| `readable` | Permisos de lectura OK |
| `size` | No está vacío |
| `freshness` | Antigüedad del backup |
| `integrity` | Archivo no corrupto (CRC/tar headers) |
| `extract_test` | Extracción de muestra exitosa |
| `checksum` | SHA-256 generado |

### Dumps de base de datos
| Check | Descripción |
|-------|-------------|
| `format` | Formato válido (MySQL/PG/SQLite) |
| `tables` | Tablas encontradas en el dump |
| `data` | Sentencias INSERT/COPY presentes |
| `complete` | Marcador de finalización presente |
| `integrity` | PRAGMA integrity_check (SQLite) |

## Certificados

Cuando un backup pasa la verificación, SELLO genera un certificado JSON en `~/.sello/certificates/`:

```json
{
  "sello_certificate": {
    "version": "0.1.0",
    "issued_at": "2026-03-18T14:30:00",
    "backup": {
      "path": "/backups/server1.tar.gz",
      "type": "tar",
      "verified_at": "2026-03-18T14:29:55"
    },
    "result": {
      "status": "VERIFIED",
      "checks_total": 7,
      "checks_passed": 7
    },
    "integrity_hash": "a1b2c3d4..."
  }
}
```

Estos certificados sirven como evidencia para:
- **Auditorías ISO 27001** (control A.12.3 - Backup)
- **Ciberseguros** (prueba de que los backups se verifican regularmente)
- **Compliance ENS** (medidas de protección de la información)

## Integración con cron

```bash
# Verificar backups cada noche a las 3:00
0 3 * * * /usr/local/bin/sello verify /backups/daily-$(date +\%Y\%m\%d).tar.gz --report json >> /var/log/sello.log 2>&1
```

## Roadmap

- [ ] Verificación de VMs (QCOW2, VMDK — arrancar en QEMU temporal)
- [ ] Plugin para Veeam / restic / borg con restore real
- [ ] Dashboard web con historial visual
- [ ] Alertas por email/Slack/Telegram
- [ ] Integración CI/CD (GitHub Actions, GitLab CI)
- [ ] Comparación de checksums entre verificaciones

## Licencia

MIT

---

*SELLO — Porque un backup sin verificar es solo una esperanza guardada en disco.*
