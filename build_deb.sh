#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_deb.sh — Empacota o Screen Recorder como .deb instalável
#
# Uso:
#   chmod +x build_deb.sh
#   ./build_deb.sh
#
# Resultado: screen-recorder_1.0.0_amd64.deb na pasta atual
# Instalar:  sudo dpkg -i screen-recorder_1.0.0_amd64.deb
# Remover:   sudo dpkg -r screen-recorder
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── Configuração ──────────────────────────────────────────────────────────────
APP_NAME="screen-recorder"
APP_VERSION="1.0.0"
APP_ARCH="amd64"
INSTALL_DIR="/opt/screen-recorder"
DESKTOP_DIR="/usr/share/applications"
ICON_DIR="/usr/share/icons/hicolor/256x256/apps"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="${SCRIPT_DIR}/deb_build/${APP_NAME}_${APP_VERSION}_${APP_ARCH}"
DEB_OUT="${SCRIPT_DIR}/${APP_NAME}_${APP_VERSION}_${APP_ARCH}.deb"

# ── Verificações ──────────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || { echo "❌  python3 não encontrado"; exit 1; }
command -v dpkg-deb >/dev/null 2>&1 || { echo "❌  dpkg-deb não encontrado. Instale: sudo apt install dpkg"; exit 1; }

if [ ! -f "${SCRIPT_DIR}/app.pyw" ]; then
    echo "❌  app.pyw não encontrado em ${SCRIPT_DIR}"; exit 1
fi

if [ ! -f "${SCRIPT_DIR}/record.ico" ]; then
    echo "⚠️   record.ico não encontrado — o app funcionará sem ícone personalizado"
    HAS_ICON=false
else
    HAS_ICON=true
fi

# ── Limpa build anterior ──────────────────────────────────────────────────────
rm -rf "${SCRIPT_DIR}/deb_build"
mkdir -p "${PKG_DIR}"

# ── Estrutura de diretórios ───────────────────────────────────────────────────
mkdir -p "${PKG_DIR}/DEBIAN"
mkdir -p "${PKG_DIR}${INSTALL_DIR}"
mkdir -p "${PKG_DIR}${DESKTOP_DIR}"
mkdir -p "${PKG_DIR}${ICON_DIR}"
mkdir -p "${PKG_DIR}/usr/bin"

# ── Copia arquivos do app ─────────────────────────────────────────────────────
cp "${SCRIPT_DIR}/app.pyw" "${PKG_DIR}${INSTALL_DIR}/app.pyw"

if [ "$HAS_ICON" = true ]; then
    cp "${SCRIPT_DIR}/record.ico" "${PKG_DIR}${INSTALL_DIR}/record.ico"

    # Converte .ico → .png 256x256 para o sistema de ícones
    if command -v convert >/dev/null 2>&1; then
        convert -background none "${SCRIPT_DIR}/record.ico[0]" \
            -resize 256x256 "${PKG_DIR}${ICON_DIR}/${APP_NAME}.png" 2>/dev/null || true
    elif command -v ffmpeg >/dev/null 2>&1; then
        ffmpeg -i "${SCRIPT_DIR}/record.ico" \
            -vf "scale=256:256" \
            "${PKG_DIR}${ICON_DIR}/${APP_NAME}.png" -y 2>/dev/null || true
    fi
fi

# ── Launcher wrapper ──────────────────────────────────────────────────────────
cat > "${PKG_DIR}/usr/bin/screen-recorder" << 'EOF'
#!/usr/bin/env bash
exec python3 /opt/screen-recorder/app.pyw "$@"
EOF
chmod 755 "${PKG_DIR}/usr/bin/screen-recorder"

# ── .desktop entry ────────────────────────────────────────────────────────────
ICON_ENTRY="${APP_NAME}"
[ "$HAS_ICON" = false ] && ICON_ENTRY="video-display"

cat > "${PKG_DIR}${DESKTOP_DIR}/screen-recorder.desktop" << EOF
[Desktop Entry]
Version=2.0
Type=Application
Name=Screen Recorder
GenericName=Screen Recorder
Comment=Record your screen with audio
Exec=screen-recorder
Icon=${ICON_ENTRY}
Terminal=false
Categories=AudioVideo;Video;Recorder;
Keywords=screen;record;capture;video;
StartupNotify=false
EOF

# ── DEBIAN/control ────────────────────────────────────────────────────────────
INSTALLED_SIZE=$(du -sk "${PKG_DIR}" | cut -f1)

cat > "${PKG_DIR}/DEBIAN/control" << EOF
Package: ${APP_NAME}
Version: ${APP_VERSION}
Architecture: ${APP_ARCH}
Maintainer: Gui guigomes23x@gmail.com
Installed-Size: ${INSTALLED_SIZE}
Depends: python3 (>= 3.10), python3-pyside6 | python3-pip, ffmpeg, pulseaudio-utils
Section: video
Priority: optional
Homepage: https://github.com/guilherme23x/Screen-Recorder
Description: Screen Recorder
 Minimal screen recorder built with PySide6 and FFmpeg.
 Supports audio capture via PulseAudio, multiple quality
 presets, and output formats (mp4, mkv, webm).
EOF

# ── DEBIAN/postinst — instala PySide6 via pip se não tiver ───────────────────
cat > "${PKG_DIR}/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e
python3 -c "import PySide6" 2>/dev/null || \
    pip3 install --break-system-packages PySide6 --quiet || \
    pip3 install PySide6 --quiet || true

# Atualiza cache de ícones
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi

# Atualiza banco de .desktop
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

exit 0
EOF
chmod 755 "${PKG_DIR}/DEBIAN/postinst"

# ── DEBIAN/postrm — limpeza ao desinstalar ────────────────────────────────────
cat > "${PKG_DIR}/DEBIAN/postrm" << 'EOF'
#!/bin/bash
set -e
case "$1" in
    purge|remove)
        rm -rf /opt/screen-recorder
        ;;
esac
exit 0
EOF
chmod 755 "${PKG_DIR}/DEBIAN/postrm"

# ── Permissões ────────────────────────────────────────────────────────────────
chmod 755 "${PKG_DIR}${INSTALL_DIR}/app.pyw"
find "${PKG_DIR}" -type d -exec chmod 755 {} \;
find "${PKG_DIR}" -type f ! -name "postinst" ! -name "postrm" \
    ! -name "screen-recorder" -exec chmod 644 {} \;
chmod 755 "${PKG_DIR}/usr/bin/screen-recorder"

# ── Build .deb ────────────────────────────────────────────────────────────────
echo ""
echo "📦  Gerando pacote .deb..."
dpkg-deb --build --root-owner-group "${PKG_DIR}" "${DEB_OUT}"

echo ""
echo "✅  Pacote gerado: ${DEB_OUT}"
echo ""
echo "Para instalar:"
echo "  sudo dpkg -i ${DEB_OUT}"
echo "  sudo apt-get install -f   # corrige dependências se necessário"
echo ""
echo "Para remover:"
echo "  sudo dpkg -r screen-recorder"
echo ""

# Limpa pasta temporária
rm -rf "${SCRIPT_DIR}/deb_build"
