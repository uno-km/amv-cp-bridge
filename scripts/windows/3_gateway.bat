@echo off
chcp 65001 >nul
title amv-cp-bridge Gateway [Port 11500]
cls
echo ============================================================
echo   amv-cp-bridge ^| 365 Copilot AI Gateway
echo ============================================================
echo.
echo [*] 게이트웨이 서버를 시작합니다 (http://localhost:11500)...
echo [*] 네이버 웨일 또는 크롬 사이드바에서 즉시 사용하실 수 있습니다.
echo [*] 종료하시려면 이 창을 닫거나 Ctrl+C 를 누르십시오.
echo.
python -m amv_cp_bridge.cli gateway --port 11500
pause
