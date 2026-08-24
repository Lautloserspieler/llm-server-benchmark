@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Benchmark/Setup wurde mit Fehlercode %RC% beendet.
pause
exit /b %RC%
