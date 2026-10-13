# Baja al PC el respaldo más reciente del servidor (copia fuera del VPS: si el servidor se pierde, los
# respaldos que están en él también).
#   powershell -ExecutionPolicy Bypass -File deploy\bajar_respaldo.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\bajar_respaldo.ps1 -Destino D:\respaldos_evidex
#
# OJO: el respaldo trae los casos completos, con datos personales de los asegurados (Ley 21.719).
# Guárdelo en un disco cifrado (BitLocker) o una carpeta con acceso restringido, nunca en GitHub, correo ni
# carpetas compartidas. Se guardan los últimos 8 en el PC; los más antiguos se borran.
param(
    [string]$Servidor = "root@179.236.75.148",
    [string]$Destino = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "respaldos_servidor"),
    [int]$Guardar = 8
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
Write-Host "Creando un respaldo nuevo en el servidor..."
ssh $Servidor "evidex-respaldo >/dev/null && ls -1t /var/backups/evidex/*.tar.gz | head -1" | Tee-Object -Variable ultimo | Out-Null
$ultimo = ($ultimo | Select-Object -Last 1).Trim()
if (-not $ultimo) { throw "No se encontró ningún respaldo en el servidor" }
$nombre = Split-Path $ultimo -Leaf
Write-Host "Bajando $nombre a $Destino ..."
scp "${Servidor}:$ultimo" (Join-Path $Destino $nombre)
if ($LASTEXITCODE -ne 0) { throw "scp falló" }
$remoto = (ssh $Servidor "sha256sum '$ultimo' | cut -d' ' -f1").Trim()
$local = (Get-FileHash -Algorithm SHA256 (Join-Path $Destino $nombre)).Hash.ToLower()
if ($remoto -ne $local) { throw "La copia no coincide con el original (sha256). Vuelva a intentarlo." }
Get-ChildItem $Destino -Filter "*.tar.gz" | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Guardar | Remove-Item
Write-Host "Listo: $nombre (verificado). Respaldos en el PC:" (Get-ChildItem $Destino -Filter "*.tar.gz").Count
