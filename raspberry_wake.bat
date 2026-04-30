@echo off
setlocal

set "RASPBERRY_HOST=192.168.0.133"
set "RASPBERRY_USER=raspberry"

echo Despertando Pie de Horno en modo kiosk...
ssh %RASPBERRY_USER%@%RASPBERRY_HOST% /home/raspberry/.local/bin/pie-wake

echo.
pause
