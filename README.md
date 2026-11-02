<div align="center">

# amv-cp-bridge

**M365 Copilot을 로컬 API로 쓸 수 있게 해주는 브릿지**

[English](#english) | 한국어

<p>
  <img src="https://img.shields.io/badge/v1.0.0-blue?style=flat-square" alt="version">
  <img src="https://img.shields.io/badge/Windows%20%7C%20macOS-supported-green?style=flat-square" alt="platform">
  <img src="https://img.shields.io/badge/License-Apache--2.0-blue?style=flat-square" alt="license">
</p>

</div>

---

## 이게 뭔가요?

Microsoft 365 Copilot (Enterprise/Edu) 라이선스가 있지만 API가 없어서 자동화를 못 하는 분들을 위한 도구입니다.

- 헤드리스 Edge 브라우저로 Copilot에 질문을 보내고 답변을 받아옵니다
- OpenAI 호환 REST API (`/v1/chat/completions`) 를 제공합니다
- 쿼리가 끝나면 브라우저를 바로 종료해서 메모리를 차지하지 않습니다
- 모든 데이터는 로컬에만 저장됩니다 (외부 전송 없음)

<p align="center">
  <img src="docs/screenshots/02_gui_dashboard.png" width="640" alt="GUI 대시보드">
  <br>
  <em>네이티브 GUI — 대시보드 탭</em>
</p>

---

## 시작하기

### 필요한 것

- **Microsoft Edge** (Windows 기본 설치 / macOS: `brew install --cask microsoft-edge`)
- **M365 Copilot 라이선스** (Enterprise 또는 Edu)
- Edge에서 Copilot에 로그인된 상태 (https://m365.cloud.microsoft/chat)

---

### Windows

#### 방법 1: EXE 실행 (가장 간단)

[Releases](https://github.com/uno-km/amv-cp-bridge/releases)에서 `amv-cp-bridge.exe`를 받아서 더블클릭하면 됩니다.
네이티브 GUI 창이 열리며 대시보드와 API 서버가 동시에 시작됩니다.

#### 방법 2: 스크립트 실행

`scripts/windows/` 폴더 안에 있는 스크립트를 더블클릭합니다:

```
scripts/windows/1_install.bat      ← Python 확인 + 의존성 설치
scripts/windows/2_dashboard.bat    ← 대시보드 + API 서버 시작
scripts/windows/3_gateway.bat      ← API 서버만 시작 (GUI 없음)
scripts/windows/4_purge.bat        ← 잔여 Edge 프로세스 정리
```

#### 방법 3: 직접 설치

```bash
pip install -e .
amv-cp-bridge dashboard
```

---

### macOS

```bash
# 설치
bash <(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/main/scripts/macos/install.sh)

# 실행
~/.amv_cp_bridge/start.sh
```

또는 직접:
```bash
git clone https://github.com/uno-km/amv-cp-bridge.git
cd amv-cp-bridge
pip install -e .
amv-cp-bridge dashboard
```

---

## 사용법

### 대시보드

`http://localhost:11500/dashboard` 에서 실시간 상태 확인:
- 일/주/월/년 사용량 차트
- 계정 상태 및 큐 모니터링
- 한국어/영어 전환
- 메모리 정리, 통계 초기화

<p align="center">
  <img src="docs/screenshots/05_web_dashboard.png" width="640" alt="웹 대시보드">
  <br>
  <em>웹 대시보드 — 실시간 상태 모니터링</em>
</p>

<p align="center">
  <img src="docs/screenshots/06_web_usage.png" width="640" alt="사용량 통계">
  <br>
  <em>사용량 차트 — 일/주/월/년 통계</em>
</p>

<p align="center">
  <img src="docs/screenshots/07_web_howto.png" width="640" alt="사용 방법">
  <br>
  <em>웹 대시보드 — 사용 방법 안내</em>
</p>

### REST API

```bash
curl http://localhost:11500/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.6-sol",
    "messages": [{"role": "user", "content": "안녕하세요"}],
    "stream": true
  }'
```

모델명은 아무거나 써도 됩니다. 실제로는 M365 Copilot이 응답합니다.

### CLI

| 명령어 | 설명 |
|--------|------|
| `amv-cp-bridge dashboard` | 대시보드 + API 서버 시작 (기본 포트 11500) |
| `amv-cp-bridge gateway` | API 서버만 시작 |
| `amv-cp-bridge ask "질문"` | 터미널에서 바로 질문 |
| `amv-cp-bridge ask "질문" --deep` | 심층 추론 모드 |
| `amv-cp-bridge status` | 현재 상태 확인 |
| `amv-cp-bridge purge` | 잔여 Edge 프로세스 정리 |
| `amv-cp-bridge serve` | MCP 서버 모드 (IDE 연동) |

<p align="center">
  <img src="docs/screenshots/03_gui_usage.png" width="640" alt="GUI 사용량 탭">
  <br>
  <em>네이티브 GUI — 사용량 탭</em>
</p>

<p align="center">
  <img src="docs/screenshots/04_gui_howto.png" width="640" alt="GUI 사용방법 탭">
  <br>
  <em>네이티브 GUI — 사용 방법 탭</em>
</p>

---

## 모듈별 안내

필요한 것만 골라서 쓸 수 있습니다.

### API만 쓰기 (curl / 다른 프로그램에서 호출)

```bash
amv-cp-bridge gateway --port 11500
```
이후 `http://localhost:11500/v1/chat/completions` 로 요청하면 됩니다.

### MCP 서버만 쓰기 (Claude Desktop / Cursor)

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "copilot": {
      "command": "amv-cp-bridge",
      "args": ["serve"]
    }
  }
}
```

**Cursor**: Settings > MCP > Add > Command: `amv-cp-bridge serve`

<p align="center">
  <img src="docs/screenshots/10_mcp_config.png" width="640" alt="MCP 설정">
  <br>
  <em>Claude Desktop MCP 서버 설정 예시</em>
</p>

5가지 모드 지원: 자동, 빠름, 깊게, Sol Quick, Sol Deep Thinking

### 브라우저 확장프로그램 (Chrome / Whale)

1. `chrome://extensions` 또는 `whale://extensions` 접속
2. 개발자 모드 ON
3. "압축해제된 확장 프로그램을 로드합니다" → `extension/` 폴더 선택
4. 사이드바에서 Ctrl+Shift+Y 또는 우클릭으로 사용

### Safari 확장프로그램 (macOS)

Safari Web Extension은 Chrome 확장프로그램을 변환하여 사용합니다.

```bash
# Xcode Command Line Tools 필요
cd extension-safari
bash convert.sh
# 생성된 Xcode 프로젝트를 빌드 후 Safari에서 활성화
```

자세한 안내: [extension-safari/README.md](extension-safari/README.md)

---

## 계정 설정

`~/.amv_cp_bridge/accounts.json` 파일을 편집합니다:

```json
[
  {
    "name": "회사 계정",
    "port": 9333,
    "profile_dir": "C:\\Users\\YOU\\copilot_profile1"
  },
  {
    "name": "학교 계정",
    "port": 9334,
    "profile_dir": "C:\\Users\\YOU\\copilot_profile2"
  }
]
```

macOS의 경우 profile_dir을 `~/.amv_cp_bridge/profiles/account1` 형식으로 지정합니다.

여러 계정을 등록하면 자동으로 로드밸런싱됩니다 (하나가 사용 중이면 다음 계정으로).

---

## 프로젝트 구조

```
amv-cp-bridge/
├── amv_cp_bridge/          # 핵심 Python 패키지
│   ├── cli.py              # CLI 엔트리포인트
│   ├── engine.py           # Playwright CDP 멀티워커 엔진
│   ├── gateway.py          # FastAPI REST 게이트웨이 + 대시보드
│   ├── mcp_server.py       # FastMCP 서버 (Claude Desktop / Cursor)
│   ├── gui.py              # CustomTkinter 네이티브 GUI
│   └── telemetry_db.py     # SQLite 텔레메트리
├── extension/              # Chrome MV3 브라우저 확장프로그램
├── extension-safari/       # Safari 변환 스크립트 (macOS)
├── scripts/
│   ├── windows/            # Windows 실행 스크립트
│   │   ├── 1_install.bat   # 의존성 설치
│   │   ├── 2_dashboard.bat # 서버 + GUI 시작
│   │   ├── 3_gateway.bat   # API 서버만 시작
│   │   ├── 4_purge.bat     # 메모리 정리
│   │   └── 999_uninstall.bat / 999_uninstall.ps1
│   ├── macos/              # macOS 실행 스크립트
│   │   ├── install.sh
│   │   ├── start_dashboard.command
│   │   └── start_gateway.command
│   └── build/              # PyInstaller 빌드 스크립트
│       ├── build_exe.py
│       └── amv-cp-bridge.spec
├── docs/
│   └── screenshots/        # README 삽입 스크린샷
├── dist/                   # 빌드 산출물 (amv-cp-bridge.exe)
├── pyproject.toml
├── requirements.txt
└── LICENSE
```

---

## 기술 스택

| 구성 | 기술 |
|------|------|
| 백엔드 | Python, FastAPI, Playwright |
| 데이터 | SQLite |
| 브라우저 확장 | Chrome Manifest V3 |
| GUI | CustomTkinter (네이티브 Python GUI, 크로스플랫폼) |
| MCP | FastMCP |
| 패키징 | PyInstaller |

---

---

## 제거 (Uninstall)

### 원터치 삭제 (Windows)

`scripts/windows/999_uninstall.bat` 을 더블클릭하면 아래 항목을 모두 자동 제거합니다.

```
[v] amv-cp-bridge process(es) terminated
[v] Port 11500 released
[v] Orphaned Edge worker processes terminated
[v] ~/.amv_cp_bridge/ data directory removed
[v] pip package uninstalled
[v] MCP config entry removed
[v] Playwright browser cache removed
[v] EXE file removed
```

또는 PowerShell에서 직접 실행:

```powershell
# 전체 삭제
PowerShell -ExecutionPolicy Bypass -File scripts\windows\999_uninstall.ps1

# Playwright 캐시 유지 (빠른 재설치용)
PowerShell -ExecutionPolicy Bypass -File scripts\windows\999_uninstall.ps1 -KeepPlaywright

# EXE 파일 유지
PowerShell -ExecutionPolicy Bypass -File scripts\windows\999_uninstall.ps1 -KeepEXE
```

### 수동 삭제 (CMD 단계별)

```cmd
:: 1. 프로세스 종료
taskkill /F /IM amv-cp-bridge.exe

:: 2. 포트 11500 해제
for /f "tokens=5" %a in ('netstat -ano -p TCP ^| findstr ":11500"') do taskkill /F /PID %a

:: 3. 설정·DB·로그 삭제
rmdir /s /q "%USERPROFILE%\.amv_cp_bridge"

:: 4. pip 패키지 제거
python -m pip uninstall -y amv-cp-bridge

:: 5. EXE 삭제 (직접 다운받은 경우)
del /f amv-cp-bridge.exe
```

> **브라우저 확장프로그램**은 `chrome://extensions`에서 직접 제거해야 합니다.

---

## 보안

- 배포 EXE는 PyInstaller로 패키징됩니다 (`scripts/build/amv-cp-bridge.spec`)
- Copilot 세션 및 자격증명은 로컬 Edge 프로파일에만 유지되며, 외부 서버로 전송되지 않습니다
- 텔레메트리 DB (`~/.amv_cp_bridge/telemetry.db`)는 로컬 전용입니다
- 소스코드는 [`amv_cp_bridge/`](amv_cp_bridge/) 디렉토리에서 직접 확인할 수 있습니다

---

## 라이선스

Apache-2.0 OR Commercial License

Copyright (c) 2026 Eunho Kim / AMEVA Foundation

상업적 이용 문의: contact@uno-km.com

---

<a id="english"></a>

## English

### What is this?

A bridge that lets you use Microsoft 365 Copilot (Enterprise/Edu) as a local API.
It automates a headless Edge browser to send prompts to Copilot and stream back responses through an OpenAI-compatible REST API.

### Key features

- **OpenAI-compatible API**: `POST http://localhost:11500/v1/chat/completions`
- **Zero memory leak**: Browser process is killed immediately after each query
- **Multi-account load balancing**: Register multiple M365 accounts for automatic failover
- **MCP server**: Works with Claude Desktop, Cursor, and other MCP-compatible tools
- **Browser extension**: Chrome/Whale sidebar for quick access
- **Safari extension**: Convert from Chrome extension using Xcode (macOS)
- **Dashboard**: Real-time usage charts, account status, Korean/English toggle
- **100% local**: No data leaves your machine

<p align="center">
  <img src="docs/screenshots/05_web_dashboard.png" width="640" alt="Web Dashboard">
  <br>
  <em>Web Dashboard — Real-time status monitoring</em>
</p>

### Project structure

```
amv-cp-bridge/
├── amv_cp_bridge/          # Core Python package
│   ├── cli.py              # CLI entry point
│   ├── engine.py           # Playwright CDP multi-worker engine
│   ├── gateway.py          # FastAPI REST gateway + dashboard
│   ├── mcp_server.py       # FastMCP server (Claude Desktop / Cursor)
│   ├── gui.py              # CustomTkinter native GUI
│   └── telemetry_db.py     # SQLite telemetry
├── extension/              # Chrome MV3 browser extension
├── extension-safari/       # Safari conversion scripts (macOS)
├── scripts/
│   ├── windows/            # Windows launch scripts
│   │   ├── 1_install.bat
│   │   ├── 2_dashboard.bat
│   │   ├── 3_gateway.bat
│   │   ├── 4_purge.bat
│   │   └── 999_uninstall.bat / 999_uninstall.ps1
│   ├── macos/              # macOS launch scripts
│   │   ├── install.sh
│   │   ├── start_dashboard.command
│   │   └── start_gateway.command
│   └── build/              # PyInstaller build scripts
├── docs/screenshots/       # README screenshots
├── dist/                   # Build output (amv-cp-bridge.exe)
├── pyproject.toml
├── requirements.txt
└── LICENSE
```

### Quick start

**Windows (EXE — simplest):**
Download `amv-cp-bridge.exe` from [Releases](https://github.com/uno-km/amv-cp-bridge/releases) and double-click.

**Windows (scripts):**
```
scripts/windows/1_install.bat      ← Install Python deps
scripts/windows/2_dashboard.bat    ← Start dashboard + API server
```

**macOS:**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/main/scripts/macos/install.sh)
~/.amv_cp_bridge/start.sh
```

**From source (any platform):**
```bash
git clone https://github.com/uno-km/amv-cp-bridge.git
cd amv-cp-bridge
pip install -e .
amv-cp-bridge dashboard
```

### Prerequisites

- Microsoft Edge browser
- M365 Copilot license (Enterprise or Edu)
- Signed into Copilot in Edge (https://m365.cloud.microsoft/chat)
- Python 3.10+ (if not using EXE)

### API usage

```bash
curl http://localhost:11500/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"any","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

### MCP setup

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "copilot": {
      "command": "amv-cp-bridge",
      "args": ["serve"]
    }
  }
}
```

### Browser extension

1. Go to `chrome://extensions`
2. Enable Developer mode
3. Click "Load unpacked" → select the `extension/` folder
4. Use via sidebar (Ctrl+Shift+Y) or right-click context menu

