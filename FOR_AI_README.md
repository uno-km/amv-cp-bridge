# FOR_AI_README.md — Autonomous Agent Setup & Operating Manual (`amv-cp-bridge`)

> **To Any Autonomous AI Agent (Claude Code, Cursor, Antigravity, Codex, Devin, Windsurf, Aider, OpenCode, or any LLM orchestrator):**
> If a developer hands you `https://github.com/uno-km/amv-cp-bridge` and asks you to install, configure, integrate, or troubleshoot `amv-cp-bridge`, follow this manual sequentially. Every branch name, URL, port, API schema, and troubleshooting rule below is verified against the current codebase (`v1.4.1`).

---

## 0. Ground Truth Summary

`amv-cp-bridge` is a local OpenAI-compatible REST gateway (`http://127.0.0.1:11500`), FastMCP stdio server, native desktop GUI, and browser sidebar extension that bridges local developer tools to **Microsoft 365 Copilot (Enterprise or Education)** via isolated Microsoft Edge Chrome DevTools Protocol (CDP) profiles (`9333+`).

### Key Operational Invariants
1. **Default Git Branch is `master` (not `main`)**: Raw installer URLs use `https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/...`.
2. **Uses Installed Microsoft Edge — Do NOT Download Playwright Browsers**: Connects to system-installed Microsoft Edge (or Chrome fallback per account) via `--remote-debugging-port` and `playwright.chromium.connect_over_cdp`. **Never run `playwright install`.**
3. **Coexistence with `amv-gn-bridge`**:
   - `amv-cp-bridge` (M365 Copilot): Gateway `:11500`, CDP ports `9333–9336`, state `~/.amv_cp_bridge/`.
   - `amv-gn-bridge` (Google Gemini): Gateway `:11501`, CDP ports `9337+`, state `~/.amv_gn_bridge/`.
   - Both bridges operate concurrently without port or profile conflicts.
4. **Strict FIFO Queue & Multi-Account Parallel Dispatch**:
   - Simultaneous requests spread immediately across distinct idle signed-in workers.
   - Requests exceeding available workers wait in strict FIFO ticket order (`_wait_tickets` in `CopilotPool.acquire_worker()`), accurately separated into `queued` vs `running` status counters.
5. **Session Bloat Prevention & Single-Tab Enforcement**:
   - Before Edge launch, `_sanitize_profile_exit_type()` writes `exit_type="Normal"` and `session.restore_on_startup=5`, and `_prune_stale_session_files()` removes accumulated `Default/Sessions/Tabs_*` and `Session_*` files while preserving M365 login cookies and preferences.
   - `connect()` trims extra pages down to 1 tab; `verify_login()` reuses the cold-boot startup tab; `hot` mode recycles renderer tabs every `COPILOT_TAB_RECYCLE_INTERVAL` (default `15`) requests.
   - `open_login()` keeps an already signed-in browser window open until closed by the user or timeout expiry.
6. **MCP Double-Launch Guard & 360s Default Timeout**:
   - `mcp_server.py` routes through a running `:11500` gateway with `COPILOT_MCP_TIMEOUT_SEC` (default `360s`).
   - It falls back to direct local `engine` execution **only** on `ConnectionRefusedError` (gateway down). On HTTP errors or timeouts, it returns an explicit error instead of launching a colliding local Edge instance on the same profile.

---

## 1. Zero-to-Working Autonomous Installation Playbook

Execute these steps in order when asked to install and set up `amv-cp-bridge` on a fresh machine.

### Step 1 — Pre-Flight Diagnostics

**Windows (PowerShell):**
```powershell
try { Invoke-RestMethod "http://127.0.0.1:11500/health" -TimeoutSec 2 } catch { "NOT_RUNNING" }
Test-Path "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

**macOS (Bash):**
```bash
curl -sf --max-time 2 http://127.0.0.1:11500/health || echo "NOT_RUNNING"
test -d "/Applications/Microsoft Edge.app" && echo "EDGE_OK" || echo "EDGE_MISSING"
```

If `/health` returns `{"gateway": "amv-cp-bridge", ...}` and `available_accounts >= 1` on `/api/status`, skip directly to Step 5 (Integration).

### Step 2 — Install `amv-cp-bridge`

- **Option A — Windows One-Liner Installer (EXE + dependencies):**
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/setup_all.ps1 | iex"
  ```
  *(If Windows Defender flags `irm | iex`, download `amv-cp-bridge.exe` directly from `https://github.com/uno-km/amv-cp-bridge/releases/latest/download/amv-cp-bridge.exe`.)*

- **Option B — Python Editable Install (recommended for developers & MCP):**
  ```bash
  git clone https://github.com/uno-km/amv-cp-bridge.git
  cd amv-cp-bridge
  python -m pip install -e .
  ```

- **Option C — macOS One-Liner Installer:**
  ```bash
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/master/scripts/setup_all.sh)"
  ```

### Step 3 — Start the `:11500` Gateway

