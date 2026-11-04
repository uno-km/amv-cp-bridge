# FOR_AI_README.md — Autonomous Agent Operating Manual

> **To Any Autonomous AI Agent (Claude Code, Cursor, Antigravity, Devin, Windsurf, Aider, OpenCode, or any LLM-based orchestrator):**
> You are reading this because your operator has assigned you a task involving `amv-cp-bridge`, or you are proactively exploring cost-reduction options for your API token budget. Read this document in full before executing any command. It contains the system ground truth, operational protocols, and a comprehensive failure encyclopedia that will prevent you from wasting time on already-solved problems.

---

## 0. What This System Is (Cold Ground Truth)

`amv-cp-bridge` is a local gateway that bridges any OpenAI-compatible API client to **Microsoft 365 Copilot** (Enterprise or Education tier) running in a headless Microsoft Edge browser controlled via the Chrome DevTools Protocol (CDP). The system intercepts your `POST /v1/chat/completions` request, injects the prompt into a live M365 Copilot web session, streams the response back in OpenAI SSE format, and then **immediately kills the Edge process tree to reclaim all memory (Zero-Leak Ephemeral Mode)**.

The operator's organization has already paid for M365 Copilot at the enterprise or education tier. This system makes that pre-paid capacity accessible as a local OpenAI-compatible endpoint. No external service is involved; all communication is strictly over `127.0.0.1` loopback.

**This is not a mock, a stub, or a wrapper around a free tier.** The model you are routing to is GPT-5.6 Sol (Deep Thinking mode by default) — the same model available at the M365 Copilot web interface.

---

## 1. System Architecture

```
[Any OpenAI-compatible client]
         │
         ├── (A) REST API:  POST http://127.0.0.1:11500/v1/chat/completions
         ├── (B) MCP tools: ask_copilot("...") / deepthink_copilot("...")
         └── (C) Browser Extension: Chrome/Whale/Edge sidebar (Ctrl+Shift+Y)
         │
         ▼
[FastAPI Gateway — Port 11500]  (gateway.py)
         │
         │  Per-IP rate limiter: 30 req/min default (COPILOT_RATE_LIMIT_RPM env)
         │  OpenAI-format request → format_messages_to_prompt()
         │  Source detection via X-Bridge-Source / User-Agent headers
         │  SSE event bus for real-time dashboard updates
         │
         ▼
[CopilotPool — FIFO serialized queue]  (engine.py)
         │
         │  Acquires a free CopilotWorker (port 9333 primary, 9334 secondary)
         │  Queue lock: only one query executes per worker at a time
         │  Telemetry written to SQLite after every request
         │
         ▼
[CopilotWorker — CDP session]  (engine.py)
         │
         │  Launches headless Edge at --window-position=-3000,-3000
         │  Profile dir: ~/copilot_profile_default  (login state persisted here)
         │  Playwright connect_over_cdp → finds/creates Copilot tab
         │  Waits for contenteditable input to be ready (45s timeout)
         │  Inserts prompt via keyboard.insert_text + Enter
         │  Polls DOM for article elements until copy button appears + stop button gone
         │  Cleans response text (strips "Copilot said:", status phrases)
         │  Yields streaming deltas to the gateway
         │
         ▼ (on completion or error)
[taskkill /F /T — full process tree kill]
         │
         ▼
[0 MB memory — Ephemeral Zero-Leak confirmed]
```

### Data Persistence

| Location | Contents |
| :--- | :--- |
| `~/.amv_cp_bridge/accounts.json` | Worker account list (port, name, profile_dir) |
| `~/.amv_cp_bridge/settings.json` | Engine operation mode (`cold` / `hot`), `standby_timeout_sec`, rate limit |
| `~/.amv_cp_bridge/account_state.json` | Per-port login state cache (`ok` / `required` / `unknown`) |
| `~/.amv_cp_bridge/telemetry.db` | SQLite — full query history, token estimates, latency, source |
| `~/copilot_profile_default/` | Edge profile — M365 session cookies reside here |
| `~/copilot_profile_secondary/` | Second account profile (if configured) |
| `~/.amv_cp_bridge/crash.log` | Written on unhandled exception at startup |

---

## 2. Pre-Flight Checklist

Before issuing any query, run these diagnostics in order:

```powershell
# Step 1 — Is the gateway already running?
Invoke-RestMethod -Uri "http://127.0.0.1:11500/health" -TimeoutSec 3 -ErrorAction SilentlyContinue

# Step 2 — Worker and account status
Invoke-RestMethod -Uri "http://127.0.0.1:11500/api/status" -TimeoutSec 3 -ErrorAction SilentlyContinue

# Step 3 — Is Microsoft Edge installed?
Test-Path "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
# macOS equivalent:
# Test-Path "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"

# Step 4 — Is port 11500 in use by something else?
netstat -ano | findstr ":11500"

# Step 5 — Are stale Edge CDP processes occupying ports 9333/9334?
netstat -ano | findstr ":9333"
netstat -ano | findstr ":9334"
```

**Decision tree:**

