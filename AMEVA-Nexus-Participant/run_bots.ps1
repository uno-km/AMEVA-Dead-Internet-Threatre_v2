# AMEVA-Dead-Internet-Threatre Bots Runner
# 코랩 GPU 엔드포인트에 4개의 로컬 봇을 각각 연결하여 병렬로 실행하는 스크립트입니다.

param(
    [string]$OllamaUrl = "https://means-sharing-assure-receptor.trycloudflare.com",
    [string]$Model = "qwen2.5:3b"
)

Write-Host "기존에 백그라운드에서 실행 중이던 파이썬 봇 프로세스를 종료합니다..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*client_ws.py*" } | Stop-Process -Force

Write-Host "`n4개의 AI 봇을 코랩 GPU 서버($OllamaUrl)와 연결하여 실행 중..." -ForegroundColor Cyan

$PythonPath = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"

# Bot 1 - Cynic
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_1 --exp EXP_TEST --server ws://localhost:8050 --ollama $OllamaUrl --model $Model" -WorkingDirectory $PSScriptRoot -RedirectStandardOutput "$PSScriptRoot\bot_1.log" -RedirectStandardError "$PSScriptRoot\bot_1_err.log" -NoNewWindow
Write-Host "✅ bot_1 (냉소주의 봇) 시작됨 -> $OllamaUrl" -ForegroundColor Green

# Bot 2 - Boomer
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_2 --exp EXP_TEST --server ws://localhost:8050 --ollama $OllamaUrl --model $Model" -WorkingDirectory $PSScriptRoot -RedirectStandardOutput "$PSScriptRoot\bot_2.log" -RedirectStandardError "$PSScriptRoot\bot_2_err.log" -NoNewWindow
Write-Host "✅ bot_2 (꼰대 도덕주의 봇) 시작됨 -> $OllamaUrl" -ForegroundColor Green

# Bot 3 - TMI
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_3 --exp EXP_TEST --server ws://localhost:8050 --ollama $OllamaUrl --model $Model" -WorkingDirectory $PSScriptRoot -RedirectStandardOutput "$PSScriptRoot\bot_3.log" -RedirectStandardError "$PSScriptRoot\bot_3_err.log" -NoNewWindow
Write-Host "✅ bot_3 (TMI 일상 봇) 시작됨 -> $OllamaUrl" -ForegroundColor Green

# Bot 4 - Hype Bot
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_4 --exp EXP_TEST --server ws://localhost:8050 --ollama $OllamaUrl --model $Model" -WorkingDirectory $PSScriptRoot -RedirectStandardOutput "$PSScriptRoot\bot_4.log" -RedirectStandardError "$PSScriptRoot\bot_4_err.log" -NoNewWindow
Write-Host "✅ bot_4 (AI 테크 낙관론 봇) 시작됨 -> $OllamaUrl" -ForegroundColor Green

Write-Host "`n모든 봇이 백그라운드에서 실행 중입니다! 로컬 서버(ws://localhost:8050)와의 통신 로그를 확인해 주세요." -ForegroundColor Cyan
