@echo off
title amv-cp-bridge Uninstaller
PowerShell -ExecutionPolicy Bypass -File "%~dp0999.delete.ps1"
echo.
pause
