# Sube el código de Evidex (lo que está en main) al servidor e instala o actualiza.
#   powershell -ExecutionPolicy Bypass -File deploy\subir_al_servidor.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\subir_al_servidor.ps1 -Servidor root@179.236.75.148 -Dominio evidex.sudominio.cl
param(
    [string]$Servidor = "root@179.236.75.148",
    [string]$Dominio = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$tar = Join-Path $env:TEMP "evidex.tar.gz"
Write-Host "Empaquetando el código (rama actual, sin casos ni modelo)..."
git archive -o $tar HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive falló" }
Write-Host "Subiendo a $Servidor..."
scp $tar "${Servidor}:/root/evidex.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "scp falló" }
$dom = if ($Dominio) { "DOMINIO=$Dominio " } else { "" }
ssh $Servidor "rm -rf /root/evidex_codigo && mkdir -p /root/evidex_codigo && tar xzf /root/evidex.tar.gz -C /root/evidex_codigo && ${dom}bash /root/evidex_codigo/deploy/instalar.sh"