- **Headless gateway only (recommended for automation/agents):**
  - Windows (Python): `Start-Process "python" -ArgumentList "-m","amv_cp_bridge.cli","gateway","--port","11500" -WindowStyle Hidden`
  - Windows (EXE): `Start-Process "amv-cp-bridge.exe" -ArgumentList "gateway","--port","11500" -WindowStyle Hidden`
  - macOS: `nohup ~/.amv_cp_bridge/start.sh gateway --port 11500 >/dev/null 2>&1 &`
- **Desktop GUI + gateway:** run `amv-cp-bridge` (or `amv-cp-bridge.exe`) with no arguments.

Wait 3–5 seconds and verify:
```bash
curl -sf http://127.0.0.1:11500/health
curl -sf http://127.0.0.1:11500/api/status
```

### Step 4 — Human-in-the-Loop M365 Account Sign-In

1. Inspect `workers` in `GET /api/status`.
2. If all workers show `login_state: "unknown"` or `"required"`, trigger the login window:
   ```bash
   curl -sf -X POST http://127.0.0.1:11500/api/accounts/9333/login
   ```
   *(Or instruct the user to open `http://127.0.0.1:11500/dashboard` and click **Connect Account**.)*
3. Once the user finishes signing in to `https://m365.cloud.microsoft/chat`, verify live status:
   ```bash
   curl -sf -X POST http://127.0.0.1:11500/api/accounts/9333/verify
   ```
   Confirm `login_state == "ok"`.

### Step 5 — Wire Up MCP (Optional — When Asked to Connect to IDE/Agent)

Register in `claude_desktop_config.json`, Cursor MCP settings, or Antigravity `mcp_config.json`:

- Using `amv-cp-bridge` on `PATH`:
  ```json
  {
    "mcpServers": {
      "copilot-bridge": {
        "command": "amv-cp-bridge",
        "args": ["serve"]
      }
    }
  }
  ```
- Using explicit Python executable (recommended on Windows to prevent duplicate/stale MCP processes):
  ```json
  {
    "mcpServers": {
      "copilot-bridge": {
        "command": "python",
        "args": ["-m", "amv_cp_bridge.cli", "serve"]
      }
    }
  }
  ```

> **Important:** Register **only one** MCP entry for `amv-cp-bridge` per IDE config to avoid spawning redundant `mcp_server.py` processes.

---

## 2. System Architecture & Persistent Files

```text
[OpenAI SDK Client / IDE MCP Client / Browser Extension]
         │
         ├── REST API:  POST http://127.0.0.1:11500/v1/chat/completions
         │              POST http://127.0.0.1:11500/v1/images/generations
         ├── FastMCP:   ask_copilot / deepthink_copilot / get_copilot_status
         └── Extension: Chrome / Edge / Whale / Safari Side Panel (Ctrl+Shift+Y)
         │
         ▼
[FastAPI Gateway — Port 11500] (amv_cp_bridge/gateway.py)
         │  • Per-IP rate limiter: 30 req/min default (COPILOT_RATE_LIMIT_RPM)
         │  • Source attribution via X-Bridge-Source / X-Client-App / User-Agent
         ▼
[CopilotPool — Parallel Dispatch & Strict FIFO Queue] (amv_cp_bridge/engine.py)
         │  • Immediate dispatch across idle signed-in workers
         │  • FIFO ticket queue (_wait_tickets) when all workers are busy
         │  • Accurate queued vs running counters & SQLite WAL telemetry
         ▼
[CopilotWorker — CDP Port 9333, 9334, ...] (amv_cp_bridge/engine.py)
         │  • Dedicated Edge profile dir per account
         │  • restore_on_startup=5 + stale Tabs_*/Session_* pruning (cookies preserved)
         │  • Single-tab enforcement + 15-request hot-mode tab recycling
         │  • Cold mode: full process tree teardown after query; Hot mode: standby countdown
```

| Path | Contents |
| :--- | :--- |
| `~/.amv_cp_bridge/accounts.json` | Worker account list (`port`, `name`, `profile_dir`, optional `browser`, `email`) |
| `~/.amv_cp_bridge/settings.json` | Engine mode (`"cold"` / `"hot"`), `standby_timeout_sec`, rate limit |
| `~/.amv_cp_bridge/account_state.json` | Per-port login state cache (`"ok"`, `"required"`, `"unknown"`) |
| `~/.amv_cp_bridge/account_meta.json` | Per-port identity and verification metadata |
| `~/.amv_cp_bridge/telemetry.db` | SQLite WAL query history, token estimates, latency, and source attribution |
| `~/.amv_cp_bridge/temp_uploads/` | Temporary directory for decoded base64 vision/reference attachments (auto-cleaned) |

---

## 3. REST API Contract (`http://127.0.0.1:11500`)

### 3.1 Chat & Multimodal Vision (`POST /v1/chat/completions`)

```json
{
  "model": "gpt-5.6-sol",
  "messages": [
    {"role": "system", "content": "You are a concise systems engineer."},
    {"role": "user", "content": "Compare epoll and io_uring in 5 bullet points."}
  ],
  "stream": true
}
```

