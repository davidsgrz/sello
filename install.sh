#!/bin/bash
# SELLO — Installer
# Usage: curl -sSL https://raw.githubusercontent.com/tu-usuario/sello/main/install.sh | bash

set -e

INSTALL_DIR="/opt/sello"
BIN_LINK="/usr/local/bin/sello"

echo ""
echo "🔒 SELLO — Backup Verification & Certification"
echo "   Instalador v0.1.0"
echo ""

# Check Python 3.8+
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 no encontrado. Instálalo primero:"
    echo "   sudo apt install python3"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✔ Python $PY_VERSION detectado"

# Install
echo "→ Instalando en $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r . "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/sello.py"

# Create symlink
echo "→ Creando enlace simbólico: $BIN_LINK"
sudo ln -sf "$INSTALL_DIR/sello.py" "$BIN_LINK"

# Create config directory
mkdir -p ~/.sello/certificates
echo "→ Directorio de configuración: ~/.sello/"

echo ""
echo "✅ SELLO instalado correctamente!"
echo ""
echo "Uso:"
echo "  sello verify /ruta/a/tu/backup.tar.gz"
echo "  sello verify-db /ruta/a/dump.sql --engine mysql"
echo "  sello report"
echo ""
echo "Más info: sello --help"