### Safari extension (macOS)

```bash
cd extension-safari && bash convert.sh
# Build the generated Xcode project, then enable in Safari > Settings > Extensions
```

### Uninstall

**One-click removal (Windows):**
Double-click `scripts/windows/999_uninstall.bat`, or run:

```powershell
PowerShell -ExecutionPolicy Bypass -File scripts\windows\999_uninstall.ps1
```

This removes: running processes · port 11500 · `~/.amv_cp_bridge/` · pip package · MCP config entry · Playwright cache · EXE.

**Manual removal (CMD):**
```cmd
taskkill /F /IM amv-cp-bridge.exe
rmdir /s /q "%USERPROFILE%\.amv_cp_bridge"
python -m pip uninstall -y amv-cp-bridge
```

> Browser extensions must be removed manually via `chrome://extensions`.

### Security

- EXE is packaged with PyInstaller (`scripts/build/amv-cp-bridge.spec`)
- Copilot sessions and credentials remain in the local Edge profile — nothing is sent to external servers
- Telemetry (`~/.amv_cp_bridge/telemetry.db`) is local-only
- Source code is available in the [`amv_cp_bridge/`](amv_cp_bridge/) directory

### License

Apache-2.0 OR Commercial License — Copyright (c) 2026 Eunho Kim / AMEVA Foundation

Commercial licensing: contact@uno-km.com
