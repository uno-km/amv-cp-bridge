<div align="center">

# amv-cp-bridge

**M365 Copilot을 로컬 API로 쓸 수 있게 해주는 브릿지**

[English](#english) | 한국어

<p>
  <img src="https://img.shields.io/badge/v1.0.2-blue?style=flat-square" alt="version">
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

프로그램은 평소 쓰는 Edge와 분리된 전용 Edge 프로필을 사용합니다. 처음 실행하면 계정이 `연결 확인 전`으로 표시되며, `계정 연결` 버튼을 누르면 Edge 창이 열립니다. Windows 계정으로 Edge가 자동 로그인되면 바로 연결되고, 그렇지 않으면 열린 창에서 Copilot에 로그인하면 됩니다.

---

### 원터치 설치 (권장)

README의 명령은 모두 한 줄입니다. 여러 단계는 `&&`로 이어 두었으므로, 붙여 넣어도 앞 단계가 실패하면 뒤 단계는 실행되지 않습니다.

Python이 없어도 됩니다. Python, Microsoft Edge(없는 경우), 필요한 라이브러리, 프로그램을 모두 설치한 뒤 실행합니다.

**Windows** (PowerShell 또는 cmd에 붙여넣기)

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/setup_all.ps1 | iex"
```

> **알려진 문제:** 2026-11-02 기준 Microsoft Defender가 이 명령을 `Trojan:Win32/Commando.A!ml`로 탐지해 차단하는 사례를 확인했습니다. 명령줄에 대한 탐지이며, 배포 EXE와 설치 스크립트 파일은 같은 PC의 Defender 검사에서 탐지되지 않았습니다. 앱 안의 `업데이트` 버튼도 같은 명령을 사용합니다. 차단되면 Defender를 끄지 말고 아래 [EXE 실행](#방법-1-exe-실행) 방법으로 최신 버전을 받으십시오.

**macOS** (터미널에 붙여넣기)

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/setup_all.sh)"
```

프로그램은 시작할 때 새 버전을 확인합니다. 새 버전이 있으면 `업데이트` 또는 `다음에 하기`를 선택할 수 있고, 설치 후 첫 실행에서 릴리스 노트를 표시합니다.

---

### Windows

#### 방법 1: EXE 실행

[Releases](https://github.com/uno-km/amv-cp-bridge/releases)에서 `amv-cp-bridge.exe`를 받아서 더블클릭하면 됩니다.
네이티브 GUI 창이 열리며 대시보드와 API 서버가 동시에 시작됩니다.

#### 방법 2: 스크립트 실행

`scripts/windows/` 폴더 안에 있는 스크립트를 더블클릭합니다. 터미널 명령이 아닙니다.

| 파일 | 동작 |
|------|------|
| `1_install.bat` | Python 확인 + 의존성 설치 |
| `2_dashboard.bat` | 대시보드 + API 서버 시작 |
| `3_gateway.bat` | API 서버만 시작 (GUI 없음) |
| `4_purge.bat` | 잔여 Edge 프로세스 정리 |

#### 방법 3: 직접 설치

저장소 폴더에서 실행합니다. PowerShell과 cmd 모두 동작합니다.

```
cmd /c "pip install -e . && amv-cp-bridge dashboard"
```

---

### macOS

위 원터치 설치를 실행한 뒤 바탕화면의 `amv-cp-bridge.command` 또는 `~/.amv_cp_bridge/start.sh`로 실행합니다.

또는 직접:
```bash
git clone https://github.com/uno-km/amv-cp-bridge.git && cd amv-cp-bridge && pip install -e . && amv-cp-bridge dashboard
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

**macOS, Linux, Git Bash**

```bash
curl -N http://localhost:11500/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"gpt-5.6-sol","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

**Windows PowerShell**

```powershell
irm http://localhost:11500/v1/chat/completions -Method Post -ContentType application/json -Body '{"model":"gpt-5.6-sol","messages":[{"role":"user","content":"Hello"}]}' | ConvertTo-Json -Depth 6
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

1. Releases에서 [`amv-cp-bridge-extension.zip`](https://github.com/uno-km/amv-cp-bridge/releases/latest/download/amv-cp-bridge-extension.zip)을 받아 압축을 풉니다
2. `chrome://extensions`, `edge://extensions`, `whale://extensions` 중 사용하는 브라우저 주소로 접속
3. 개발자 모드 ON
4. "압축해제된 확장 프로그램을 로드합니다" → 압축을 푼 폴더 선택
5. 사이드바에서 Ctrl+Shift+Y 또는 우클릭으로 사용

### Safari 확장프로그램 (macOS)

Safari Web Extension은 Chrome 확장프로그램을 변환하여 사용합니다. Xcode Command Line Tools가 필요합니다.

```bash
cd extension-safari && bash convert.sh
```

명령이 끝나면 생성된 Xcode 프로젝트를 빌드한 뒤 Safari에서 활성화합니다.

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

여러 계정을 등록해도 요청은 한 번에 하나씩 순서대로 처리합니다. 처리는 첫 번째 계정이 맡고, 첫 번째 계정이 로그인 창으로 사용 중일 때만 다음 계정을 사용합니다.

---

## 프로젝트 구조

```text
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

### Windows

저장소를 내려받지 않아도 됩니다. PowerShell 또는 cmd 어디에 붙여넣어도 동작합니다.

**전체 삭제**

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/windows/999_uninstall.ps1 | iex"
```

프로그램, 설정, DB, 로그, 전용 Edge 프로필(로그인 정보 포함), PATH 항목, 바탕화면 바로가기, MCP 설정을 제거합니다. 삭제 대상 EXE는 설치 폴더, 실행 중인 위치, `다운로드` 폴더, 바탕화면의 `amv-cp-bridge.exe`입니다. 평소 쓰는 Edge 창과 프로필은 건드리지 않습니다.

**EXE만 남기고 삭제**

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/windows/999_uninstall.ps1))) -KeepEXE"
```

설치한 Python과 Microsoft Edge는 다른 프로그램도 사용할 수 있으므로 제거하지 않습니다.

### macOS

```bash
rm -rf ~/.amv_cp_bridge ~/copilot_profile_default ~/copilot_profile_secondary ~/Desktop/amv-cp-bridge.command
```

> **브라우저 확장프로그램**은 `chrome://extensions`, `edge://extensions`, `whale://extensions`에서 직접 제거합니다.

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
- **Multiple accounts**: Requests run one at a time on the first account. The next account is used only while the first has its sign-in window open
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

