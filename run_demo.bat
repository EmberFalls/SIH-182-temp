@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
) else (
  python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
)
