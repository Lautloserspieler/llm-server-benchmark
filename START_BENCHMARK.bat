@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title LLM Server Benchmark


set "MODE=%LLMBENCH_EXECUTION_MODE%"
if "%MODE%"=="" set "MODE=auto"

rem Wenn im Setup eine Modellauswahl gespeichert wurde, pruefen/nachladen wir
rem spaeter nur diese Modelle statt wieder die komplette Standard-Suite.
if exist "models\.llmbench-model-selection.json" set "LLMBENCH_USE_SAVED_SELECTION=1"

if /I not "%MODE%"=="auto" if /I not "%MODE%"=="docker" if /I not "%MODE%"=="native" (
    echo LLMBENCH_EXECUTION_MODE muss auto, docker oder native sein.
    pause
    exit /b 1
)

if /I not "%MODE%"=="native" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DOCKER_BENCHMARK.ps1" -Action Check >nul 2>&1
    if !errorlevel! equ 0 (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DOCKER_BENCHMARK.ps1" -Action Run
        set RC=!ERRORLEVEL!
        goto :done
    )

    if /I "%MODE%"=="docker" (
        echo Docker-Modus ist erzwungen, aber noch nicht bereit. Richte ihn jetzt ein...
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DOCKER_BENCHMARK.ps1" -Action Setup
        if !errorlevel! neq 0 (
            set RC=!ERRORLEVEL!
            goto :done
        )
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\DOCKER_BENCHMARK.ps1" -Action Run
        set RC=!ERRORLEVEL!
        goto :done
    )
)

:: Nativer Windows-Fallback. Dieser Pfad bleibt fuer Systeme ohne Docker Desktop
:: bzw. ohne WSL2-GPU-Unterstuetzung voll funktionsfaehig.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1" %*
set RC=%ERRORLEVEL%

:done
echo.
if not "%RC%"=="0" echo Benchmark/Setup wurde mit Fehlercode %RC% beendet.
pause
exit /b %RC%
