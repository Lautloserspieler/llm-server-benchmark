@echo off
setlocal
cd /d "%~dp0"
title LLM Server Benchmark - Abhaengigkeiten aktualisieren
echo.
echo Hinweis: Dieses Update laedt llama.cpp neu herunter.
echo Fuer eine Vergleichsserie auf ALLEN Servern denselben Build verwenden.
echo Der verwendete Tag steht danach in tools\llama.cpp\.llama-build.json
echo und laesst sich ueber llama-cpp-version.txt festschreiben.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_BENCHMARK.ps1" -SetupOnly -ForceUpdateLlamaCpp %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
