# Changelog

## 1.3.0

### Added
- **Standalone Multi-Account Parallel Pool**: Released `CopilotPool` queue lock immediately after atomic worker reservation (`_reserved`), enabling true concurrent execution across multiple logged-in Copilot worker ports while deprioritizing `login_state == "required"` workers.
- **Native Image Generation Gateway Endpoint (`POST /v1/images/generations`)**: Added `CopilotWorker.generate_image` and `CopilotPool.generate_image` with in-page `data:`/`blob:`/`https:` image byte extraction, reference SHA-256/dimension filtering, structured error classification (HTTP 422 policy refusal, HTTP 429 quota/transient limit), and cross-worker buffered failover.
- **Structured Reasoning & DeepThink Stream Separation (`amv_cp_bridge.reasoning`)**: Added `ReasoningStreamParser`, DeepThink directive toggle support, and `reasoning_content` / `content` SSE delta separation.
- **Per-Account Browser Preference & Manual Window Control**: Added `"browser": "chrome" | "edge"` fallback preference alongside `Last Browser` preservation, `external` status flagging for manually opened sessions, and single-worker shutdown via `POST /api/accounts/{port}/close`.
- **Generic Telemetry Source Attribution**: Supported `X-Bridge-Source` and `X-Client-App` headers across REST endpoints cleanly without client-specific coupling.

### Changed
- Removed client-specific file lock env hooks and `/api/telemetry/record` bypass endpoint so all usage is recorded centrally by the bridge server.
- Buffered non-streaming `CopilotPool.query()` per attempt so mid-stream worker failures discard partial output before failing over to another worker.

## 1.2.1

### Added
- **Entra ID Conditional Access Fast-Fail**: Added proactive sub-1.5s detection of login gate URLs (`login.microsoftonline.com`, `login.live.com`, `login.microsoft.com`), eliminating the previous 45-second composer timeout when enterprise sessions are revoked after idle periods.
- **OpenAI Standard HTTP 401 Unauthorized**: Automatically maps `CopilotLoginRequired` to a clean `401 Unauthorized` with `{"error": {"message": "...", "type": "authentication_error", "code": "session_expired"}}` across both streaming SSE chunks and standard REST endpoints, allowing IDEs (Cursor, Cline, Continue.dev) to instantly recognize re-authentication states without hanging.
- **Native OS Desktop Tray Toast Notifications**: Automatically dispatches a system tray balloon / OS toast notification when session expiration is detected, alerting the user to re-authenticate with a single click.
- **Copilot Designer (DALL-E 3) Markdown Image Streaming**: Extracted live DOM generated image elements (`data:image/` or `blob:` or URL) and formatted them directly as Markdown images (`![alt](url)`). Eliminates streaming timeout when Copilot generates high-resolution images without intermediate inner text.
- **FastMCP Concurrency & Shared Standby Documentation**: Formally documented that FastMCP stdio connections route through the centralized gateway (`127.0.0.1:11500`), sharing the exact same authenticated browser session, warm standby countdown timer, and 0MB memory reclamation lifecycle with `/v1/chat/completions`.
- **Community Shout-Out**: Special thanks to Reddit users `u/nameupp` and `u/kantorcodes1` for highlighting enterprise Entra ID session revocation edge cases and FastMCP multiplexing behavior.

## 1.2.0

### Added
- **Multimodal Vision & File Attachment Support**: Full OpenAI-compatible multimodal input support for `/v1/chat/completions`:
  - Accepts `content` as an array of items (`{"type": "text", "text": "..."}` and `{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}`).
  - Supports Base64 data URLs for PNG, JPEG, GIF, WEBP images and PDF documents.
  - Automatically decodes and persists payloads into secure local temporary files (`~/.amv_cp_bridge/temp_uploads/`).
  - Automates file attachment via Playwright CDP file injection (`page.set_input_files('input[type="file"]')`) directly into the active Copilot web session.
  - Automatic post-query cleanup guarantees zero disk leakage (`cleanup_temp_files`).
- **Direct Local File Path Ingestion**: Supports local file paths and `file://` URLs in `content` items (`{"type": "file_path", "path": "..."}`).

## 1.1.0