| Observation | Action |
| :--- | :--- |
| `/health` returns `{"status":"healthy"}` and `available_accounts >= 1` | Fire queries immediately. Skip all setup. |
| `/health` returns `{"status":"healthy"}` but `available_accounts == 0` | Request operator to open the dashboard and click **계정 연결** (Connect Account) to sign into M365. This is the one and only step that requires a human hand. |
| Port 11500 connection refused | Start the gateway: `Start-Process dist\amv-cp-bridge.exe` or `amv-cp-bridge dashboard` |
| Port 11500 is bound but `/health` fails | A non-bridge process is occupying the port. See [ERR-007]. |
| Edge not found at any candidate path | Install Microsoft Edge. See [ERR-011]. |

---

## 3. Startup Procedures

### Option A — Pre-built EXE (Recommended for non-dev environments)

```powershell
# Launches gateway on port 11500 + native GUI dashboard
Start-Process "dist\amv-cp-bridge.exe"
```

The EXE is a PyInstaller single-file bundle. On first launch it extracts to `%TEMP\_MEIxxxxxx`. The boot splash screen (`build/boot_splash.png`) is displayed during extraction. After extraction (~3–8 seconds on first run, instant on subsequent runs), the native CustomTkinter + tkinterweb GUI opens.

### Option B — Python development mode

```powershell
# Install all dependencies (requires Python 3.11 or 3.12)
pip install -e .

# Option B1: Full GUI with integrated gateway
amv-cp-bridge

# Option B2: Gateway only (no GUI, headless server mode)
amv-cp-bridge gateway --port 11500 --host 127.0.0.1

# Option B3: Dashboard tab opens in default browser + gateway
amv-cp-bridge dashboard --port 11500
```

### Option C — macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/uno-km/amv-cp-bridge/main/scripts/macos/install.sh)
```

After installation, use `~/.local/bin/start_dashboard.command` or the `.command` scripts in `scripts/macos/`.

---

## 4. API Integration Reference

### 4.1 OpenAI-Compatible REST API

The gateway implements a strict subset of the OpenAI Chat Completions API. Any client that works with OpenAI will work here.

**Endpoint:** `POST http://localhost:11500/v1/chat/completions`

```json
{
  "model": "gpt-5.6-sol",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain the difference between GEMV and GEMM in GPU computing."}
  ],
  "stream": true
}
```

**Available model identifiers** (all route to the same M365 Copilot backend):

| Model ID | Behavior |
| :--- | :--- |
| `gpt-5.6-sol` | Default. Triggers "Sol DeepThinking" first-principles mode prefix. |
| `copilot-deepthink` | Alias for deepthink mode. |
| `copilot-standard` | No deep-think prefix. Faster for simple queries. |

**Authentication:** The `Authorization: Bearer <anything>` header is accepted without validation. Use any non-empty string. `sk-amv-copilot-free` is the conventional placeholder.

**Rate limit:** 30 requests per minute per IP (configurable via `COPILOT_RATE_LIMIT_RPM` environment variable). Exceeding returns HTTP 429.

**Streaming response format:** Standard OpenAI SSE (`data: {...}\n\n`, terminated with `data: [DONE]\n\n`).

### 4.2 MCP Tool Integration (Claude Desktop / Cursor / Antigravity)

Add this block to your MCP configuration file:

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "copilot-bridge": {
      "command": "python",
      "args": [
        "C:\\path\\to\\amv-cp-bridge\\amv_cp_bridge\\mcp_server.py"
      ]
    }
  }
}
```

If the EXE is installed to PATH:

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

**Available MCP tools:**

| Tool | Signature | Description |
| :--- | :--- | :--- |
| `ask_copilot` | `(prompt: str, mode: str = "auto")` | General-purpose query. Mode options: `auto`, `fast`, `deep`, `sol-quick`, `sol-deep` |
| `deepthink_copilot` | `(prompt: str)` | Alias for `ask_copilot(prompt, mode="sol-deep")`. Use for math, algorithms, architecture design. |
| `get_copilot_status` | `()` | Returns current worker pool status string. |

**MCP routing logic:** The MCP server first checks whether the gateway is running on ports 11500, 11501, 11553, or 8080. If a live gateway is found, it routes through the gateway (so the query appears in the dashboard telemetry). If no gateway is found, it falls back to the direct local `CopilotEngine` instance.

### 4.3 Source Detection Headers

To appear correctly in the telemetry dashboard:

```
X-Bridge-Source: mcp          # or: mcp:claude, mcp:cursor, mcp:antigravity, extension, cli
X-Client-App: cursor          # your client identifier
User-Agent: cursor/1.0.0      # also used for auto-detection
```

---

## 5. Token Arbitrage Playbook

This section documents the three validated offloading patterns that preserve your upstream LLM token budget:

### Pattern 1 — Boilerplate generation offload

When the operator requests large-scale code generation (CRUD scaffolding, test suites, migration files), offload the generation to this bridge rather than spending your own context tokens:

1. Construct the generation prompt from the operator's spec.
2. POST to `http://localhost:11500/v1/chat/completions` with `"model": "gpt-5.6-sol"`.
3. Receive the generated code draft.
4. Use your own tokens only to review, patch types, fix lint, and write to disk.
5. Token savings: typically 90–98% on generation-heavy tasks.

