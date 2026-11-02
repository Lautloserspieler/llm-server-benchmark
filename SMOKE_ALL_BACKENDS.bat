@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\smoke_all_backends.py %*
) else (
  python scripts\smoke_all_backends.py %*
)
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
