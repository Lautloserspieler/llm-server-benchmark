@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark

:: Der aktuelle Windows-Setup-Pfad installiert Python pro Benutzer und nutzt
:: offizielle llama.cpp-Release-Builds. Fuer einen normalen Benchmark-Start
:: werden daher keine Administratorrechte mehr benoetigt.
:: Falls spaeter ein separater Installer Adminrechte braucht, soll nur dieser
:: konkrete Schritt eine UAC-Abfrage ausloesen - nicht jeder Benchmark-Start.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Benchmark/Setup wurde mit Fehlercode %RC% beendet.
pause
exit /b %RC%
