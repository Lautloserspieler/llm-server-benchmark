@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python-Umgebung fehlt; erstelle .venv ...
  python -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -c "from pydantic import field_validator; import yaml, httpx, rich, psutil, huggingface_hub" >nul 2>&1
if errorlevel 1 (
  echo Installiere Projektabhaengigkeiten in .venv ...
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" scripts\smoke_all_backends.py %*
set RC=%ERRORLEVEL%
goto :done
:failed
set RC=1
:done
echo.
pause
exit /b %RC%
