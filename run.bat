@echo off
:: AMEVA Dead Internet Theatre - One-click run script
:: Bypasses PowerShell execution policy to run run.ps1

echo [AMEVA] Dead Internet Theatre system running...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

echo.
echo System terminated. Press any key to close.
pause
