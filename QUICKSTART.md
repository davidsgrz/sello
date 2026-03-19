# ═══════════════════════════════════════════════
#  🔒 SELLO — Guía de Lanzamiento Rápido
#  Todo lo que necesitas para ir de 0 a producción
# ═══════════════════════════════════════════════


## Paso 1: Comprar dominio (5 minutos)

Ve a https://porkbun.com o https://namecheap.com
Busca un dominio disponible. Sugerencias:
  - getsello.com
  - sello.dev
  - usesello.com
  - sellobackup.com

Coste: ~10€/año


## Paso 2: Contratar VPS en Hetzner (10 minutos)

1. Ve a https://www.hetzner.com/cloud
2. Regístrate (necesitas tarjeta o PayPal)
3. Crea un nuevo proyecto "SELLO"
4. Crea un servidor:
   - Ubicación: Falkenstein o Nuremberg (Alemania) — más cerca de España
   - Imagen: Ubuntu 24.04
   - Tipo: CX22 (2 vCPU, 4GB RAM, 40GB NVMe) — €3.79/mes
   - SSH Key: añade tu clave pública (~/.ssh/id_rsa.pub)
   - Nombre: sello-prod
5. Anota la IP pública que te asignan

Coste: 3.79€/mes


## Paso 3: Apuntar dominio al VPS (5 minutos)

En el panel DNS de tu proveedor de dominio:
  - Registro A: @ → [IP de tu VPS]
  - Registro A: www → [IP de tu VPS]
  - (Opcional) Registro AAAA si tienes IPv6

Espera 5-15 minutos a que propague.
Comprueba: ping tudominio.com


## Paso 4: Desplegar SELLO (5 minutos)

Conéctate al servidor:
  ssh root@[IP-de-tu-VPS]

Clona el repo y ejecuta el deploy:
  git clone https://github.com/tu-usuario/sello.git
  cd sello
  bash deploy.sh tudominio.com tu@email.com

El script hace TODO automáticamente:
  - Instala Docker, Nginx, Certbot
  - Configura firewall (SSH + HTTP + HTTPS)
  - Despliega la API con Docker
  - Configura Nginx como reverse proxy
  - Obtiene certificado SSL de Let's Encrypt
  - Crea tu primera API key

Al terminar verás:
  URL:      https://tudominio.com
  API Key:  sello_xxxxxxxxxxxxx

GUARDA LA API KEY.


## Paso 5: Subir a GitHub (10 minutos)

Desde tu ordenador local:

  # Crear repo en GitHub (puede ser privado)
  # Ve a https://github.com/new → nombre: sello

  cd sello
  git init
  git add .
  git commit -m "SELLO v0.2.0 - Initial release"
  git remote add origin https://github.com/tu-usuario/sello.git
  git push -u origin main


## Paso 6: Probar que todo funciona

Desde tu ordenador:

  # Test 1: Health check
  curl https://tudominio.com/health
  # Debería responder: {"status":"ok","version":"0.2.0"}

  # Test 2: Verificar un backup localmente
  python3 sello.py verify /ruta/a/un/backup.tar.gz

  # Test 3: Conectar el agente remoto
  python3 agent/sello-agent.py setup \
    --server https://tudominio.com \
    --key sello_xxxxxxxxxxxxx

  # Test 4: Ver API docs
  # Abre en navegador: https://tudominio.com/docs


## Paso 7: Conectar tu primer servidor real

En el servidor que quieras monitorizar (ej: uno de Andamur):

  # 1. Copia el agente
  scp -r agent/ src/ root@servidor-destino:/opt/sello-agent/

  # 2. Conéctate al servidor
  ssh root@servidor-destino

  # 3. Configura el agente
  cd /opt/sello-agent
  python3 sello-agent.py setup --server https://tudominio.com --key sello_xxxxx

  # 4. Edita la config para añadir tus backups
  nano ~/.sello/agent.json

  # Ejemplo de config:
  # {
  #   "server_url": "https://tudominio.com",
  #   "api_key": "sello_xxxxx",
  #   "backups": [
  #     {
  #       "name": "mysql-diario",
  #       "path": "/backups/mysql/dump-*.sql.gz",
  #       "engine": "mysql",
  #       "enabled": true
  #     },
  #     {
  #       "name": "archivos-diario",
  #       "path": "/backups/daily-*.tar.gz",
  #       "type": "auto",
  #       "enabled": true
  #     }
  #   ]
  # }

  # 5. Prueba
  python3 sello-agent.py test
  python3 sello-agent.py run

  # 6. Añade a cron (verificar cada noche a las 4:00)
  crontab -e
  # Añade: 0 4 * * * cd /opt/sello-agent && python3 sello-agent.py run --once >> /var/log/sello-agent.log 2>&1


## Costes totales

  Dominio:  ~10€/año (~0.83€/mes)
  VPS:       3.79€/mes
  SSL:       0€ (Let's Encrypt)
  ─────────────────────────
  TOTAL:     4.62€/mes

  Con 1 cliente Pro (9€/mes) ya estás en beneficio.


## Estructura de archivos en el VPS

  /opt/sello/                 ← Código fuente
  /opt/sello/server/          ← API FastAPI
  /opt/sello/src/             ← Motor de verificación
  /opt/sello/agent/           ← Agente remoto
  /var/lib/sello/sello.db     ← Base de datos
  /var/www/tudominio.com/     ← Landing page estática
  /root/.sello-credentials    ← Credenciales (chmod 600)


## Comandos útiles del servidor

  # Ver logs en tiempo real
  docker compose -f /opt/sello/docker-compose.prod.yml logs -f

  # Reiniciar API
  docker compose -f /opt/sello/docker-compose.prod.yml restart

  # Ver estado
  docker compose -f /opt/sello/docker-compose.prod.yml ps

  # Backup de la base de datos (¡hazlo!)
  cp /var/lib/sello/sello.db /var/lib/sello/sello.db.bak

  # Actualizar código
  cd /opt/sello && git pull
  docker compose -f docker-compose.prod.yml up -d --build

  # Crear nueva API key para otro servidor
  curl -X POST https://tudominio.com/api/keys \
    -H "Content-Type: application/json" \
    -d '{"name": "nuevo-servidor", "server_name": "srv-02"}'

  # Ver estadísticas
  curl https://tudominio.com/api/stats

  # Renovar SSL (automático, pero por si acaso)
  certbot renew
