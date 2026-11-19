# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""GitHub Releases version check and reinstall launcher."""

import hashlib
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from ._version import __version__

REPO = "uno-km/amv-cp-bridge"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/master/scripts"
SETUP_PS1_URL = f"{RAW_BASE}/setup_all.ps1"
SETUP_SH_URL = f"{RAW_BASE}/setup_all.sh"
EXE_ASSET_NAME = "amv-cp-bridge.exe"
SHA256_ASSET_NAME = "amv-cp-bridge.exe.sha256"

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
    exe_url: str = ""
    sha256_url: str = ""
    asset_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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

    exe_url = ""
    sha256_url = ""
    asset_size = 0
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        aname = str(asset.get("name") or "").lower()
        dl = str(asset.get("browser_download_url") or "")
        if aname == EXE_ASSET_NAME.lower() or (aname.endswith(".exe") and "amv-cp-bridge" in aname and not exe_url):
            exe_url = dl
            asset_size = int(asset.get("size") or 0)
        elif aname == SHA256_ASSET_NAME.lower() or aname.endswith(".sha256"):
            sha256_url = dl

    return Release(
        version=tag.lstrip("vV"),
        notes=(payload.get("body") or "").strip(),
        url=payload.get("html_url") or RELEASES_PAGE,
        exe_url=exe_url,
        sha256_url=sha256_url,
        asset_size=asset_size,
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


def check_for_update(timeout: float = 6.0) -> Dict[str, Any]:
    """Check GitHub Releases and return structured status for GUI/API."""
    try:
        rel = fetch_latest_release(timeout=timeout)
        newer = is_newer(rel.version, __version__)
        return {
            "ok": True,
            "current_version": __version__,
            "latest_version": rel.version,
            "has_update": newer,
            "frozen": bool(getattr(sys, "frozen", False)),
            "can_hot_swap_exe": bool(getattr(sys, "frozen", False) and rel.exe_url and sys.platform == "win32"),
            "release": rel.to_dict(),
        }
    except UpdateError as exc:
        return {
            "ok": False,
            "current_version": __version__,
            "latest_version": __version__,
            "has_update": False,
            "frozen": bool(getattr(sys, "frozen", False)),
            "can_hot_swap_exe": False,
            "error": str(exc),
        }


def _fetch_expected_sha256(sha_url: str, timeout: float = 10.0) -> Optional[str]:
    if not sha_url:
        return None
    req = urllib.request.Request(sha_url, headers={"User-Agent": f"amv-cp-bridge/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            txt = resp.read().decode("utf-8", errors="replace").strip()
        m = re.search(r"\b([a-fA-F0-9]{64})\b", txt)
        return m.group(1).lower() if m else None
    except Exception:
        return None


def download_release_exe(
    rel: Release,
    dest_path: Optional[Path] = None,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = 180.0,
) -> Path:
    """Download the release EXE asset and verify SHA-256 when a checksum asset is published."""
    if not rel.exe_url:
        raise UpdateError(f"릴리스 v{rel.version}에 {EXE_ASSET_NAME} 첨부 파일이 없습니다.")

    if dest_path is None:
        dl_dir = Path(tempfile.gettempdir()) / "amv_cp_bridge_update"
        dl_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dl_dir / f"amv-cp-bridge-{rel.version}.exe.new"
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(rel.exe_url, headers={"User-Agent": f"amv-cp-bridge/{__version__}"})
    hasher = hashlib.sha256()
    downloaded = 0
    total = rel.asset_size

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            if not total:
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total = int(cl)
            with open(dest_path, "wb") as out_f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            pass
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise UpdateError(f"새 EXE 다운로드 실패: {exc}") from exc

    if downloaded < 100_000:
        dest_path.unlink(missing_ok=True)
        raise UpdateError(f"다운로드된 파일 크기가 비정상적으로 작습니다 ({downloaded} bytes).")

    expected_sha = _fetch_expected_sha256(rel.sha256_url)
    actual_sha = hasher.hexdigest().lower()
    if expected_sha and actual_sha != expected_sha:
        dest_path.unlink(missing_ok=True)
        raise UpdateError(f"SHA-256 체크섬 불일치 (expected={expected_sha[:12]}, actual={actual_sha[:12]}).")

    return dest_path


def build_swap_script(pid: int, target_exe: Path, new_exe: Path, launch_args: Optional[list[str]] = None) -> str:
    """Build an atomic Windows PowerShell hot-swap & relaunch script with automatic rollback."""
    args_ps = ""
    if launch_args:
        escaped = ", ".join("'" + str(a).replace("'", "''") + "'" for a in launch_args)
        args_ps = f" -ArgumentList @({escaped})"
    tgt = str(target_exe).replace("'", "''")
    src = str(new_exe).replace("'", "''")
    bak = (str(target_exe) + ".bak").replace("'", "''")
    return f"""$ErrorActionPreference = 'Stop'
$waitPid = {int(pid)}
$target = '{tgt}'
$source = '{src}'
$backup = '{bak}'

# 1. Wait until current amv-cp-bridge process exits (max 30s)
for ($i = 0; $i -lt 60; $i++) {{
    $p = Get-Process -Id $waitPid -ErrorAction SilentlyContinue
    if (-not $p) {{ break }}
    Start-Sleep -Milliseconds 500
}}
Start-Sleep -Milliseconds 400

# 2. Atomic swap with rollback backup
try {{
    if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue }}
    if (Test-Path -LiteralPath $target) {{ Move-Item -LiteralPath $target -Destination $backup -Force }}
    Move-Item -LiteralPath $source -Destination $target -Force
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
}} catch {{
    if ((Test-Path -LiteralPath $backup) -and (-not (Test-Path -LiteralPath $target))) {{
        Move-Item -LiteralPath $backup -Destination $target -Force -ErrorAction SilentlyContinue
    }}
    throw
}}

# 3. Relaunch updated EXE automatically
Start-Process -FilePath $target{args_ps}
"""


def launch_exe_hot_swap(
    new_exe: Path,
    *,
    target_exe: Optional[Path] = None,
    pid: Optional[int] = None,
    launch_args: Optional[list[str]] = None,
) -> Path:
    """Write and spawn the detached PowerShell hot-swap helper. Caller should exit immediately afterwards."""
    if sys.platform != "win32":
        raise UpdateError("EXE hot-swap is supported on Windows only.")
    tgt = target_exe or Path(sys.executable)
    cur_pid = pid if pid is not None else os.getpid()
    script_text = build_swap_script(cur_pid, tgt, new_exe, launch_args=launch_args)
    script_path = new_exe.parent / f"swap_amv_cp_{cur_pid}.ps1"
    script_path.write_text(script_text, encoding="utf-8")

    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass

    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script_path)],
        env=env,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
    return script_path


def apply_update_and_prepare_restart(
    rel: Optional[Release] = None,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Download latest release and spawn auto-restarting swapper (EXE mode) or setup script (source mode)."""
    target_rel = rel or fetch_latest_release()
    if getattr(sys, "frozen", False) and sys.platform == "win32" and target_rel.exe_url:
        new_exe = download_release_exe(target_rel, progress_cb=progress_cb)
        launch_args = sys.argv[1:] if len(sys.argv) > 1 else []
        script_path = launch_exe_hot_swap(new_exe, launch_args=launch_args)
        return {
            "ok": True,
            "mode": "exe_hot_swap",
            "version": target_rel.version,
            "script": str(script_path),
            "should_exit": True,
        }

    launch_reinstall()
    return {
        "ok": True,
        "mode": "reinstall_script",
        "version": target_rel.version,
        "should_exit": True,
    }