### Added
- **Operation Mode Configuration**: Added user-selectable engine lifecycle modes in native GUI, web dashboard, and persistent `~/.amv_cp_bridge/settings.json`:
  - **Cold Launch (콜드 유지 / Ephemeral 0MB)**: Forcibly terminates the Edge browser immediately after query completion to guarantee 0MB idle memory footprint (default).
  - **Hot Standby (핫로딩 / 웜 스탠바이)**: Keeps Edge browser running in background for a configurable standby window for ultra-fast consecutive responses (<5s) and session context retention.
- **Configurable Standby Timeout (초 단위)**: Customizable countdown timer (10s ~ 86400s, with quick 60s, 300s, 600s, 1800s presets) that automatically shuts down Edge and reclaims memory to 0MB when idle.
- **Dynamic Settings REST API**: Added `GET /api/settings` and `POST /api/settings` endpoints for runtime configuration persistence.
- **Dedicated Settings Tab**: Added "⚙️ 설정" (Settings) tab in both the native CustomTkinter GUI and the web dashboard (`/dashboard`) with real-time feedback, detailed descriptions, and instant engine synchronization.
- **Live Standby Countdown Display**: The account status cards in the GUI and web dashboard now display remaining seconds (`⏱️ XXs`) during warm standby.

## 1.0.2

### Fixed
- The account name appeared as `:9333` on the main window, and Korean text disappeared from the request queue. The native GUI decoded the live event stream one byte at a time, which discarded multi-byte characters.
- Words such as `복사`, `공유`, and `편집` were removed from answers wherever they appeared. Only status text before the answer and button labels on their own line are now removed.
- The Copilot status text `진행 중…` could appear at the start of an answer.
- On macOS, closing the window could leave no way to reopen it, because the tray library requires the main thread. The window now minimizes to the Dock. This change has not been run on macOS.
- The uninstaller wrote `claude_desktop_config.json` with a UTF-8 byte order mark. The file is now written without one.
- The uninstaller reported a path error when the Desktop folder could not be resolved.
- A damaged `telemetry.db` stopped the application with a raw SQLite error. The error now names the file and how to recover.

### Changed
- README commands are one line each, joined with `&&` so that a later step does not run after an earlier step fails. The Windows script list is now a table because those files are not terminal commands.
- PowerShell examples were added for the REST API because `curl` in Windows PowerShell 5.1 is an alias with different arguments.
- The release regression check fails when a README shell block has more than one line.
- The README no longer describes multi-account load balancing. Requests run one at a time, and the first free account in the list handles them. The behavior did not change in this release.

## 1.0.1

### Added
- One-line installer `scripts/setup_all.ps1` (Windows) and `scripts/setup_all.sh` (macOS). Installs Python when absent, Microsoft Edge when absent, all Python packages, and the application.
- Update check in the loading window against GitHub Releases, with a live progress log.
- Update prompt with `업데이트` and `다음에 하기` buttons. `업데이트` runs the reinstall command.
- Release notes dialog on the first launch after an install.
- Build pipeline with an isolated build environment, UPX compression, and an automated self-test. The compression result is recorded in each release.

- Browser extension package `amv-cp-bridge-extension.zip` in each release.
- One-line uninstall command that does not require the repository.

### Changed
- The uninstaller now removes the dedicated Edge profile and stops only the Edge processes that use it. It previously could stop regular Edge processes.
- Minimum Python version corrected to 3.10, which the `mcp` dependency requires.
- Application version now has a single source, `amv_cp_bridge/_version.py`.
- macOS install no longer downloads Playwright Chromium. The application uses the installed Microsoft Edge.

### Fixed
- Requests could wait with no response on a freshly opened Edge profile. Copilot displays a server-rendered input before the page is active, and the Enter key was ignored. The engine now retries until the message is confirmed as sent.
- An empty Copilot result was reported as success. The request now returns an error.
- Accounts were shown as available without any check. Accounts now show `연결됨`, `연결 확인 전`, or `로그인 필요`, with a `계정 연결` button.
- New installs no longer create a second default account on port 9334.
- The loading window appeared only after the heavy startup work. A boot screen now appears while the EXE unpacks, followed by the loading window and the main window.
- A first run no longer marks the account step as failed.
- New installs received `mcp` 2.x, which removed `mcp.server.fastmcp`. The dependency is now limited to `mcp<2`.
- macOS `.command` files were committed without the executable bit.
- `scripts/build/build_exe.py` resolved the repository root incorrectly after the scripts moved.
- The published EXE included unrelated packages from the build machine, such as `botocore`.
- The README macOS install URL pointed to a branch that does not exist.