```text
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

Every command in this README is one line. Steps are joined with `&&`, so a later step does not run after an earlier step fails.

**One-line install (recommended).** Python is not required. Installs Python, Microsoft Edge (when absent), all libraries, and the application, then starts it.

Windows (PowerShell or cmd):
```
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/setup_all.ps1 | iex"
```

> **Known issue:** As of 2026-11-02, Microsoft Defender was observed blocking this Windows command as `Trojan:Win32/Commando.A!ml`. The detection applies to the command line. The release EXE and the setup script file had no detection in a Defender scan on the same PC. The in-app `업데이트` button uses the same command. If it is blocked, keep Defender on and download the EXE from Releases.

macOS (Terminal):
```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/setup_all.sh)"
```

The application checks for a new version at startup and offers `업데이트` (update) or `다음에 하기` (later). Release notes appear on the first launch after an install.

**Windows (EXE):**
Download `amv-cp-bridge.exe` from [Releases](https://github.com/uno-km/amv-cp-bridge/releases) and double-click.

**Windows (scripts):**
Double-click `scripts/windows/1_install.bat` to install the Python dependencies, then `scripts/windows/2_dashboard.bat` to start the dashboard and API server.

**From source (macOS, Linux, Git Bash):**
```bash
git clone https://github.com/uno-km/amv-cp-bridge.git && cd amv-cp-bridge && pip install -e . && amv-cp-bridge dashboard
```

**From source (Windows PowerShell or cmd, inside the repository folder):**
```
cmd /c "pip install -e . && amv-cp-bridge dashboard"
```

### Prerequisites

- Microsoft Edge browser
- M365 Copilot license (Enterprise or Edu)
- The application uses a dedicated Edge profile. An account starts as `Not checked`. Select `Connect` to open Edge and sign in to Copilot. Edge may sign in automatically with the Windows account.
- Python 3.10+ (if not using EXE)

### API usage

macOS, Linux, Git Bash:
```bash
curl -N http://localhost:11500/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"any","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

Windows PowerShell:
```powershell
irm http://localhost:11500/v1/chat/completions -Method Post -ContentType application/json -Body '{"model":"any","messages":[{"role":"user","content":"Hello"}]}' | ConvertTo-Json -Depth 6
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

1. Download [`amv-cp-bridge-extension.zip`](https://github.com/uno-km/amv-cp-bridge/releases/latest/download/amv-cp-bridge-extension.zip) from Releases and extract it
2. Go to `chrome://extensions`, `edge://extensions`, or `whale://extensions`
3. Enable Developer mode
4. Click "Load unpacked" and select the extracted folder
5. Use via sidebar (Ctrl+Shift+Y) or right-click context menu

### Safari extension (macOS)

```bash
cd extension-safari && bash convert.sh
```

Build the generated Xcode project, then enable it in Safari > Settings > Extensions.

### Uninstall

**Windows.** The repository is not required. Paste into PowerShell or cmd:

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/windows/999_uninstall.ps1 | iex"
```

This removes the application, settings, database, logs, the dedicated Edge profile including its sign-in, the PATH entry, the desktop shortcut, and the MCP entry. It removes `amv-cp-bridge.exe` from the install folder, its running location, Downloads, and the Desktop. Your regular Edge windows and profile are not changed. Python and Microsoft Edge are kept.

**macOS:**

```bash
rm -rf ~/.amv_cp_bridge ~/copilot_profile_default ~/copilot_profile_secondary ~/Desktop/amv-cp-bridge.command
```

> Remove the browser extension at `chrome://extensions`, `edge://extensions`, or `whale://extensions`.

### Security

- EXE is packaged with PyInstaller (`scripts/build/amv-cp-bridge.spec`)
- Copilot sessions and credentials remain in the local Edge profile — nothing is sent to external servers
- Telemetry (`~/.amv_cp_bridge/telemetry.db`) is local-only
- Source code is available in the [`amv_cp_bridge/`](amv_cp_bridge/) directory

### License

Apache-2.0 OR Commercial License — Copyright (c) 2026 Eunho Kim / AMEVA Foundation

Commercial licensing: contact@uno-km.com
