@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark

rem Die eigentliche Einrichtung (Sprachwahl, Docker Desktop/WSL2, Python,
rem Modelle) liegt in scripts\SETUP.ps1 - dort laufen alle Texte ueber das
rem Sprachsystem. LLMBENCH_EXECUTION_MODE (auto/docker/native) und
rem LLMBENCH_AUTO_INSTALL (1/0) werden dort ausgewertet.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\SETUP.ps1"
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
