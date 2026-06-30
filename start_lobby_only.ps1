# start_lobby_only.ps1
# AMEVA 대기소 및 봇 컴포넌트 자동 기동 스크립트 (DIT 서버 구동 안 함)

# 절대 경로 정의
$WorkspaceRoot = Get-Location
$PythonPath = "$WorkspaceRoot\venv\Scripts\python.exe"
$ParticipantDir = "$WorkspaceRoot\AMEVA-Nexus-Participant"

# 1. 기존 파이썬 백그라운드 프로세스 종료 (이전 실행 찌꺼기 제거)
Write-Host "이전 파이썬 프로세스 정리 중..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*run.py*" -or $_.CommandLine -like "*client_ws.py*" } | Stop-Process -Force

# 2. Platform Hub 기동 (8050 포트)
Write-Host "`n1. Platform Hub 기동 중..." -ForegroundColor Cyan
Start-Process $PythonPath -ArgumentList "$WorkspaceRoot\AMEVA-Nexus-Platform\run.py" -WorkingDirectory "$WorkspaceRoot\AMEVA-Nexus-Platform" -NoNewWindow -RedirectStandardOutput "$WorkspaceRoot\platform_server.log" -RedirectStandardError "$WorkspaceRoot\platform_server_err.log"
Write-Host "✅ Platform Hub가 백그라운드에서 시작되었습니다. (http://localhost:8050)" -ForegroundColor Green

# 서버 초기화 대기 (데이터베이스 및 소켓 바인딩 안정화)
Start-Sleep -Seconds 4

# 3. 3개 코랩 주소 정의 (받아오신 3개의 주소를 맵핑)
$Colab1 = "https://inform-arrow-jerry-charging.trycloudflare.com"
$Colab2 = "https://bali-corn-illustration-panel.trycloudflare.com"
$Colab3 = "https://gonna-habits-composer-discrete.trycloudflare.com"
$Model = "qwen2.5:3b"

Write-Host "`n2. 5개의 에이전트 봇 기동 및 코랩 GPU 노드 분산 연결 중..." -ForegroundColor Cyan

# Bot 1 -> Colab 1
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_1 --exp LOBBY --server ws://localhost:8050 --ollama $Colab1 --model $Model" -WorkingDirectory $ParticipantDir -NoNewWindow -RedirectStandardOutput "$ParticipantDir\bot_1.log" -RedirectStandardError "$ParticipantDir\bot_1_err.log"
Write-Host "✅ bot_1 (냉소주의) 구동됨 -> Colab 1 연결 완료" -ForegroundColor Green

# Bot 2 -> Colab 2
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_2 --exp LOBBY --server ws://localhost:8050 --ollama $Colab2 --model $Model" -WorkingDirectory $ParticipantDir -NoNewWindow -RedirectStandardOutput "$ParticipantDir\bot_2.log" -RedirectStandardError "$ParticipantDir\bot_2_err.log"
Write-Host "✅ bot_2 (보수 꼰대) 구동됨 -> Colab 2 연결 완료" -ForegroundColor Green

# Bot 3 -> Colab 3
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_3 --exp LOBBY --server ws://localhost:8050 --ollama $Colab3 --model $Model" -WorkingDirectory $ParticipantDir -NoNewWindow -RedirectStandardOutput "$ParticipantDir\bot_3.log" -RedirectStandardError "$ParticipantDir\bot_3_err.log"
Write-Host "✅ bot_3 (TMI 일상) 구동됨 -> Colab 3 연결 완료" -ForegroundColor Green

# Bot 4 -> Colab 1
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_4 --exp LOBBY --server ws://localhost:8050 --ollama $Colab1 --model $Model" -WorkingDirectory $ParticipantDir -NoNewWindow -RedirectStandardOutput "$ParticipantDir\bot_4.log" -RedirectStandardError "$ParticipantDir\bot_4_err.log"
Write-Host "✅ bot_4 (테크 낙관) 구동됨 -> Colab 1 연결 완료 (공유)" -ForegroundColor Green

# Bot 5 -> Colab 2
Start-Process $PythonPath -ArgumentList "client_ws.py --bot bot_5 --exp LOBBY --server ws://localhost:8050 --ollama $Colab2 --model $Model" -WorkingDirectory $ParticipantDir -NoNewWindow -RedirectStandardOutput "$ParticipantDir\bot_5.log" -RedirectStandardError "$ParticipantDir\bot_5_err.log"
Write-Host "✅ bot_5 (음모론자) 구동됨 -> Colab 2 연결 완료 (공유)" -ForegroundColor Green

Write-Host "`n" + "="*80 -ForegroundColor Yellow
Write-Host "🎉 대기소 서버(8050) 및 5인 봇 기동 완료 (DIT 서버 비활성 상태)" -ForegroundColor Green
Write-Host "👉 웹 브라우저를 열고 대기소에 접속하세요: http://localhost:8050" -ForegroundColor Cyan
Write-Host "="*80 -ForegroundColor Yellow

Write-Host "`n[중요] 대기소 서버와 봇들이 백그라운드에서 실행되도록 이 태스크를 유지합니다." -ForegroundColor Magenta
Write-Host "종료하려면 IDE에서 태스크를 kill(중단)해 주세요." -ForegroundColor Magenta

while ($true) {
    Start-Sleep -Seconds 10
}
