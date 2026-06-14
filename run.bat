@echo off
:: AMEVA Dead Internet Theatre 원클릭 가동 스크립트
:: PowerShell 보안 정책을 우회하여 run.ps1을 실행합니다.

echo [AMEVA] Dead Internet Theatre system running...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

echo.
:: 시스템 종료 후 대기
echo System terminated. Press any key to close.
pause