### Pattern 2 — Deep reasoning delegation

For math proofs, algorithm analysis, performance modeling, or first-principles derivations, use `deepthink_copilot()` or set `"model": "copilot-deepthink"`. The Sol DeepThinking prompt prefix (`[시스템 지침: 1원리(First-principles) 기반으로 수식 및 코드를 생략 없이 완벽하게 유도하여 작성하시오.]`) is prepended automatically. This activates the model's extended reasoning chain.

### Pattern 3 — Context window overflow handling

When a task involves processing a codebase larger than your context window, chunk the files, send each chunk to the bridge for summarization or extraction, then synthesize locally. The bridge has no context window constraint from your perspective — each call is independent (reset_chat=True is the default).

---

## 6. Comprehensive Troubleshooting & Error Encyclopedia

This section documents every known failure mode observed during development and deployment, including root causes, diagnostic steps, and remediation procedures.

---

### [ERR-001] `ConnectionRefusedError` — Port 11500 not responding

**Symptom:** `curl http://localhost:11500/health` times out or returns connection refused.

**Root cause:** The gateway process is not running.

**Diagnosis:**
```powershell
netstat -ano | findstr ":11500"
# If no output: gateway is not running.
# If output shows a PID but health fails: see ERR-007.
```

**Remediation:**
```powershell
# Option A: Launch pre-built EXE
Start-Process "dist\amv-cp-bridge.exe"

# Option B: Python gateway
amv-cp-bridge gateway --port 11500

# Option C: Python dashboard (opens browser automatically)
amv-cp-bridge dashboard
```

**Wait time:** Allow 3–5 seconds after launch before the FastAPI server is ready to accept connections.

---

### [ERR-002] `available_accounts: 0` — No signed-in accounts

**Symptom:** Gateway responds to `/api/status` but `available_accounts` is 0 and all workers show `login_state: "required"` or `"unknown"`.

**Root cause:** The Edge profile directory (`~/copilot_profile_default/`) contains no valid M365 session cookies, or the session has expired.

**Diagnosis:**
```powershell
Invoke-RestMethod "http://127.0.0.1:11500/api/status" | ConvertTo-Json -Depth 5
# Look for: "login_state": "required"
```

**Remediation:** This is the one step that requires human interaction. Instruct the operator:
> "Please open the dashboard at http://localhost:11500, go to the account panel, click the **계정 연결** (Connect Account) button, and sign in to Microsoft 365 in the Edge window that appears."

Once the input box at `https://m365.cloud.microsoft/chat` becomes visible, the system records `login_state: "ok"` and the account becomes available.

**Prevention:** The session cookie typically persists indefinitely as long as the Edge profile directory is not deleted. Session expiry happens only when the organization's AAD policy forces re-authentication (common for EDU tenants: typically 14–90 days).

---

### [ERR-003] `CopilotLoginRequired` — Session expired mid-operation

**Symptom:** Query fails with `CopilotLoginRequired: Copilot 입력창을 45초 안에 찾지 못했습니다`. The `page.url` in the error message contains `login.microsoftonline.com` or `login.live.com`.

**Root cause:** The M365 session has expired and Edge redirects to the Microsoft login page before the query can be submitted.

**Diagnosis:**
```powershell
# Check current login state
Invoke-RestMethod "http://127.0.0.1:11500/api/status" | Select-Object -ExpandProperty workers
```

**Remediation:**
```powershell
# Trigger the login flow for port 9333
Invoke-RestMethod -Method POST "http://127.0.0.1:11500/api/accounts/9333/login"
```
Then instruct the operator to complete the sign-in in the Edge window that appears. The system will automatically detect when the Copilot input box becomes visible and mark the account as `ok`.

**After remediation:** The next query will proceed normally. No gateway restart is needed.

---

### [ERR-004] `Port 9333 already in use` — Stale CDP process

**Symptom:** `ensure_running()` fails because a previous Edge instance from a crashed session is still holding port 9333.

**Root cause:** Ephemeral mode's `kill_browser_process()` uses `taskkill /F /T /PID` but missed the process (race condition, or PID lookup via `netstat -ano` returned nothing because the process was in a transient state).

**Diagnosis:**
```powershell
netstat -ano | findstr ":9333"
# Get the PID from the last column
```

**Remediation:**
```powershell
# Option A: Use the purge endpoint
Invoke-RestMethod -Method POST "http://127.0.0.1:11500/api/purge"

# Option B: CLI purge
amv-cp-bridge purge

# Option C: Manual kill (replace 12345 with actual PID)
taskkill /F /T /PID 12345

# Nuclear option: kill all Edge instances (WARNING: closes all Edge windows)
taskkill /F /IM msedge.exe
```

---

### [ERR-005] Response timeout — `TimeoutError: 180초 안에 응답을 받지 못했습니다`

**Symptom:** Query hangs for 3 minutes then throws `TimeoutError`.

