#!/usr/bin/env bash
# Instala o actualiza Evidex en un servidor Ubuntu (24.04 LTS o más nuevo). Reemplaza a los .bat de Windows.
#
#   sudo DOMINIO=evidex.sudominio.cl bash deploy/instalar.sh
#
# Se corre desde la carpeta del código ya descomprimida (ver deploy/LEEME.md). Se puede correr de nuevo para
# actualizar: copia el código nuevo, actualiza las librerías y reinicia, sin tocar los casos ni el modelo.
#
#   código      /opt/evidex/app        (se reemplaza en cada actualización)
#   casos       /var/lib/evidex/casos  (datos: NUNCA se borran ni se reemplazan aquí)
#   modelo IA   /var/lib/evidex/modelos
#   respaldos   /var/backups/evidex    (todos los días a las 03:15, se guardan 14)
#
# Sin DOMINIO se usa <ip-con-guiones>.sslip.io, que apunta a la IP del servidor y permite HTTPS sin comprar dominio.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Corra este script como root (sudo)."; exit 1; fi
ORIGEN="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -f "$ORIGEN/evidex/web/wsgi.py" ]; then echo "No encuentro el código de Evidex en $ORIGEN."; exit 1; fi

APP=/opt/evidex/app
VENV=/opt/evidex/venv
DATOS=/var/lib/evidex
RESPALDOS=/var/backups/evidex
CONF=/etc/evidex/evidex.env

IP="$(curl -4 -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
if [ -z "${DOMINIO:-}" ] && [ -f "$CONF" ]; then DOMINIO="$(sed -n 's/^EVIDEX_DOMINIO=//p' "$CONF")"; fi
DOMINIO="${DOMINIO:-${IP//./-}.sslip.io}"
echo "==> Evidex en https://$DOMINIO"

echo "==> Paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-dev build-essential git curl rsync ufw fail2ban \
  unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https gnupg libgl1 libglib2.0-0
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true   # parches de seguridad automáticos

echo "==> Usuario y carpetas"
id evidex >/dev/null 2>&1 || useradd --system --home /opt/evidex --shell /usr/sbin/nologin evidex
mkdir -p "$APP" "$DATOS/casos" "$DATOS/modelos" "$RESPALDOS" /etc/evidex
chown -R evidex:evidex "$DATOS"
chmod 750 "$DATOS" "$DATOS/casos"
chmod 700 "$RESPALDOS"

echo "==> Código"
rsync -a --delete --exclude '.git' --exclude 'casos' --exclude 'caso_sin' --exclude 'modelos' \
  --exclude '__pycache__' --exclude '*.bat' --exclude '*.exe' "$ORIGEN/" "$APP/"
chown -R root:evidex "$APP"
chmod -R o-rwx "$APP"

echo "==> Librerías de Python (la primera vez tarda varios minutos)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP/requirements.txt" gunicorn==26.2.0
while read -r extra; do
  case "$extra" in ''|-*|\#*) continue;; esac
  "$VENV/bin/pip" install -q "$extra" || echo "   Aviso: no se pudo instalar el extra $extra (Evidex funciona igual)"
done < "$APP/requirements-optional.txt"
"$VENV/bin/python" -m compileall -q "$APP/evidex" >/dev/null || true    # el código queda de solo lectura para Evidex

echo "==> Configuración"
if [ ! -f "$CONF" ]; then
  cat > "$CONF" <<EOF
# Configuración de Evidex en este servidor (después de cambiarla: systemctl restart evidex-web)
EVIDEX_DOMINIO=$DOMINIO
EVIDEX_DIR=$DATOS/casos
EVIDEX_MODELO=$DATOS/modelos
# Opcional: solo estas redes pueden entrar a Evidex (el portal del asegurado queda abierto). Ej: 200.1.2.0/24,190.5.6.7
EVIDEX_IPS_PERMITIDAS=
EOF
else
  sed -i "s/^EVIDEX_DOMINIO=.*/EVIDEX_DOMINIO=$DOMINIO/" "$CONF"
fi
chown root:evidex "$CONF"
chmod 640 "$CONF"

cat > /etc/systemd/system/evidex-web.service <<EOF
[Unit]
Description=Evidex (web)
After=network.target

[Service]
User=evidex
Group=evidex
EnvironmentFile=$CONF
WorkingDirectory=$APP
ExecStart=$VENV/bin/gunicorn --workers 1 --threads 8 --timeout 300 --no-control-socket --bind 127.0.0.1:8765 'evidex.web.wsgi:build()'
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$DATOS
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/evidex-worker.service <<EOF
[Unit]
Description=Evidex (análisis de archivos en segundo plano)
After=network.target

[Service]
User=evidex
Group=evidex
EnvironmentFile=$CONF
WorkingDirectory=$APP
ExecStart=$VENV/bin/python -m evidex.inspection.worker --dir $DATOS/casos
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$DATOS
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

cat > /usr/local/bin/evidex-respaldo <<EOF
#!/usr/bin/env bash
# Respaldo de los casos y del modelo. Se guardan los últimos 14. Copie de vez en cuando uno fuera del servidor.
set -euo pipefail
f="$RESPALDOS/evidex-\$(date +%Y%m%d-%H%M).tar.gz"
tar czf "\$f" -C "$DATOS" casos modelos
chmod 600 "\$f"
ls -1t "$RESPALDOS"/evidex-*.tar.gz | tail -n +15 | xargs -r rm -f
echo "Respaldo: \$f"
EOF
chmod 750 /usr/local/bin/evidex-respaldo

cat > /etc/systemd/system/evidex-respaldo.service <<EOF
[Unit]
Description=Respaldo de Evidex

[Service]
Type=oneshot
ExecStart=/usr/local/bin/evidex-respaldo
EOF
cat > /etc/systemd/system/evidex-respaldo.timer <<EOF
[Unit]
Description=Respaldo diario de Evidex

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "==> HTTPS (Caddy pide el certificado solo)"
cat > /etc/caddy/Caddyfile <<EOF
$DOMINIO {
	encode gzip
	request_body {
		max_size 30MB
	}
	reverse_proxy 127.0.0.1:8765
}
EOF

echo "==> Firewall: solo SSH, HTTP y HTTPS"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
systemctl enable --now fail2ban >/dev/null 2>&1 || true

systemctl daemon-reload
systemctl enable evidex-web evidex-worker evidex-respaldo.timer >/dev/null
systemctl restart evidex-web evidex-worker
systemctl start evidex-respaldo.timer
systemctl reload caddy || systemctl restart caddy

sleep 3
if systemctl is-active --quiet evidex-web; then echo "==> Evidex está corriendo."; else
  echo "==> Evidex no arrancó. Revise: journalctl -u evidex-web -n 50"; exit 1; fi

if [ ! -f "$DATOS/casos/usuarios.json" ]; then
  echo
  echo "Falta crear el administrador. Corra:"
  echo "  sudo -u evidex $VENV/bin/python -m evidex.accounts.setup --dir $DATOS/casos"
fi
[ -f "$DATOS/modelos/evidex_ia.onnx" ] || echo "Aviso: no hay modelo de IA en $DATOS/modelos (Evidex funciona sin él). Ver deploy/LEEME.md."
echo
echo "Listo: https://$DOMINIO"
