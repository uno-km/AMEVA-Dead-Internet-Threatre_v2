@echo off
:: AMEVA 설치 스크립트
echo ===================================================
echo  AMEVA Setup Script
echo ===================================================

:: 파이썬 가상환경 생성 단계
echo [1/3] Creating virtual environment (venv)...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

:: 가상환경 활성화 단계
echo [2/3] Activating virtual environment...
call .\venv\Scripts\activate.bat

:: 종속성 패키지 설치 단계
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
:: 실행 팁 안내
echo [TIPS] To run the simulation in Local Native mode:
echo   1. The system will automatically use llama-cpp-python.
echo   2. Just click start in the setup modal without manual configuration.
echo.
echo Launch command: run.bat
echo ===================================================
pause
exit /b 0
