@echo off
setlocal enabledelayedexpansion

echo.
echo ====================================================
echo   LLM Server Benchmark - Quick Setup (Windows)
echo ====================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python wurde nicht gefunden.
    echo Bitte installiere Python 3.10+ oder nutze START_BENCHMARK.bat für eine automatische Installation.
    pause
    exit /b 1
)

:: Create Virtual Environment
if not exist .venv (
    echo [+] Erstelle virtuelle Umgebung (.venv)...
    python -m venv .venv
)

:: Activate and Install
echo [+] Installiere Abhängigkeiten...
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [V] Setup erfolgreich!
echo.
echo Starte jetzt den Setup-Wizard...
echo.

python -m llmbench setup

echo.
echo ====================================================
echo   Setup beendet. Du kannst jetzt starten mit:
echo   .venv\Scripts\python -m llmbench run
echo ====================================================
echo.
pause
