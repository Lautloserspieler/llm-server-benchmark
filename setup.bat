@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ====================================================
echo   LLM Server Benchmark - Einrichtung (Windows)
echo ====================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python wurde nicht gefunden.
    echo Bitte Python 3.10+ installieren oder START_BENCHMARK.bat verwenden,
    echo das Python bei Bedarf projektlokal einrichtet.
    pause
    exit /b 1
)

if not exist .venv (
    echo [+] Erstelle virtuelle Umgebung ^(.venv^)...
    python -m venv .venv
    if !errorlevel! neq 0 goto :fail
)

echo [+] Installiere llmbench inklusive Web-Dashboard...
call .venv\Scripts\activate
python -m pip install --upgrade pip
if !errorlevel! neq 0 goto :fail
python -m pip install -e ".[web]"
if !errorlevel! neq 0 goto :fail

echo.
echo [OK] Installation abgeschlossen.
echo.
echo Starte jetzt die Einrichtung...
echo.

python -m llmbench setup

echo.
echo ====================================================
echo   Weiter mit:
echo   .venv\Scripts\llmbench doctor --config benchmark.yaml
echo   .venv\Scripts\llmbench run    --config benchmark.yaml
echo ====================================================
echo.
pause
exit /b 0

:fail
echo.
echo [!] Die Installation ist fehlgeschlagen. Bitte die Ausgabe oben pruefen.
pause
exit /b 1
