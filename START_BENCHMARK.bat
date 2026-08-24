@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark

:: Fuer die Erstinstallation von Visual C++ Build Tools bzw. CUDA Toolkit
:: werden Administratorrechte benoetigt. Falls sie fehlen, startet sich die
:: BAT einmal selbst mit UAC neu. Danach laeuft alles im selben Ablauf weiter.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Administratorrechte werden fuer das automatische Setup angefordert...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b 0
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Benchmark/Setup wurde mit Fehlercode %RC% beendet.
pause
exit /b %RC%
