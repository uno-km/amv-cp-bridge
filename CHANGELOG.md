# Changelog

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
