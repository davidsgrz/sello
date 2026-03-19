#!/bin/bash
# ═══════════════════════════════════════════════════
#  SELLO Pro — Despliegue automático en VPS
# ═══════════════════════════════════════════════════
#
#  Uso:
#    1. Contrata un VPS en Hetzner (CX22, Ubuntu 24.04)
#    2. Apunta tu dominio al IP del VPS (registro A)
#    3. SSH al servidor: ssh root@tu-ip
#    4. Ejecuta este script:
#       curl -sSL https://raw.githubusercontent.com/tu-usuario/sello/main/deploy.sh | bash -s -- tu-dominio.com tu@email.com
#
#    O clona y ejecuta:
#       git clone https://github.com/tu-usuario/sello.git
#       cd sello
#       bash deploy.sh tu-dominio.com tu@email.com
#
# ═══════════════════════════════════════════════════

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo ""
    echo "🔒 SELLO Pro — Deploy Script"
    echo ""
    echo "Uso: bash deploy.sh <dominio> <email>"
    echo ""
    echo "Ejemplo:"
    echo "  bash deploy.sh getsello.com admin@getsello.com"
    echo ""
    exit 1
fi

echo ""
echo "🔒 SELLO Pro — Desplegando..."
echo "   Dominio: $DOMAIN"
echo "   Email:   $EMAIL"
echo ""

# ── 1. Actualizar sistema ──
echo "→ [1/8] Actualizando sistema..."
apt update -qq && apt upgrade -y -qq
apt install -y -qq curl git nginx certbot python3-certbot-nginx docker.io docker-compose-v2 ufw > /dev/null 2>&1

# ── 2. Firewall ──
echo "→ [2/8] Configurando firewall..."
ufw --force reset > /dev/null 2>&1
ufw default deny incoming > /dev/null 2>&1
ufw default allow outgoing > /dev/null 2>&1
ufw allow ssh > /dev/null 2>&1
ufw allow http > /dev/null 2>&1
ufw allow https > /dev/null 2>&1
ufw --force enable > /dev/null 2>&1

# ── 3. Crear directorio del proyecto ──
echo "→ [3/8] Preparando proyecto..."
SELLO_DIR="/opt/sello"
mkdir -p "$SELLO_DIR"

# Si estamos dentro del repo clonado, copiar; si no, clonar
if [ -f "./server/app.py" ]; then
    cp -r ./* "$SELLO_DIR/"
else
    echo "   Clonando repositorio..."
    git clone https://github.com/tu-usuario/sello.git "$SELLO_DIR" 2>/dev/null || true
fi

cd "$SELLO_DIR"

# ── 4. Crear directorios de datos ──
echo "→ [4/8] Creando directorios de datos..."
mkdir -p /var/lib/sello
mkdir -p /var/log/sello

# ── 5. Docker Compose (producción) ──
echo "→ [5/8] Configurando Docker..."

cat > "$SELLO_DIR/docker-compose.prod.yml" << 'COMPOSE'
services:
  sello-api:
    build:
      context: .
      dockerfile: server/Dockerfile
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - /var/lib/sello:/data
    environment:
      - SELLO_DB_PATH=/data/sello.db
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
COMPOSE

# Build and start
docker compose -f docker-compose.prod.yml up -d --build

echo "   Esperando a que la API arranque..."
sleep 5

# Verify API is running
if curl -s http://127.0.0.1:8000/health | grep -q "ok"; then
    echo "   ✔ API corriendo en :8000"
else
    echo "   ✘ Error: API no responde"
    docker compose -f docker-compose.prod.yml logs
    exit 1
fi

# ── 6. Nginx reverse proxy ──
echo "→ [6/8] Configurando Nginx..."

cat > "/etc/nginx/sites-available/$DOMAIN" << NGINX
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000;
    }

    # API docs
    location /docs {
        proxy_pass http://127.0.0.1:8000;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8000;
    }

    # Landing page / Dashboard (static files)
    location / {
        root /var/www/$DOMAIN;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
NGINX

ln -sf "/etc/nginx/sites-available/$DOMAIN" /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Create placeholder landing page
mkdir -p "/var/www/$DOMAIN"
cat > "/var/www/$DOMAIN/index.html" << 'LANDING'
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SELLO — Backup Verification</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #09090b; color: #e4e4e7; font-family: system-ui, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .container { text-align: center; max-width: 500px; padding: 40px; }
        h1 { font-size: 48px; margin-bottom: 16px; }
        .badge { display: inline-block; background: #22c55e; color: #000; padding: 4px 12px; font-size: 12px; font-weight: 700; margin-bottom: 24px; }
        p { color: #888; font-size: 16px; line-height: 1.6; margin-bottom: 24px; }
        .status { color: #22c55e; font-size: 14px; }
        code { background: #1a1a1e; padding: 8px 16px; font-family: monospace; font-size: 13px; color: #aaa; display: block; margin-top: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔒 SELLO</h1>
        <div class="badge">SERVIDOR ACTIVO</div>
        <p>Backup Verification & Certification Platform</p>
        <p class="status">✔ API operativa</p>
        <code>curl https://DOMAIN_PLACEHOLDER/health</code>
    </div>
</body>
</html>
LANDING

# Replace placeholder
sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "/var/www/$DOMAIN/index.html"

nginx -t && systemctl reload nginx

echo "   ✔ Nginx configurado"

# ── 7. SSL con Let's Encrypt ──
echo "→ [7/8] Configurando SSL (Let's Encrypt)..."
certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect 2>/dev/null || {
    echo "   ⚠ SSL pendiente — asegúrate de que el dominio apunta a este servidor"
    echo "   Ejecuta manualmente: certbot --nginx -d $DOMAIN -d www.$DOMAIN"
}

# Auto-renewal cron
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | sort -u | crontab -

# ── 8. Crear primera API key ──
echo "→ [8/8] Creando API key de administración..."

API_RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/api/keys \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"admin\", \"server_name\": \"$(hostname)\"}")

API_KEY=$(echo "$API_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('api_key', 'ERROR'))" 2>/dev/null || echo "ERROR")

# ── Done ──
echo ""
echo "═══════════════════════════════════════════════════"
echo "  🔒 SELLO Pro — Desplegado correctamente"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  URL:        https://$DOMAIN"
echo "  API:        https://$DOMAIN/api/"
echo "  API Docs:   https://$DOMAIN/docs"
echo "  Health:     https://$DOMAIN/health"
echo ""
echo "  API Key:    $API_KEY"
echo "  (Guárdala — no se mostrará de nuevo)"
echo ""
echo "  Para conectar un servidor:"
echo "    sello-agent setup --server https://$DOMAIN --key $API_KEY"
echo ""
echo "  Datos en:   /var/lib/sello/sello.db"
echo "  Logs:       docker compose -f /opt/sello/docker-compose.prod.yml logs -f"
echo ""
echo "  Comandos útiles:"
echo "    docker compose -f /opt/sello/docker-compose.prod.yml logs -f"
echo "    docker compose -f /opt/sello/docker-compose.prod.yml restart"
echo "    docker compose -f /opt/sello/docker-compose.prod.yml down"
echo ""
echo "═══════════════════════════════════════════════════"

# Save credentials
CREDS_FILE="/root/.sello-credentials"
cat > "$CREDS_FILE" << CREDS
# SELLO Pro Credentials — $(date)
DOMAIN=$DOMAIN
API_URL=https://$DOMAIN
API_KEY=$API_KEY
DB_PATH=/var/lib/sello/sello.db
CREDS

chmod 600 "$CREDS_FILE"
echo "  Credenciales guardadas en: $CREDS_FILE"
echo ""
