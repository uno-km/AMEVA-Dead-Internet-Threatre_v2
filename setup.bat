@echo off
echo ===================================================
echo  AMEVA Setup Script
echo ===================================================

echo [1/3] Creating virtual environment (venv)...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/3] Activating virtual environment...
call .\venv\Scripts\activate.bat

echo [3/3] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo ===================================================
echo  Setup completed successfully!
echo ===================================================
echo.
echo [TIPS] To run the simulation in Local Native mode:
echo   1. Ensure you have llama-server.exe built/downloaded locally.
echo   2. In the setup modal, choose "로컬 직접 실행" and enter its path.
echo.
echo Launch command: python run.py
echo ===================================================
pause
exit /b 0
