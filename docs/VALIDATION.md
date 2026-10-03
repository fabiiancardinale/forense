# Verificación del cambio

Entorno local: Linux, Python 3.12. Verificación del 3 de octubre de 2026.

- Suite completa, con C2PA 0.38.0, HEIC 1.8.0, pyHanko 0.37.0 y RapidOCR 1.4.4 instalados: **82 passed in 287.58s**.
- Se agregaron luego dos casos: conflicto de idempotencia/cuotas y cambio textual en un PDF incremental. Suite de endurecimiento final: **16 passed in 10.31s** (14 de esos casos ya estaban en los 82 anteriores). Total de casos distintos comprobados: **84**.
- Comprobación adicional del rechazo CSRF con caracteres Unicode: **1 passed in 0.48s**.
- `git diff --check`: sin errores.
- PDF de una página procesado con extracción textual y el validador pyHanko instalado: cobertura 1/1; resultado no concluyente sin referencia de autenticidad.

Estas pruebas verifican comportamiento del software con datos sintéticos y regresiones. Las respuestas de servicios de IA y los errores de C2PA se simulan en pruebas específicas; no se realizó una consulta facturable a Sightengine ni se validó un corpus de fotografías reales del negocio. Tampoco se ensayó una firma C2PA confiable completa, una PKI productiva ni infraestructura pública. La matriz de CI agrega Linux/Windows y un trabajo Linux con motores opcionales; su resultado remoto debe consultarse en el PR.
