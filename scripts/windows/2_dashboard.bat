@echo off
chcp 65001 >nul
title amv-cp-bridge Core Dashboard [Port 11500]
cls
echo ============================================================
echo   ⚡ amv-cp-bridge ^| Sovereign AI Gateway ^& Dashboard
echo ============================================================
echo.
echo [*] 게이트웨이 및 실시간 텔레메트리 대시보드를 시작합니다...
echo [*] 대시보드 URL: http://localhost:11500/dashboard
echo [*] 네이버 웨일 / 크롬 사이드바가 자동으로 연동됩니다.
echo [*] 종료하시려면 이 창을 닫거나 Ctrl+C 를 누르십시오.
echo.
python -m amv_cp_bridge.cli dashboard --port 11500
pause
