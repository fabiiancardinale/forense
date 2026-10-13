# Evidex en un servidor (VPS Ubuntu)

Desde ahora Evidex corre en el servidor, no en el PC: los analistas entran por el navegador a `https://<dominio>` con su usuario y contraseña, y el asegurado abre el portal desde su celular con el enlace que le llega. Los `.bat` de Windows ya no se usan.

| Qué | Dónde |
|---|---|
| Código | `/opt/evidex/app` (se reemplaza en cada actualización) |
| Casos y usuarios | `/var/lib/evidex/casos` (no se tocan al actualizar) |
| Modelo de IA | `/var/lib/evidex/modelos` |
| Respaldos diarios (03:15, los últimos 14) | `/var/backups/evidex` |
| Configuración | `/etc/evidex/evidex.env` |

## Instalar o actualizar (desde el PC, en PowerShell)

En la carpeta `veritas`, con los cambios ya en `main`:

```powershell
git archive -o "$env:TEMP\evidex.tar.gz" HEAD
scp "$env:TEMP\evidex.tar.gz" root@179.236.75.148:/root/evidex.tar.gz
ssh root@179.236.75.148 "rm -rf /root/evidex_codigo && mkdir -p /root/evidex_codigo && tar xzf /root/evidex.tar.gz -C /root/evidex_codigo && bash /root/evidex_codigo/deploy/instalar.sh"
```

O todo junto: `powershell -ExecutionPolicy Bypass -File deploy\subir_al_servidor.ps1`.

`instalar.sh` instala Python, Caddy (HTTPS automático), el firewall (solo SSH, 80 y 443), fail2ban, los parches de seguridad automáticos, los servicios `evidex-web` y `evidex-worker` y el respaldo diario. Para actualizar, se corre lo mismo: cambia el código y reinicia, sin tocar los casos.

**Dominio:** sin dominio propio se usa `179-236-75-148.sslip.io`, que apunta a la IP y tiene HTTPS. Para usar uno propio, apunte un registro A del dominio a la IP del servidor y corra el instalador con `DOMINIO=evidex.sudominio.cl` delante de `bash` (por ejemplo `ssh root@... "DOMINIO=evidex.sudominio.cl bash /root/evidex_codigo/deploy/instalar.sh"`).

## La primera vez

1. Crear el administrador (en el servidor):

   ```bash
   evidex-admin
   ```

2. Subir el modelo de IA (desde el PC):

   ```powershell
   scp modelos\evidex_ia.* root@179.236.75.148:/var/lib/evidex/modelos/
   ssh root@179.236.75.148 "chown -R evidex:evidex /var/lib/evidex/modelos && systemctl restart evidex-web evidex-worker"
   ```

3. Abrir `https://<dominio>` e ingresar.

## Del día a día

```bash
systemctl status evidex-web            # ¿está corriendo?
journalctl -u evidex-web -n 100        # últimos mensajes (errores)
systemctl restart evidex-web evidex-worker
evidex-respaldo                        # respaldo en el momento
evidex-admin --reset                   # recuperar la contraseña de un administrador
```

### Respaldo fuera del servidor

Si el servidor se pierde, los respaldos que están en él también. Una vez por semana, desde el PC:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\bajar_respaldo.ps1
```

Crea un respaldo nuevo, lo baja a `forense\respaldos_servidor`, comprueba que la copia sea idéntica (sha256) y
deja los últimos 8. Trae datos personales: guárdelo en un disco cifrado (BitLocker), nunca en GitHub ni en el correo.

### Entrar al servidor con llave (y no con contraseña)

1. En el PC (PowerShell), cree su llave. Ponga una frase de paso cuando la pida; si ya tiene una, responda «n» a sobrescribir:

   ```powershell
   ssh-keygen -t ed25519
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@179.236.75.148 "cat >> ~/.ssh/authorized_keys"
   ```

2. Pruebe: `ssh root@179.236.75.148` debe entrar pidiendo la frase de la llave, no la contraseña de root.
3. Recién entonces se desactiva la contraseña en el servidor (`PasswordAuthentication no`). Si algún día pierde
   la llave, se entra por la consola web de Hostinger.

## Seguridad (antes de datos reales de BCI)

- **No suba casos reales** hasta que BCI apruebe el servidor: dónde está el datacenter, quién tiene acceso, respaldos y borrado (Ley 21.719). Los casos del PC no se copian solos.
- **SSH con llave y sin contraseña:** en el PC `ssh-keygen -t ed25519`, luego copie `C:\Users\<usted>\.ssh\id_ed25519.pub` al servidor en `/root/.ssh/authorized_keys`. Cuando entre sin contraseña, en `/etc/ssh/sshd_config` ponga `PasswordAuthentication no` y `systemctl restart ssh`.
- **Solo desde la oficina:** en `/etc/evidex/evidex.env`, `EVIDEX_IPS_PERMITIDAS=<IP de la oficina>` y `systemctl restart evidex-web`. El portal del asegurado sigue abierto a todos.
- Contraseñas de al menos 15 caracteres; tras 5 intentos fallidos la cuenta se bloquea 5 minutos.

## Probar en el PC (sin servidor)

```
python -m pip install -r requirements.txt
python -m evidex.accounts.setup --dir casos
python -m evidex.web --dir casos
```
