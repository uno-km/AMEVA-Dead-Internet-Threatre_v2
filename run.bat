@echo off
:: AMEVA Dead Internet Theatre 원클릭 가동 래퍼
:: PowerShell 보안 정책을 우회하여 run.ps1을 실행합니다.

echo [AMEVA] Dead Internet Theatre system running...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

echo.
echo System terminated. Press any key to close.
pause
