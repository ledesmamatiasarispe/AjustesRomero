@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"
set "APP=app.py"
set "PYTHON_EXE="
set "PYTHON_FLAGS="

:: 1. Python Launcher (py.exe) - disponible con Python 3.3+ en Windows
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_FLAGS=-3"
    goto :run
)

:: 2. python en PATH (verificar que sea Python 3)
python --version >nul 2>&1
if not errorlevel 1 (
    python --version 2>&1 | findstr /C:"Python 3" >nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        goto :run
    )
)

:: 3. python3 en PATH
python3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python3"
    goto :run
)

:: 4. Buscar en rutas de instalacion comunes
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_EXE=%%D\python.exe"
        goto :run
    )
)
for /d %%D in ("%ProgramFiles%\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_EXE=%%D\python.exe"
        goto :run
    )
)
for /d %%D in ("%ProgramFiles(x86)%\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_EXE=%%D\python.exe"
        goto :run
    )
)
for /d %%D in ("C:\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_EXE=%%D\python.exe"
        goto :run
    )
)

:: Python no encontrado
echo.
echo  [ERROR] No se encontro Python 3 instalado.
echo.
echo  Para instalar Python:
echo    1. Abre tu navegador y ve a: https://www.python.org/downloads/
echo    2. Descarga la version mas reciente de Python 3
echo    3. Durante la instalacion, marca la opcion "Add Python to PATH"
echo    4. Reinicia este launcher
echo.
pause
exit /b 1

:run
"%PYTHON_EXE%" %PYTHON_FLAGS% "%~dp0%APP%"
if errorlevel 1 (
    echo.
    echo  La aplicacion cerro con un error.
    pause
)
