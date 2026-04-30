@echo off
setlocal

set "RASPBERRY_HOST=192.168.0.133"
set "RASPBERRY_USER=raspberry"

echo Poniendo Pie de Horno en reposo falso...
ssh %RASPBERRY_USER%@%RASPBERRY_HOST% /home/raspberry/.local/bin/pie-sleep

echo.
pause
