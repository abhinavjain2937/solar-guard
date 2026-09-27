@echo off
setlocal
cd /d "%~dp0"

curl.exe --silent --fail http://127.0.0.1:8000/health >nul 2>nul
if errorlevel 1 goto :start_backend
curl.exe --silent --fail http://127.0.0.1:8000/style.css >nul 2>nul
if errorlevel 1 goto :stale_backend
curl.exe --silent --fail http://127.0.0.1:8000/app.js >nul 2>nul
if errorlevel 1 goto :stale_backend
curl.exe --silent --fail http://127.0.0.1:8000/assets/auth.css >nul 2>nul
if errorlevel 1 goto :stale_backend
curl.exe --silent --fail http://127.0.0.1:8000/auth.js >nul 2>nul
if errorlevel 1 goto :stale_backend
echo SolarSurd is already running with its frontend at http://127.0.0.1:8000
start "" "http://127.0.0.1:8000"
exit /b 0

:stale_backend
echo A server is answering on port 8000, but its frontend files are missing.
echo Close the old SolarSurd API window with Ctrl+C, then run this launcher again.
echo Do not open frontend\index.html directly; use http://127.0.0.1:8000.
pause
exit /b 1

:start_backend

set "PYTHON_CMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYTHON_CMD="%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe""
if not defined PYTHON_CMD (
  echo Python 3 was not found. Install Python 3.11 or newer, then try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" %PYTHON_CMD% -m venv .venv
if errorlevel 1 (
  echo Could not create the project virtual environment.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python -c "import fastapi, uvicorn, sqlalchemy, pydantic" >nul 2>nul
if errorlevel 1 (
  echo Installing missing web dependencies...
  python -m pip install -r requirements-web.txt
  if errorlevel 1 (
    echo Dependency installation failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)

start "SolarSurd API" /D "%CD%" "%CD%\.venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
for /l %%i in (1,1,20) do (
  curl.exe --silent --fail http://127.0.0.1:8000/health >nul 2>nul
  if not errorlevel 1 goto :backend_ready
  timeout /t 1 /nobreak >nul
)
echo SolarSurd did not become ready on port 8000. Check the SolarSurd API window for the error.
pause
exit /b 1

:backend_ready
start "" "http://127.0.0.1:8000"
endlocal
