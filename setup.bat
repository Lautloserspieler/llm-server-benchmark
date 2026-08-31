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

echo [+] Installiere/Aktualisiere llmbench...
call .venv\Scripts\activate
python -m pip install --upgrade pip
if !errorlevel! neq 0 goto :fail
python -m pip install -e "."
if !errorlevel! neq 0 goto :fail

echo.
echo [OK] Programm und Abhaengigkeiten sind bereit.

if not exist models mkdir models

dir /s /b "models\*.gguf" >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ====================================================
    echo   Keine Modelle gefunden - V2 Auto-Download
    echo ====================================================
    echo Die komplette Standard-Suite wird automatisch von HuggingFace geladen.
    echo Bereits vorhandene Cache-Dateien werden wiederverwendet.
    echo.
    python -m llmbench download --suite all --models-dir models
    if !errorlevel! neq 0 goto :fail

    dir /s /b "models\*.gguf" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [!] Der Download wurde beendet, aber es wurde keine GGUF-Datei gefunden.
        goto :fail
    )
) else (
    echo [+] Vorhandene GGUF-Modelle erkannt. Download wird uebersprungen.
)

echo.
echo Starte jetzt die automatische Konfiguration...
echo.

python -m llmbench setup
if !errorlevel! neq 0 goto :fail

echo.
echo ====================================================
echo   Einrichtung abgeschlossen.
echo   Der Benchmark kann jetzt direkt gestartet werden.
echo ====================================================
echo.
pause
exit /b 0

:fail
echo.
echo [!] Die Installation/Einrichtung ist fehlgeschlagen. Bitte die Ausgabe oben pruefen.
pause
exit /b 1
