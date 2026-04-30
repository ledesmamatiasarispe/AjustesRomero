@echo off
setlocal

cd /d "C:\Users\LABOR01\Desktop\ajuste_comp"

set "SUBDOMAIN=phorno-k91m-ajc26-zeta84"

echo Iniciando ajuste_comp...
echo.
echo URL local: http://localhost:8765
echo URL publica: https://%SUBDOMAIN%.loca.lt
echo.
echo La app inicia el tunel publico automaticamente.
echo Los dispositivos nuevos se aprueban desde la pestana PIE DE HORNO.
echo.

start "" python app.py

echo.
pause
