@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark - Dependencies Update
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1" -SetupOnly -ForceUpdateLlamaCpp
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
