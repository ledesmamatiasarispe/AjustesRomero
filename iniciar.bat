@echo off
rem iniciar.bat -- arranca el servidor de Ajuste de Composicion (version sobre appbase) y abre la app en el
rem navegador. Lo usa el acceso directo "Ajuste de Composicion" de la carpeta de Inicio de Windows.
rem Puerto: 50506, el mismo de la version anterior (app/version.py), salvo que se cambie en Opciones.
rem Usa la ruta directa al Python311 del sistema (NO "python" del PATH): en esta PC el "python" del PATH puede
rem ser un .venv de otro proyecto sin las dependencias de esta app (requirements.txt).
cd /d "%~dp0"
start "Ajuste de Composicion - servidor" /min "C:\Users\LABOR01\AppData\Local\Programs\Python\Python311\python.exe" -u -m app
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:50506/"
