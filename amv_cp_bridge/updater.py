# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""GitHub Releases version check and reinstall launcher."""

import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from ._version import __version__

REPO = "uno-km/amv-cp-bridge"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/master/scripts"
SETUP_PS1_URL = f"{RAW_BASE}/setup_all.ps1"
SETUP_SH_URL = f"{RAW_BASE}/setup_all.sh"

WINDOWS_SETUP_COMMAND = (
    f'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm {SETUP_PS1_URL} | iex"'
)
MACOS_SETUP_COMMAND = f'bash -c "$(curl -fsSL {SETUP_SH_URL})"'


class UpdateError(RuntimeError):
    """Release lookup or reinstall launch failed."""


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str


def parse_version(text: str) -> Tuple[int, ...]:
    cleaned = text.strip().lstrip("vV")
    try:
        return tuple(int(part) for part in cleaned.split("."))
    except ValueError as exc:
        raise UpdateError(f"Invalid version string: {text!r}") from exc


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def _ssl_context() -> ssl.SSLContext:
    if sys.platform == "darwin":
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _fetch_release(url: str, timeout: float) -> Release:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"amv-cp-bridge/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"GitHub API returned HTTP {exc.code}: {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"GitHub API is unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateError(f"GitHub API returned invalid JSON: {exc}") from exc

    tag = payload.get("tag_name")
    if not tag:
        raise UpdateError(f"GitHub API response has no tag_name: {url}")
    parse_version(tag)
    return Release(
        version=tag.lstrip("vV"),
        notes=(payload.get("body") or "").strip(),
        url=payload.get("html_url") or RELEASES_PAGE,
    )


def fetch_latest_release(timeout: float = 5.0) -> Release:
    return _fetch_release(f"{RELEASES_API}/latest", timeout)


def fetch_release_for_version(version: str, timeout: float = 5.0) -> Release:
    return _fetch_release(f"{RELEASES_API}/tags/v{version}", timeout)


def format_notes(markdown: str) -> str:
    """Convert release notes Markdown to plain text for a Tk text widget."""
    lines = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if re.fullmatch(r"\|[\s:|-]+\|", line):
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            line = ": ".join(cells)
        elif line.startswith("#"):
            line = f"[{line.lstrip('#').strip()}]"
        elif line.startswith(("- ", "* ")):
            line = f"• {line[2:]}"
        lines.append(line.replace("`", "").replace("**", ""))
    return "\n".join(lines).strip()


def _seen_version_path() -> Path:
    return Path.home() / ".amv_cp_bridge" / "last_seen_version"


def read_seen_version() -> Optional[str]:
    path = _seen_version_path()
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def mark_version_seen(version: str = __version__) -> None:
    path = _seen_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(version, encoding="utf-8")


def needs_release_notes() -> bool:
    return read_seen_version() != __version__


def _reinstall_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["AMV_WAIT_PID"] = str(os.getpid())
    if getattr(sys, "frozen", False):
        env["AMV_EXE_PATH"] = sys.executable
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def macos_terminal_script(pid: int) -> str:
    return f"AMV_WAIT_PID={pid} {MACOS_SETUP_COMMAND}"


def launch_reinstall() -> None:
    """Start the reinstall command in a new visible terminal. The caller must exit afterwards."""
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", f"irm {SETUP_PS1_URL} | iex"],
                env=_reinstall_env(),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                close_fds=True,
            )
        except OSError as exc:
            raise UpdateError(f"Could not start PowerShell: {exc}") from exc
        return
    if sys.platform == "darwin":
        script = macos_terminal_script(os.getpid()).replace("\\", "\\\\").replace('"', '\\"')
        result = subprocess.run(
            ["osascript",
             "-e", f'tell application "Terminal" to do script "{script}"',
             "-e", 'tell application "Terminal" to activate'],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise UpdateError(f"Could not open Terminal: {result.stderr.strip()}")
        return
    raise UpdateError(
        f"Unsupported platform {sys.platform}. Run manually: {shlex.quote(MACOS_SETUP_COMMAND)}"
    )
