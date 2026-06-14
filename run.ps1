# AMEVA Dead Internet Theatre 실행 및 환경 진단 스크립트

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
if ($ScriptPath) { Set-Location -Path $ScriptPath }

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($PSVersionTable.PSVersion.Major -le 5) { chcp 65001 | Out-Null }
$ErrorActionPreference = "Stop"

Write-Host "--- AMEVA Dead Internet Theatre Environment Setup ---" -ForegroundColor Cyan
Write-Host "Path: $(Get-Location)" -ForegroundColor Gray

# [1] 파이썬 가상환경(venv) 검증 및 패키지 설치 단계
$EnvDir = ".\venv"
if (-not (Test-Path -Path $EnvDir)) {
    Write-Host "Virtual environment (venv) not found. Creating virtual environment..." -ForegroundColor Yellow
    python -m venv $EnvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment."
        exit 1
    }
    
    Write-Host "Upgrading pip and installing requirements..." -ForegroundColor Yellow
    & "$EnvDir\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
    & "$EnvDir\Scripts\python.exe" -m pip install -r requirements.txt
}

# [2] 하드웨어와 설치된 LLM 엔진 정합성 검증
Write-Host "Verifying hardware and LLM engine match..." -ForegroundColor Cyan
$videoControllers = Get-CimInstance Win32_VideoController
$hasNvidia = $false
foreach ($vc in $videoControllers) {
    if ($vc.Name -match "NVIDIA") { $hasNvidia = $true }
}

# NVIDIA GPU가 있을 경우 CUDA Toolkit 설치 여부 확인
if ($hasNvidia) {
    $cudaPath = [Environment]::GetEnvironmentVariable('CUDA_PATH')
    if (-not $cudaPath) {
        # 환경변수가 아직 갱신되지 않았을 경우 머신 레벨에서 가져오기 시도
        $machineCuda = [Environment]::GetEnvironmentVariable('CUDA_PATH', 'Machine')
        if ($machineCuda) {
            Write-Host "Discovered CUDA_PATH from registry. Applying to current session." -ForegroundColor Green
            [Environment]::SetEnvironmentVariable('CUDA_PATH', $machineCuda, 'Process')
            $env:PATH += ";$machineCuda\bin"
            $cudaPath = $machineCuda
        }
    }
    
    if (-not $cudaPath) {
        Write-Host "[WARNING] NVIDIA GPU detected, but CUDA Toolkit (CUDA_PATH) is missing. Reverting to CPU mode." -ForegroundColor Yellow
        $hasNvidia = $false
    }
}

$pythonExe = "$EnvDir\Scripts\python.exe"
$checkScript = "try:`n    from llama_cpp import llama_supports_gpu_offload`n    print('GPU' if llama_supports_gpu_offload() else 'CPU')`nexcept Exception as e:`n    if 'llama.dll' in str(e) or 'cudart' in str(e).lower(): print('GPU_MISSING_CUDA')`n    else: print('NONE')"
$engineStatus = & $pythonExe -c $checkScript

if ($hasNvidia -and $engineStatus -eq "CPU") {
    Write-Host "NVIDIA GPU detected, but CPU engine is installed. Fixing..." -ForegroundColor Yellow
    & $pythonExe -m pip install llama-cpp-python[server] --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121 --force-reinstall --no-cache-dir --only-binary=llama-cpp-python
} elseif ($hasNvidia -and $engineStatus -eq "GPU_MISSING_CUDA") {
    Write-Host "[WARNING] NVIDIA GPU detected, but CUDA 12 Toolkit is missing. Reverting to CPU engine to prevent crash." -ForegroundColor Red
    & $pythonExe -m pip install llama-cpp-python[server] --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --force-reinstall --no-cache-dir --only-binary=llama-cpp-python
} elseif (-not $hasNvidia -and ($engineStatus -eq "GPU" -or $engineStatus -eq "GPU_MISSING_CUDA")) {
    Write-Host "No NVIDIA GPU detected, but GPU engine is installed. Fixing..." -ForegroundColor Yellow
    & $pythonExe -m pip install llama-cpp-python[server] --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --force-reinstall --no-cache-dir --only-binary=llama-cpp-python
} elseif ($engineStatus -eq "NONE") {
    Write-Host "Engine not found. Installing default CPU engine..." -ForegroundColor Yellow
    & $pythonExe -m pip install llama-cpp-python[server] --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --only-binary=llama-cpp-python
} else {
    Write-Host "Hardware and Engine configuration matches." -ForegroundColor Green
}

# [3] 가상환경 활성화 단계
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
. "$EnvDir\Scripts\Activate.ps1"

# [4] 메인 어플리케이션 진입 및 기동
Write-Host "Launching AMEVA Dead Internet Theatre..." -ForegroundColor Cyan
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

& "$EnvDir\Scripts\python.exe" run.py