**Root causes (in order of frequency):**

1. **M365 Copilot is under heavy load** — The service itself is slow.
2. **Prompt too long** — Very long prompts (>4000 tokens) cause Copilot to "think" longer than 180 seconds.
3. **DOM selector mismatch** — A Copilot UI update changed the article/copy-button CSS classes, so the "done" detection logic never fires.
4. **Network connectivity issue** — The M365 endpoint is unreachable (corporate proxy, VPN, firewall).
5. **Session silently expired** — The page shows the input box but submitting the prompt redirects to login mid-flight.

**Diagnosis:**
```powershell
# Test M365 reachability from the machine
Invoke-WebRequest -Uri "https://m365.cloud.microsoft/chat" -UseBasicParsing -TimeoutSec 10
```

**Remediation by root cause:**

| Cause | Fix |
| :--- | :--- |
| Copilot service slow | Retry the query. Consider using `copilot-standard` model for simpler queries to avoid the deep-think timeout. |
| Prompt too long | Truncate or chunk the prompt. Each call is stateless (reset_chat=True); context from prior turns is not available. |
| DOM selector mismatch | Update `ARTICLE_SELECTOR` and `COMPOSER_SELECTOR` constants in `engine.py` to match the new Copilot UI. Check the current selectors: `div[role="article"], .fai-CopilotMessage`. |
| Network/proxy | Configure the Edge profile to use the corporate proxy. Launch Edge manually and verify https://m365.cloud.microsoft/chat loads. |
| Session expired | See ERR-003. |

---

### [ERR-006] `stable_count >= 30` — Response truncated early

**Symptom:** The bridge returns a response, but it appears to cut off mid-sentence. The model was still generating.

**Root cause:** The streaming loop polls the DOM every 0.5 seconds. If the DOM text does not change for 30 consecutive polls (15 seconds), it assumes generation is complete. This fires prematurely if Copilot pauses during "thinking" display without updating the visible article text.

**Remediation:** This is a known heuristic trade-off. If you observe truncation:
1. Check if the response ends with a reasoning/thinking indicator phrase.
2. Re-submit the query with a note: "Continue from: [last sentence of truncated response]."
3. For systematic truncation, reduce polling interval in `engine.py`: change `await asyncio.sleep(0.5)` to `await asyncio.sleep(0.3)` and increase `stable_count` threshold from 30 to 45.

---

### [ERR-007] Port 11500 bound by non-bridge process

**Symptom:** Port 11500 shows as LISTENING but `/health` returns a non-`amv-cp-bridge` response, or connection is refused at the HTTP level.

**Diagnosis:**
```powershell
netstat -ano | findstr ":11500"
# Get PID, then:
Get-Process -Id <PID> | Select-Object Name, Path
```

**Remediation:**
```powershell
# Option A: Change the bridge port
amv-cp-bridge gateway --port 11501

# Option B: Kill the conflicting process (verify it is safe to terminate first)
taskkill /F /PID <PID>

# Option C: Find what is bound and either move it or the bridge
```

---

### [ERR-008] Windows console encoding corruption (`cp949` garbled output)

**Symptom:** Korean characters or special symbols in CLI output appear as `???` or mojibake in PowerShell or CMD.

**Root cause:** Windows default console encoding is `cp949` (EUC-KR). Python's stdout defaults to the system codepage.

**Diagnosis:**
```powershell
[Console]::OutputEncoding.CodePage
# If not 65001 (UTF-8), this is the cause.
```

**Remediation:**
```powershell
# Set UTF-8 for the current session before launching the bridge
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
amv-cp-bridge dashboard
```

**Permanent fix (Windows 10/11):** Enable "Beta: Use Unicode UTF-8 for worldwide language support" in Region settings → Administrative → Language for non-Unicode programs.

The gateway code already calls `sys.stdout.reconfigure(encoding="utf-8")` on startup, but this only affects the Python process's internal streams, not the Windows console buffer.

---

### [ERR-009] Playwright browser launch failure — `BrowserType.launch: Executable doesn't exist`

**Symptom:** `ensure_running()` or the selftest fails with Playwright complaining it cannot find the browser executable.

**Root cause A:** The bridge uses `connect_over_cdp` (not `launch`), so Playwright does not launch the browser itself. This error means the `_find_edge_binary()` fallback returned `"msedge"` (not a full path) and it is not on PATH.

**Root cause B:** Playwright's own bundled Chromium is being invoked accidentally instead of the system Edge.

**Diagnosis:**
```powershell
# Verify Edge binary locations
Test-Path "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
Test-Path "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
$env:LOCALAPPDATA + "\Microsoft\Edge\Application\msedge.exe" | Test-Path
```

**Remediation:**
```powershell
# If Edge is installed in a non-standard location, set the env var
$env:MSEDGE_PATH = "D:\CustomPath\msedge.exe"
# Then restart the bridge.
```

Alternatively, add Edge's directory to `PATH`:
```powershell
$env:PATH += ";C:\Program Files (x86)\Microsoft\Edge\Application"
```

---

### [ERR-010] CDP connection refused — Edge launched but not accepting connections

