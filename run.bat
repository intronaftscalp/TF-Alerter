@echo off
REM ============================================
REM Launch script for TF-Alerter
REM ============================================

echo.
echo === TF-Alerter Launcher ===
echo.

cd /d "%~dp0"

set "PY_EXE="
set "PY_ARGS="
if exist ".venv\Scripts\python.exe" set "PY_EXE=.venv\Scripts\python.exe"
if not defined PY_EXE (
    where python >nul 2>&1
    if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=py"
        set "PY_ARGS=-3"
    )
)

if not defined PY_EXE (
    echo ERROR: Python is not installed or not in PATH.
    echo Install Python 3.10 or newer and run install_dependencies.bat.
    echo.
    pause
    exit /b 1
)

"%PY_EXE%" %PY_ARGS% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not start Python.
    pause
    exit /b 1
)

echo [*] Starting TF-Alerter...
echo [*] Python: %PY_EXE% %PY_ARGS%
echo.

"%PY_EXE%" %PY_ARGS% main.py

if errorlevel 1 (
    echo.
    echo ERROR: Failed to start application
    echo Make sure dependencies are installed in the selected venv.
    pause
    exit /b 1
)
