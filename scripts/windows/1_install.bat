@echo off
chcp 65001 > nul
title amv-cp-bridge Local Setup & Launcher

echo =====================================================================
echo  ⚡ amv-cp-bridge :: 초경량 M365 Copilot 브릿지 원클릭 환경 구축기
echo =====================================================================
echo.

:: 1. 파이썬 설치 여부 검사
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Python이 시스템에 감지되지 않았습니다.
    echo [*] Windows 패키지 관리자(winget)로 Python 3.11 설치를 시도합니다...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [-] 자동 설치에 실패했습니다. https://www.python.org 에서 파이썬을 설치 후 다시 실행해 주십시오.
        pause
        exit /b 1
    )
    echo [+] Python 설치 완료. 환경 변수 갱신 후 재실행을 권장합니다.
)

for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version.split()[0])"') do set PY_VER=%%i
echo [+] Python 버전 확인: v%PY_VER%

:: 2. 필수 의존성 패키지 설치 및 amv-cp-bridge 로컬 등록
echo.
echo [*] 필수 패키지 (fastapi, uvicorn, websockets, pydantic) 및 로컬 브릿지 모듈 등록 중...
python -m pip install --upgrade pip --quiet
python -m pip install fastapi uvicorn websockets pydantic --quiet
python -m pip install -e . --quiet
if %errorlevel% neq 0 (
    echo [-] 패키지 등록 중 오류가 발생했습니다.
    pause
    exit /b 1
)
echo [+] amv-cp-bridge 패키지 등록 완료.

:: 3. 텔레메트리 SQLite 데이터베이스 확인
python -c "from amv_cp_bridge.telemetry_db import telemetry_db; print('[+] SQLite 텔레메트리 DB 준비 완료: ~/.amv_cp_bridge/telemetry.db')"

echo.
echo =====================================================================
echo  [+] 모든 준비가 완료되었습니다!
echo  [*] 실시간 Cyber Dark 대시보드 및 게이트웨이를 기동합니다.
echo  [*] 브라우저(http://localhost:11500/dashboard)가 자동으로 열립니다.
echo =====================================================================
echo.

python -m amv_cp_bridge.cli dashboard --port 11500
pause
