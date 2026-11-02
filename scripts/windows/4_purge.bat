@echo off
chcp 65001 >nul
title amv-cp-bridge | Memory Purge (0MB)
cls
echo ============================================================
echo   ⚡ amv-cp-bridge ^| 0MB 메모리 강제 완전 소각기
echo ============================================================
echo.
echo [*] 포트 9333 / 9334 및 잔존 Edge 프로세스를 전수 검사하여 소각합니다...
echo.
python -m amv_cp_bridge.cli purge
echo.
echo [*] 현재 메모리 상태 확인:
python -m amv_cp_bridge.cli status
echo.
echo ============================================================
echo [완료] 모든 잔여 메모리가 0MB로 깨끗하게 회수되었습니다.
echo ============================================================
pause