- **Model IDs**: `gpt-5.6-sol` (default), `copilot-deepthink`, `copilot-standard`, `copilot-fast`, `copilot-auto`.
- **Authentication**: Any non-empty `Authorization: Bearer <token>` header is accepted (or omitted).
- **Multimodal attachments**: Pass OpenAI `content` arrays containing `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}` or `{"type": "file_path", "path": "..."}`.
- **Structured Errors**:
  - `401 Unauthorized` (`authentication_error` / `session_expired`): Entra ID / M365 session expired (fast-fail ~1.5s). Prompt user to re-authenticate via `POST /api/accounts/{port}/login`.
  - `429 Too Many Requests`: Rate limit exceeded (`COPILOT_RATE_LIMIT_RPM`) or upstream quota limit.

### 3.2 Native Image Generation (`POST /v1/images/generations`)

```json
{
  "prompt": "A clean architectural diagram of a local multi-worker gateway",
  "model": "copilot-image",
  "reference_images": [
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."
  ]
}
```

Extracts generated image bytes (`data:`/`blob:`/`https:`), filters out reference copies via SHA-256 and dimensions, and maps policy refusals to HTTP `422` and quota limits to HTTP `429`.

### 3.3 Management Endpoints

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/health` | Health check (`gateway: "amv-cp-bridge"`, `version`) |
| `GET` | `/api/status` | Live workers, `available_accounts`, `total_accounts`, queue status (`queued` vs `running`), settings, telemetry |
| `GET` / `POST` / `DELETE` | `/api/accounts`, `/api/accounts/{port}` | List, add, or remove accounts |
| `POST` | `/api/accounts/{port}/login` | Open visible Edge window for sign-in (stays open until user closes if already signed in) |
| `POST` | `/api/accounts/{port}/verify` | Live verification of single account (reuses cold-boot tab) |
| `POST` | `/api/accounts/verify` | Sequential verification of all accounts |
| `POST` | `/api/accounts/{port}/close` | Terminate browser process tree for one account |
| `POST` | `/api/purge` | Terminate all idle Edge CDP process trees |
| `GET` / `POST` | `/api/settings` | Inspect or update `mode` (`"cold"` / `"hot"`) and `standby_timeout_sec` |
| `GET` / `POST` | `/api/update/check`, `/api/update/apply` | Check GitHub Releases and apply SHA-256 verified EXE hot-swap update |

---

## 4. FastMCP Tools & Environment Variables

| Tool | Signature | Behavior |
| :--- | :--- | :--- |
| `ask_copilot` | `(prompt: str, mode: str = "auto") -> str` | `mode`: `"auto"`, `"fast"`, `"deep"`, `"sol-quick"`, `"sol-deep"` |
| `deepthink_copilot` | `(prompt: str) -> str` | Alias for `ask_copilot(prompt, mode="sol-deep")` |
| `get_copilot_status` | `() -> str` | Returns current worker pool status summary |

| Env Var | Default | Purpose |
| :--- | :--- | :--- |
| `COPILOT_MCP_TIMEOUT_SEC` | `360` | HTTP timeout (seconds) for MCP requests to `:11500` |
| `COPILOT_RATE_LIMIT_RPM` | `30` | Per-IP requests per minute limit on `:11500` |
| `COPILOT_TAB_RECYCLE_INTERVAL` | `15` | Requests per worker before recycling renderer tab in `hot` mode |

---

## 5. Troubleshooting Quick Reference

| Symptom | Root Cause | Remediation |
| :--- | :--- | :--- |
| `ConnectionRefusedError` on `:11500` | Gateway not running | Start `amv-cp-bridge gateway --port 11500` (or `amv-cp-bridge.exe`) and wait 3–5s. |
| `401 Unauthorized` / `session_expired` / `available_accounts == 0` | M365 or Entra ID session expired or uninitialized | Call `POST /api/accounts/{port}/login` and ask user to sign in via the visible Edge window. |
| `Port 9333 already in use` | Stale Edge process holding CDP port | Call `POST /api/purge` or run `amv-cp-bridge purge`. |
| MCP returns timeout error without fallback | Gateway is alive and still processing a slow/queued request (`360s` timeout) | Increase `COPILOT_MCP_TIMEOUT_SEC` if needed; double-launch guard intentionally prevents colliding Edge launches. |
| Slow startup or high RAM on old profiles | Legacy `Default/Sessions/Tabs_*` accumulation | Automatic in `v1.4.1+` on next launch (`_prune_stale_session_files` + `restore_on_startup=5`). |

---

## 6. Mandatory Rules for AI Agents

1. **Never spawn `msedge.exe` directly against `~/.amv_cp_bridge` or `copilot_profile_*` directories.** Always route through `http://127.0.0.1:11500` or the MCP tools.
2. **Never run `playwright install`.** System Microsoft Edge is used directly over CDP.
3. **Never commit personal emails, company/tenant domains, cookies, or profile directories** into any repository.
4. **Keep MCP registration singular** (one `copilot-bridge` entry per IDE config) to avoid redundant idle MCP subprocesses.

---

*Copyright © 2026 Eunho Kim / AMEVA Foundation. SPDX-License-Identifier: Apache-2.0 OR Commercial-License.*