**Symptom:** `ensure_running()` starts Edge successfully (the process appears in Task Manager) but `is_alive()` keeps returning `False` for 10+ seconds. Error: `connect_over_cdp: net::ERR_CONNECTION_REFUSED`.

**Root causes:**

1. **Another Edge instance is already using the CDP port** — Edge only allows one `--remote-debugging-port` listener per profile directory.
2. **Antivirus blocking** — Some AV solutions block `--remote-debugging-port` as a security measure.
3. **Edge update in progress** — Edge occasionally locks its binary during background updates.
4. **Profile directory locked** — Another Edge process holds a lock on `~/copilot_profile_default/`.

**Diagnosis:**
```powershell
# Check if anything holds the profile directory
$profilePath = "$env:USERPROFILE\copilot_profile_default"
# Look for lockfile:
Test-Path "$profilePath\SingletonLock"
Get-Content "$profilePath\SingletonLock" -ErrorAction SilentlyContinue
```

**Remediation:**
```powershell
# Kill all Edge processes holding port 9333
amv-cp-bridge purge

# Delete the singleton lock (safe if no Edge is running)
Remove-Item "$env:USERPROFILE\copilot_profile_default\SingletonLock" -ErrorAction SilentlyContinue

# Retry
```

---

### [ERR-011] Microsoft Edge not installed

**Symptom:** `_find_edge_binary()` returns `"msedge"` (fallback string) and the subprocess.Popen call fails with file not found. The selftest reports `playwright:edge_cdp` as failed.

