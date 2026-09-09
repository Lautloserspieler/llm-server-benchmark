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
    if /I "%MODE%"=="docker" (
        echo [!] Docker-Modus wurde erzwungen und konnte nicht eingerichtet werden.
        goto :fail
    )
    echo [!] Docker Desktop GPU-Runtime ist nicht bereit. Auto-Modus verwendet Native als Fallback.
    echo.
)

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

echo.
echo ====================================================
echo   V2 Standard-Suite pruefen
echo ====================================================
python -m llmbench download --suite all --models-dir models --verify-only >nul 2>&1
if !errorlevel! neq 0 (
    echo [+] Mindestens ein Standard-Modell fehlt oder ist unvollstaendig.
    echo [+] Fehlende Dateien werden automatisch von HuggingFace geladen.
    echo [+] Bereits vorhandene Modelle und Cache-Dateien bleiben erhalten.
    echo.
    python -m llmbench download --suite all --models-dir models
    if !errorlevel! neq 0 goto :fail
) else (
    echo [+] Alle Standard-Modelle sind vollstaendig vorhanden.
)

python -m llmbench download --suite all --models-dir models --verify-only
if !errorlevel! neq 0 (
    echo [!] Die Standard-Suite ist nach dem Download weiterhin unvollstaendig.
    goto :fail
)

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

:fail
echo.
echo [!] Die Installation/Einrichtung ist fehlgeschlagen. Bitte die Ausgabe oben pruefen.
pause
exit /b 1
