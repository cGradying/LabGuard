@echo off
setlocal
REM ==============================================================================
REM LabGuard+ — Local PC Launcher (Windows)
REM Runs the Raspberry Pi Python Flask backend (app.py) inside a local .venv
REM ==============================================================================

cd /d "%~dp0"

if "%PORT%"=="" set "PORT=5000"

echo ==================================================================
echo   LabGuard+ Smart Science Laboratory Kiosk - Windows Local Runner
echo   Arellano University - Jose Rizal Campus
echo ==================================================================

set "PY_CMD="
where python >nul 2>nul && set "PY_CMD=python"
if "%PY_CMD%"=="" (
    where py >nul 2>nul && set "PY_CMD=py -3"
)

if "%PY_CMD%"=="" (
    echo [!] Python 3 is not found in your PATH.
    echo     Please install Python 3.9+ from https://www.python.org
    echo     Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [+] Creating local virtual environment in .venv...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [!] Failed to create .venv.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import flask, flask_sock, qrcode" >nul 2>nul
if errorlevel 1 (
    echo [+] Installing Python dependencies from requirements.txt...
    ".venv\Scripts\pip.exe" install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [!] Failed to install requirements.txt.
        pause
        exit /b 1
    )
)

echo [+] Starting LabGuard+ Python server on http://localhost:%PORT%
echo     Kiosk UI  : http://localhost:%PORT%/kiosk
echo     Admin UI  : http://localhost:%PORT%/admin
echo     Health API: http://localhost:%PORT%/api/health
echo     Press Ctrl+C to stop.
echo.

start "" "http://localhost:%PORT%/kiosk"
".venv\Scripts\python.exe" app.py

pause
endlocal
