@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark

rem Sprachwahl, LLMBENCH_EXECUTION_MODE (auto/docker/native) sowie Docker- und
rem nativer Lauf werden in scripts\START_BENCHMARK.ps1 ausgewertet - dort laufen
rem alle Texte ueber das Sprachsystem.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
