# AMEVA PowerShell 설치 스크립트
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host " AMEVA Setup Script (PowerShell)" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# 1. 파이썬 설치 여부 확인
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in PATH. Please install Python."
    Read-Host "Press Enter to exit..."
    exit 1
}

# 2. 가상환경 생성 단계
Write-Host "[1/3] Creating virtual environment (venv)..." -ForegroundColor Yellow
python -m venv venv
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create virtual environment."
    Read-Host "Press Enter to exit..."
    exit 1
}

# 3. 가상환경 활성화 및 pip 업그레이드
Write-Host "[2/3] Activating virtual environment & Upgrading pip..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip

# 4. 종속성 설치 단계
Write-Host "[3/3] Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install dependencies."
    Read-Host "Press Enter to exit..."
    exit 1
}

Write-Host "===================================================" -ForegroundColor Green
Write-Host " Setup completed successfully!" -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Green
Write-Host ""
# 실행 팁 안내
Write-Host "[TIPS] To run the simulation in Local Native mode:" -ForegroundColor Cyan
Write-Host "  1. The system will automatically use llama-cpp-python."
Write-Host "  2. Just click start in the setup modal without manual configuration."
Write-Host ""
Write-Host "Launch command: run.bat" -ForegroundColor Yellow
Write-Host ""
Read-Host "Press Enter to exit..."
