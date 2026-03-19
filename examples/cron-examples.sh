# ============================================
# SELLO — Ejemplo de configuración con cron
# ============================================
#
# Añade estas líneas a tu crontab (crontab -e)
# para verificar tus backups automáticamente.
#
# Los certificados se guardan en ~/.sello/certificates/
# El historial se guarda en ~/.sello/history.json
#

# ── Verificar backup diario de archivos a las 4:00 AM ──
0 4 * * * /usr/local/bin/sello verify /backups/daily-$(date +\%Y\%m\%d).tar.gz --report json >> /var/log/sello.log 2>&1

# ── Verificar dump MySQL cada noche a las 3:30 AM ──
30 3 * * * /usr/local/bin/sello verify-db /backups/mysql/all-databases-$(date +\%Y\%m\%d).sql.gz --engine mysql --report json >> /var/log/sello.log 2>&1

# ── Verificar dump PostgreSQL los domingos a las 5:00 AM ──
0 5 * * 0 /usr/local/bin/sello verify-db /backups/postgres/full-dump.sql --engine postgres --report json >> /var/log/sello.log 2>&1

# ── Verificar repositorio restic cada día a las 6:00 AM ──
0 6 * * * RESTIC_PASSWORD_FILE=/etc/restic/password /usr/local/bin/sello verify /backups/restic-repo --type restic --report json >> /var/log/sello.log 2>&1

# ── Generar informe HTML semanal (lunes a las 8:00 AM) ──
0 8 * * 1 cd /var/reports && /usr/local/bin/sello verify /backups/weekly-$(date -d "last sunday" +\%Y\%m\%d).tar.gz --report html 2>&1

# ── NOTA: Para alertas por email cuando falle, añade: ──
# 0 4 * * * /usr/local/bin/sello verify /backups/daily.tar.gz --report json 2>&1 | python3 -c "
# import sys, json
# data = json.load(sys.stdin)
# if not data['passed']:
#     import subprocess
#     subprocess.run(['mail', '-s', 'SELLO: Backup FAILED', 'admin@tuempresa.com'],
#                    input=json.dumps(data, indent=2), text=True)
# "