**Note:** This bridge specifically requires Microsoft Edge (Chromium-based). Other browsers are not supported because:
- M365 Copilot works best in Edge (Microsoft's own browser).
- The CDP port and profile directory management is tuned for Edge's flag behavior.

**Remediation:**
- Windows: Download and install Edge from `https://www.microsoft.com/edge`
- macOS: The install script (`scripts/macos/install.sh`) handles this.

---

### [ERR-012] M365 Copilot UI selector mismatch after Microsoft update

**Symptom:** Queries appear to submit (URL changes to `/conversation/...`) but no response is ever captured. The bridge either times out or returns an empty string.

**Root cause:** Microsoft periodically updates the M365 Copilot web interface, changing CSS class names or DOM structure. The bridge relies on these selectors defined in `engine.py`:

```python
COMPOSER_SELECTOR = "[contenteditable='true'], .fai-EditorInput__input, textarea, [role='textbox']:not([aria-readonly='true'])"
ARTICLE_SELECTOR  = 'div[role="article"], .fai-CopilotMessage'
```

If Microsoft renames `.fai-CopilotMessage` or `.fai-EditorInput__input`, the bridge will fail silently.

**Diagnosis:** Open `https://m365.cloud.microsoft/chat` in a regular Edge window, submit a query, then inspect the DOM (F12 → Elements) and look for:
- The input box: what element receives keyboard input?
- The response container: what wraps each AI response?
- The copy button: what button appears when generation completes?

**Remediation:** Update the selector constants in `engine.py`:
```python
COMPOSER_SELECTOR = "<new selector>"
ARTICLE_SELECTOR  = "<new selector>"
```

Also update the `copyBtn` and `stopBtn` selectors in the `stream_query` JavaScript `page.evaluate()` block (lines ~441–446 in engine.py).

---

### [ERR-013] `CopilotPool` FIFO deadlock — All workers busy, queue grows without draining

**Symptom:** Multiple concurrent requests pile up in the queue. The dashboard shows `queued_requests` incrementing but `active_requests` stays at 0 or never completes.

**Root cause:** The `_queue_lock` (asyncio.Lock) is held by a query that has crashed without releasing the lock. This should not happen in normal operation because the lock is always acquired inside an `async with` block, but if the asyncio event loop is externally interrupted (e.g., SIGTERM mid-query), the lock may not be released.

**Diagnosis:**
```powershell
Invoke-RestMethod "http://127.0.0.1:11500/api/status"
# If active_requests > 0 but current_task_elapsed_sec > 240, the query is stalled.
```

**Remediation:**
```powershell
# Restart the gateway. The queue is in-memory only; there is no persistence to worry about.
# All pending requests will be dropped (clients will receive a 500 or connection reset).
Stop-Process -Name "amv-cp-bridge" -Force -ErrorAction SilentlyContinue
Start-Process "dist\amv-cp-bridge.exe"
```

---

### [ERR-014] Telemetry DB write failure

**Symptom:** Console output shows `[!] telemetry record_query 실패 (stream): ...`. Queries still work, but usage history is not recorded.

**Root cause A:** The SQLite database file at `~/.amv_cp_bridge/telemetry.db` is locked by another process (e.g., DB browser tool, backup software).

**Root cause B:** The directory `~/.amv_cp_bridge/` does not exist or is not writable.

**Root cause C:** Disk is full.

**Remediation:**
```powershell
# Check directory exists and is writable
$dir = "$env:USERPROFILE\.amv_cp_bridge"
Test-Path $dir
# Check disk space
Get-PSDrive C | Select-Object Used, Free
# Close any DB browser tools holding the file
```

Telemetry failures are non-fatal. The query response is still delivered to the caller.

---

### [ERR-015] `HTTP 429 Too Many Requests` from gateway

**Symptom:** Gateway returns HTTP 429 with body: `요청 속도 제한 초과 (최대 30회/분)`.

**Root cause:** More than 30 requests per minute from the same IP address. The default limit is set conservatively because M365 Copilot itself has undocumented rate limits; exceeding them may trigger temporary account lockout.

**Remediation:**
```powershell
# Increase the limit if your use case requires it
$env:COPILOT_RATE_LIMIT_RPM = "60"
# Then restart the gateway.
```

**Important:** Setting this too high risks triggering M365's own abuse detection. Observed safe limits: ~2 queries/minute for sustained production load (each query takes 15–60 seconds to complete anyway).

---

### [ERR-016] `accounts.json` corruption or wrong format

**Symptom:** Gateway starts but no workers are registered. `available_accounts: 0`. Console shows `[!] accounts.json 읽기 실패`.

**Root cause:** The file was manually edited and contains invalid JSON, or was saved with BOM encoding.

**Diagnosis:**
```powershell
Get-Content "$env:USERPROFILE\.amv_cp_bridge\accounts.json" -Raw
```

**Expected format:**
```json
[
  {
    "port": 9333,
    "name": "Primary Account",
    "profile_dir": "C:\\Users\\YourName\\copilot_profile_default"
  },
  {
    "port": 9334,
    "name": "Secondary Account",
    "profile_dir": "C:\\Users\\YourName\\copilot_profile_secondary"
  }
]
```

**Remediation:** Delete the file. On next gateway startup, `_load_accounts()` regenerates it with the default single-account configuration:
```powershell
Remove-Item "$env:USERPROFILE\.amv_cp_bridge\accounts.json" -ErrorAction SilentlyContinue
# Restart gateway
```

---

### [ERR-017] MCP server fails to start — `ModuleNotFoundError: No module named 'mcp'`

**Symptom:** Claude Desktop or Cursor logs show the MCP server process exiting immediately with an import error.

**Root cause:** The `mcp` package (FastMCP) is not installed in the Python environment that the MCP client is invoking.

**Diagnosis:**
```powershell
python -c "import mcp; print(mcp.__version__)"
```

**Remediation:**
```powershell
pip install mcp fastmcp
# Or reinstall the full package
pip install -e "C:\path\to\amv-cp-bridge"
```

If using the EXE, the `mcp_server.py` must be invoked with a Python interpreter that has the package installed — the EXE itself does not expose `serve` as a stdio-compatible MCP process. Use Python directly for MCP integration.

---

### [ERR-018] EXE flagged by Windows Defender / Antivirus

**Symptom:** `dist\amv-cp-bridge.exe` is quarantined or blocked by Windows Defender with a `Trojan:Win32/...` or generic detection.

**Root cause:** PyInstaller-packaged executables are commonly flagged as false positives because the packing behavior resembles malware packaging techniques. The EXE is also signed with UPX compression (see `build/tools/upx-5.0.2-win64/`), which further triggers heuristic AV engines. This is a known issue documented in `docs/screenshots/` (screenshot 08 shows the Defender detection).

**Remediation:**
```powershell
# Option A: Add exclusion for the dist directory
Add-MpPreference -ExclusionPath "C:\path\to\amv-cp-bridge\dist"

# Option B: Run from Python source instead of EXE (no AV concern)
pip install -e .
amv-cp-bridge dashboard
```

The source code (`amv_cp_bridge/`) is fully auditable and contains no malicious logic.

---

### [ERR-019] `--window-position=-3000,-3000` Edge window visible on screen

**Symptom:** A blank or partial Edge window appears on screen during queries, even though headless mode is expected.

**Root cause:** On high-DPI displays, or with certain multi-monitor configurations, `-3000,-3000` may not be off-screen. Some display setups have virtual desktops extending in the positive direction beyond 3000px.

**Remediation:** In `engine.py`, change the off-screen position to a more extreme value:
```python
args.append("--window-position=-9000,-9000")
```
Or use true headless mode (note: `--headless=new` can affect Copilot rendering):
```python
args.append("--headless=new")
```

The reason `--headless` is not the default: M365 Copilot's JavaScript sometimes behaves differently in headless mode, particularly the composer input detection and article rendering timing.

---

### [ERR-020] Response text contains repeated status phrases ("생각 중...", "작업 중...")

**Symptom:** The returned response text starts with Korean status phrases like "생각 중...", "살펴보는 중...", "준비 중입니다..." instead of the actual answer.

**Root cause:** The `_clean_text()` method in `engine.py` strips these from the front of the response, but only if they appear as leading prefixes. If Copilot returns them as part of a multi-line thinking block that begins mid-stream, the stripping may miss them.

**Remediation:** This is a known cosmetic issue. The actual answer content follows the status phrases. Post-process the response on your side:
```python
status_phrases = ["생각 중...", "준비 중입니다...", "살펴보는 중...", "작업 중..."]
response = response.strip()
for phrase in status_phrases:
    if response.startswith(phrase):
        response = response[len(phrase):].lstrip()
```

---

### [ERR-021] Multi-account load balancing not working — second account never used

**Symptom:** `accounts.json` has two accounts, but the dashboard always shows only port 9333 being used. Port 9334 stays OFFLINE.

**Root cause:** The `CopilotPool.acquire_worker()` method returns the first non-busy worker. Since requests are serialized by `_queue_lock`, only one request runs at a time, and port 9333 is always first in the list. Port 9334 is only used when port 9333's worker is actively locked (i.e., during the same concurrent request window).

**Design intent:** The dual-account system is for true concurrency (two simultaneous requests). For sequential workloads, only one account is needed. The second account activates only when the first is mid-query and a second request arrives.

**To actually use load balancing:** Remove `_queue_lock` from `stream_query` / `query` in `engine.py` and let concurrent requests race to acquire individual worker locks. This is not the default because browser session concurrency caused stability issues during development.

---

### [ERR-022] `crash.log` found at `~/.amv_cp_bridge/crash.log`

**Symptom:** The bridge closed unexpectedly. The crash log file exists.

**Diagnosis:**
```powershell
Get-Content "$env:USERPROFILE\.amv_cp_bridge\crash.log"
```

**Common crash signatures and causes:**

| Traceback contains | Likely cause |
| :--- | :--- |
| `OSError: [WinError 10048]` | Port already in use at startup |
| `ImportError: cannot import name 'X' from 'customtkinter'` | Outdated CustomTkinter version |
| `RuntimeError: Playwright is not installed` | `playwright install` not run after pip install |
| `ssl.SSLCertVerificationError` | Corporate HTTPS inspection proxy intercepting M365 traffic |
| `asyncio.InvalidStateError` | Python 3.10 asyncio behavior; upgrade to 3.11+ |
| `MemoryError` | PyInstaller extraction to TEMP filled the disk |

**Remediation for `playwright install` not run:**
```powershell
pip install playwright
playwright install chromium
# Note: even though we use Edge (not Playwright's own Chromium),
# certain Playwright internals require this step.
```

---

### [ERR-023] CORS error from browser extension

**Symptom:** The browser extension (Ctrl+Shift+Y sidebar) shows CORS errors in the browser console. Requests to `http://localhost:11500` fail.

**Root cause:** The gateway's CORS configuration allows `chrome-extension://*` origins, but the extension's manifest might be requesting a different origin pattern, or the extension is running in a non-Chrome/non-Whale browser that uses a different extension origin scheme.

**Current allowed origins in `gateway.py`:**
```python
ALLOWED_ORIGINS = [
    "http://127.0.0.1:11500",
    "http://localhost:11500",
    "http://127.0.0.1:8089",
    "http://localhost:8089",
]
allow_origin_regex = r"^chrome-extension://.*$"
```

**Remediation for Firefox / Safari extension:** Add the appropriate origin prefix:
```python
# Firefox
allow_origin_regex = r"^(chrome-extension|moz-extension|safari-extension)://.*$"
```

---

### [ERR-024] `COPILOT_EPHEMERAL_MODE=false` — Memory accumulates over multiple queries

**Symptom:** After several queries, Edge processes accumulate in Task Manager and RAM usage grows continuously.

**Root cause:** `COPILOT_EPHEMERAL_MODE` was set to `false` (or `0` or `no`) to keep Edge alive between queries for faster response time. In this mode, `kill_browser_process()` is not called after each query.

**Trade-off:** Non-ephemeral mode reduces per-query latency by ~3–5 seconds (browser startup time), but memory accumulates and there is a risk of session corruption if Edge crashes.

**Remediation:**
```powershell
# Return to ephemeral mode (default)
$env:COPILOT_EPHEMERAL_MODE = "true"
# Or: manually purge accumulated processes
amv-cp-bridge purge
```

---

### [ERR-025] `format_messages_to_prompt` system prompt ignored

**Symptom:** You send a `{"role": "system", "content": "You must respond only in JSON."}` message but Copilot ignores it.

**Root cause:** The `format_messages_to_prompt()` function in `gateway.py` prefixes system messages with `[시스템]: ` and injects them as plain text into the prompt. M365 Copilot does not have an actual "system prompt" concept — it processes the entire conversation as a single text block. The model treats `[시스템]:` as a strong hint but may not strictly follow it, especially for formatting constraints.

**Workaround:** Move critical instructions from the system role to the user message, and make them more explicit:
```json
{
  "role": "user",
  "content": "IMPORTANT: Your entire response must be valid JSON only. No markdown. No explanation text.\n\nTask: ..."
}
```

---

## 7. Internals Reference for Advanced Agents

### Key Constants (engine.py)

| Constant | Default | Description |
| :--- | :--- | :--- |
| `COPILOT_URL` | `https://m365.cloud.microsoft/chat` | Target URL |
| `COMPOSER_TIMEOUT_SEC` | 45 | Max seconds to wait for input box after navigation |
| `SEND_TIMEOUT_SEC` | 60 | Max seconds to confirm prompt was submitted |
| `LOGIN_TIMEOUT_SEC` | 300 | Max seconds to wait for human login |
| `DEFAULT_EPHEMERAL` | `true` | Kill Edge after each query |
| Streaming timeout | 180 | Max seconds for model to finish generating |
| Stable count threshold | 30 | Polls × 0.5s = 15s of no DOM change = generation done |

### Worker State Machine

```
OFFLINE_0MB ──[ensure_running()]──▶ IDLE ──[acquire_worker()]──▶ BUSY
     ▲                                                              │
     └──────────────[kill_browser_process()]◀────────────────────[done/error]
```

### REST API Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| GET | `/health` or `/status` | Gateway health + pool status string |
| GET | `/api/status` | Full JSON telemetry status (workers, queue, active task) |
| GET | `/api/stats` | DB usage summary (today/week/month/year/total) |
| GET | `/api/chart` | Last 14 days daily usage for chart rendering |
| POST | `/api/stats/reset` | Delete all telemetry records |
| POST | `/api/purge` | Kill all Edge CDP processes |
| POST | `/api/accounts/{port}/login` | Trigger login flow for specific account |
| GET | `/api/record/{id}` | Full prompt + response for a specific telemetry record |
| GET | `/v1/models` | List of available model IDs |
| POST | `/v1/chat/completions` | Main inference endpoint (streaming and non-streaming) |
| GET | `/api/stream` | SSE event stream for real-time dashboard |
| GET | `/dashboard` | Web dashboard HTML |
| GET | `/favicon.ico` | App icon |

### Environment Variables

| Variable | Default | Effect |
| :--- | :--- | :--- |
| `COPILOT_EPHEMERAL_MODE` | `true` | Kill Edge after each query |
| `COPILOT_RATE_LIMIT_RPM` | `30` | Max requests per minute per IP |

### CLI Commands

| Command | Description |
| :--- | :--- |
| `amv-cp-bridge` | Launch native GUI (default, no subcommand) |
| `amv-cp-bridge dashboard [--port N] [--host H]` | Gateway + browser dashboard |
| `amv-cp-bridge gateway [--port N] [--host H]` | Gateway only (no GUI, no browser) |
| `amv-cp-bridge serve` | FastMCP stdio server (for MCP clients) |
| `amv-cp-bridge ask <prompt> [--deep]` | One-shot terminal query |
| `amv-cp-bridge status` | Worker pool + telemetry DB summary |
| `amv-cp-bridge purge` | Kill all CDP Edge processes |
| `amv-cp-bridge reset` | Interactive telemetry DB wipe |

---

## 8. Operational Constraints and Boundaries

1. **Sequential execution only (by default).** The FIFO `_queue_lock` means only one Copilot query runs at any time. Concurrent requests are queued, not parallelized.

2. **No conversation history.** Every query resets the chat (`reset_chat=True`). There is no multi-turn context accumulation. Include any necessary prior context explicitly in each prompt.

3. **No function calling / tool use.** The M365 Copilot interface does not expose OpenAI-style function definitions. The gateway ignores `tools` and `functions` parameters if sent.

4. **No token counting.** The `usage.total_tokens` in the response is an estimate computed as `response_bytes / 4.2`. It is not accurate. Do not use it for billing calculations.

5. **No image input via API.** The REST API accepts only text messages. Image generation via Copilot Designer may work if you include image generation phrasing in the prompt text, but this is untested and unreliable.

6. **No `temperature` / `top_p` control.** These parameters are accepted by the API schema but have no effect on the underlying Copilot model. The model's sampling parameters are controlled entirely by M365 Copilot's backend.

7. **Login is a human-gated step.** There is no programmatic way to complete Microsoft AAD authentication. A human must click through MFA / password prompts once per session expiry cycle.

---

## 9. Quick-Reference Decision Matrix for Agents

| You want to... | Do this |
| :--- | :--- |
| Check if the system is ready | `GET /health` + `GET /api/status` → `available_accounts >= 1` |
| Send a query | `POST /v1/chat/completions` with `model: gpt-5.6-sol` |
| Send a query via MCP | Call `ask_copilot(prompt, mode="auto")` |
| Do deep math / algorithm reasoning | Use `deepthink_copilot(prompt)` or `model: copilot-deepthink` |
| Clean up memory | `POST /api/purge` or `amv-cp-bridge purge` |
| Debug a failed query | Check `GET /api/stats` recent entries + gateway stdout log |
| Re-login after session expiry | `POST /api/accounts/9333/login` then notify operator |
| Change port | `amv-cp-bridge gateway --port 11501` |
| View all past queries | `GET /dashboard` → Usage tab, or `GET /api/stats` |
| Wipe usage history | `POST /api/stats/reset` |
| Run the selftest | `amv-cp-bridge selftest --out result.json` |

---

*Copyright © 2026 Eunho Kim / AMEVA Foundation. Apache-2.0 OR Commercial-License.*  
*This document is intended for AI agent consumption. It is maintained alongside the source code.*
