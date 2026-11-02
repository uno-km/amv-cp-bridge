# Changelog

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
