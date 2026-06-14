# AMEVA Setup Script for PowerShell
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host " AMEVA Setup Script (PowerShell)" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# 1. Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in PATH. Please install Python."
    Read-Host "Press Enter to exit..."
    exit 1
}

# 2. Create Venv
Write-Host "[1/3] Creating virtual environment (venv)..." -ForegroundColor Yellow
python -m venv venv
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create virtual environment."
    Read-Host "Press Enter to exit..."
    exit 1
}

# 3. Activate and Install
Write-Host "[2/3] Activating virtual environment & Upgrading pip..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip

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
Write-Host "팁: 로컬 직접 실행(Native llama.cpp) 모드를 사용하려면:" -ForegroundColor Cyan
Write-Host "  1. llama.cpp 저장소에서 prebuilt llama-server.exe를 다운로드하거나 빌드합니다."
Write-Host "  2. 웹 UI 초기 설정 모달에서 '로컬 직접 실행'을 선택하고"
Write-Host "     llama-server.exe의 절대 경로를 지정해 주세요."
Write-Host ""
Write-Host "서버 실행 방법: python run.py" -ForegroundColor Yellow
Write-Host ""
Read-Host "Press Enter to exit..."
