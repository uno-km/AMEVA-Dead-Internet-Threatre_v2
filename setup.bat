@echo off
:: AMEVA Setup Script
echo ===================================================
echo  AMEVA Setup Script
echo ===================================================

:: Step 1: Create virtual environment
echo [1/3] Creating virtual environment (venv)...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

:: Step 2: Activate virtual environment
echo [2/3] Activating virtual environment...
call .\venv\Scripts\activate.bat

:: Step 3: Install dependencies
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
:: Execution tips
echo [TIPS] To run the simulation in Local Native mode:
echo   1. The system will automatically use llama-cpp-python.
echo   2. Just click start in the setup modal without manual configuration.
echo.
echo Launch command: run.bat
echo ===================================================
pause
exit /b 0
