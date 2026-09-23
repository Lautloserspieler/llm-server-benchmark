@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"


set "MODE=%LLMBENCH_EXECUTION_MODE%"
if "%MODE%"=="" set "MODE=auto"

if /I not "%MODE%"=="auto" if /I not "%MODE%"=="docker" if /I not "%MODE%"=="native" (
    echo [!] LLMBENCH_EXECUTION_MODE muss auto, docker oder native sein.
    pause
    exit /b 1
)

echo.
echo ====================================================
echo   LLM Server Benchmark - Einrichtung (Windows)
echo ====================================================
echo Ausfuehrungsmodus: %MODE%
echo.

if /I not "%MODE%"=="native" (
    echo === Docker Desktop + WSL2 + NVIDIA CUDA ===
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DOCKER_BENCHMARK.ps1" -Action Setup
    if !errorlevel! equ 0 goto :docker_ok
    if !errorlevel! equ 3010 goto :reboot
    if /I "%MODE%"=="docker" (
        echo [!] Docker-Modus wurde erzwungen und konnte nicht eingerichtet werden.
        goto :fail
    )
    echo [!] Docker Desktop GPU-Runtime ist nicht bereit. Auto-Modus verwendet Native als Fallback.
    echo.
)

rem Python suchen; fehlt es, fragt ENSURE_PYTHON.ps1 nach und installiert es.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\ENSURE_PYTHON.ps1"
if !errorlevel! neq 0 goto :fail
set "PYTHON_EXE="
if exist ".runtime\python-path.txt" set /p PYTHON_EXE=<".runtime\python-path.txt"
if not defined PYTHON_EXE (
    echo [!] Python 3.10+ wurde nicht gefunden.
    goto :fail
)

if not exist .venv (
    echo [+] Erstelle virtuelle Umgebung ^(.venv^)...
    "!PYTHON_EXE!" -m venv .venv
    if !errorlevel! neq 0 goto :fail
)

echo [+] Installiere/Aktualisiere llmbench...
call .venv\Scripts\activate
python -m pip install --upgrade pip
if !errorlevel! neq 0 goto :fail
python -m pip install -e "."
if !errorlevel! neq 0 goto :fail

echo.
echo [OK] Programm und Abhaengigkeiten sind bereit.
if not exist models mkdir models

echo.
echo ====================================================
echo   Modelle fuer den Benchmark auswaehlen
echo ====================================================
python -m llmbench.model_select --models-dir models --select
if !errorlevel! neq 0 goto :fail

rem Der anschliessende Setup-Wizard darf nur die gespeicherte Auswahl pruefen
rem und niemals stillschweigend die komplette Standard-Suite nachladen.
set "LLMBENCH_USE_SAVED_SELECTION=1"

echo.
echo Starte jetzt die automatische Konfiguration...
echo.
python -m llmbench setup
if !errorlevel! neq 0 goto :fail

echo.
echo ====================================================
echo   Einrichtung abgeschlossen (Native).
echo   Der Benchmark kann jetzt direkt gestartet werden.
echo ====================================================
echo.
pause
exit /b 0

:docker_ok
echo.
echo ====================================================
echo   Einrichtung abgeschlossen (Docker + CUDA).
echo   Der Benchmark kann jetzt direkt gestartet werden.
echo ====================================================
echo.
pause
exit /b 0

:reboot
echo.
echo ====================================================
echo   Neustart erforderlich.
echo   Bitte Windows neu starten und danach setup.bat
echo   erneut ausfuehren - die Einrichtung macht dann weiter.
echo ====================================================
echo.
pause
exit /b 3010

:fail
echo.
echo [!] Die Installation/Einrichtung ist fehlgeschlagen. Bitte die Ausgabe oben pruefen.
pause
exit /b 1
