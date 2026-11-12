# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Copilot 365 Bridge Engine - Parallel Multi-Worker & Image Extraction Edition
Microsoft 365 Copilot (Enterprise / Edu) CDP 기반 멀티 워커 병렬 풀 및 무누수(Zero-Leak) 라이프사이클 엔진.
"""

import sys
import os
import re
import json
import base64
import hashlib
import io
import contextlib
import time
import uuid
import asyncio
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, AsyncGenerator, List, Dict, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from .telemetry_db import telemetry_db
except (ImportError, ValueError):
    from telemetry_db import telemetry_db

try:
    from .settings import load_settings, save_settings, DEFAULT_SETTINGS
except (ImportError, ValueError):
    from settings import load_settings, save_settings, DEFAULT_SETTINGS
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

COPILOT_URL = "https://m365.cloud.microsoft/chat"
COMPOSER_SELECTOR = "[contenteditable='true'], .fai-EditorInput__input, textarea, [role='textbox']:not([aria-readonly='true'])"
ARTICLE_SELECTOR = 'div[role="article"], .fai-CopilotMessage'
LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com", "login.microsoft.com")
COMPOSER_TIMEOUT_SEC = 45
SEND_TIMEOUT_SEC = 60
LOGIN_TIMEOUT_SEC = 300


class CopilotLoginRequired(RuntimeError):
    """The account profile is not signed in to Microsoft 365 Copilot."""


class CopilotQuotaError(RuntimeError):
    """The account reached its daily Copilot generation limit."""


class CopilotTransientError(RuntimeError):
    """Temporary service busy or rate-limit response from Copilot."""


class CopilotPolicyRefusalError(RuntimeError):
    """Content generation refused by Copilot policy."""


_RE_QUOTA = re.compile(
    r"(any more images today|more images today|generate any more images|오늘.{0,20}(더 이상|더이상).{0,20}(이미지|생성)|"
    r"이미지.{0,20}(하루|오늘|일일).{0,20}(한도|제한|초과)|daily (?:image )?(?:limit|quota))",
    re.IGNORECASE,
)
_RE_TRANSIENT = re.compile(
    r"(잠시 후 다시|다시 시도해|나중에 다시|현재 이미지 생성 요청을 처리할 수 없|try again later|please try again|temporarily)",
    re.IGNORECASE,
)
_RE_REFUSAL = re.compile(
    r"(생성할 수 없|만들 수 없|도와드릴 수 없|도움을 드릴 수 없|정책|가이드라인|사용할 수 없는 요청|"
    r"can['’]?t (?:create|generate|help)|cannot (?:create|generate)|unable to (?:create|generate)|content policy|against .*policy)",
    re.IGNORECASE,
)


def _is_login_url(url: str) -> bool:
    return any(host in url.lower() for host in LOGIN_HOSTS)


def _normalize_composer_text(text: str) -> str:
    return re.sub(r"[\s​‌‍﻿]+", "", text or "")


class EventBus:
    """SSE 구독자 브로드캐스터 — asyncio.Queue 기반."""

    def __init__(self):
        self._queues: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    def publish(self, event: dict):
        dead = []
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for d in dead:
            try:
                self._queues.remove(d)
            except ValueError:
                pass


event_bus = EventBus()

def _find_edge_binary() -> str:
    if sys.platform == "darwin":
        mac_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        return mac_path if os.path.isfile(mac_path) else "microsoft-edge"
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return "msedge"

def _find_chrome_binary() -> str:
    if sys.platform == "darwin":
        mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return mac_path if os.path.isfile(mac_path) else "google-chrome"
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return ""

def _find_browser_binary(profile_dir: Optional[str] = None, preferred_browser: Optional[str] = None) -> str:
    """프로필의 Last Browser 기록 또는 계정 browser 선호 설정에 맞춰 Chrome/Edge 바이너리를 선택한다."""
    if profile_dir:
        lb = Path(profile_dir) / "Last Browser"
        if lb.is_file():
            try:
                raw = lb.read_bytes().replace(b"\x00", b"").decode("utf-8", errors="ignore").lower()
                if "chrome.exe" in raw or "google chrome" in raw:
                    chrome_bin = _find_chrome_binary()
                    if chrome_bin:
                        return chrome_bin
                elif "msedge.exe" in raw or "microsoft edge" in raw:
                    return _find_edge_binary()
            except OSError:
                pass
    pref = (preferred_browser or "").strip().lower()
    if pref in ("chrome", "google-chrome", "google chrome"):
        chrome_bin = _find_chrome_binary()
        if chrome_bin:
            return chrome_bin
    return _find_edge_binary()

# 기본 동작 모드: 로컬 메모리 누수 방지를 위해 단발성 즉시 종료(Ephemeral Mode) 활성화
DEFAULT_EPHEMERAL = os.environ.get("COPILOT_EPHEMERAL_MODE", "true").lower() in ("true", "1", "yes")

class CopilotWorker:
    def __init__(self, port: int, name: str, profile_dir: str, mode: str = "cold", standby_timeout_sec: int = 300, ephemeral_mode: Optional[bool] = None, browser: Optional[str] = None):
        self.port = port
        self.name = name
        self.profile_dir = profile_dir
        self.preferred_browser: Optional[str] = browser.strip().lower() if isinstance(browser, str) and browser.strip() else None
        if ephemeral_mode is not None:
            self.mode = "cold" if ephemeral_mode else "hot"
        else:
            self.mode = mode if mode in ("cold", "hot") else "cold"
        self.ephemeral_mode = (self.mode == "cold")
        self.standby_timeout_sec = max(10, standby_timeout_sec)
        self.cdp_url = f"http://127.0.0.1:{port}"
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._lock = asyncio.Lock()
        self._reserved: bool = False
        self.login_state: str = _read_login_states().get(str(port), "unknown")
        self._standby_task: Optional[asyncio.Task] = None
        self._standby_deadline: Optional[float] = None
        self.last_text: str = ""
        self._launched_by_bridge: bool = False

    def _cancel_standby(self):
        """진행 중인 웜 스탠바이 카운트다운 타이머 취소"""
        if self._standby_task and not self._standby_task.done():
            self._standby_task.cancel()
        self._standby_task = None
        self._standby_deadline = None

    def _schedule_standby(self):
        """마지막 요청 후 브라우저를 켜둔 채 지정된 초 동안 대기 (스탠바이 만료 시 자동 0MB 종료)"""
        self._cancel_standby()
        self._standby_deadline = time.time() + self.standby_timeout_sec
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 동기 컨텍스트(예: 초기 설정 반영/단위 테스트)에서는 이벤트 루프 태스크를 만들지 않는다.
            self._standby_deadline = None
            return
        self._standby_task = loop.create_task(self._standby_countdown())
        print(f"[*] [{self.name}] [Hot] 핫로딩 모드: 웜 스탠바이 대기 중 ({self.standby_timeout_sec}초 유지)")

    async def _standby_countdown(self):
        """스탠바이 시간 경과 후 프로세스 회수"""
        try:
            await asyncio.sleep(self.standby_timeout_sec)
            if not self.is_busy():
                print(f"[+] [{self.name}] [Standby] 웜 스탠바이({self.standby_timeout_sec}초) 만료 — 브라우저 프로세스 정리")
                await self.cleanup()
                if self._launched_by_bridge:
                    self.kill_browser_process()
                self._standby_deadline = None
                event_bus.publish({"type": "accounts", "event": "standby_expired", "worker": self.name})
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[!] [{self.name}] 웜 스탠바이 카운트다운 경고: {exc}")

    def apply_settings(self, settings: Dict[str, Any]):
        """동적 설정 갱신 적용"""
        new_mode = str(settings.get("mode", self.mode)).lower().strip()
        if new_mode in ("cold", "hot"):
            self.mode = new_mode
            self.ephemeral_mode = (self.mode == "cold")
        if "standby_timeout_sec" in settings:
            try:
                self.standby_timeout_sec = max(10, int(settings["standby_timeout_sec"]))
            except (ValueError, TypeError):
                pass

        if self.mode == "cold":
            self._cancel_standby()
            if not self.is_busy() and self.is_alive():
                print(f"[*] [{self.name}] 콜드 모드 전환으로 유휴 브라우저 즉시 회수")
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.close())
                except RuntimeError:
                    pass
        elif self.mode == "hot":
            if not self.is_busy() and self.is_alive():
                self._schedule_standby()

    def _set_login_state(self, state: str):
        self.login_state = state
        _write_login_state(self.port, state)

    def get_listening_pids(self) -> List[int]:
        """해당 디버깅 포트에 바인딩된 Edge 브라우저 PID를 탐색 (10초 캐시)"""
        now = time.monotonic()
        if hasattr(self, "_pids_cache_time") and now - self._pids_cache_time < 10.0:
            return self._pids_cache  # type: ignore[attr-defined]
        pids = []
        try:
            port_str = str(int(self.port))
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["lsof", "-ti", f":{port_str}"],
                    capture_output=True, text=True, timeout=3
                )
                for line in result.stdout.strip().splitlines():
                    if line.strip().isdigit():
                        pids.append(int(line.strip()))
            else:
                netstat = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True, text=True, timeout=3
                )
                for line in netstat.stdout.splitlines():
                    if f":{port_str}" not in line or "LISTENING" not in line:
                        continue
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit() and int(pid) > 0:
                            pids.append(int(pid))
        except Exception:
            pass
        result = list(set(pids))
        self._pids_cache = result
        self._pids_cache_time = now
        return result

    def is_alive(self) -> bool:
        """해당 디버깅 포트가 열려있는지 확인 (3초 캐시)"""
        now = time.monotonic()
        if hasattr(self, "_alive_cache_time") and now - self._alive_cache_time < 3.0:
            return self._alive_cache  # type: ignore[attr-defined]
        alive = False
        try:
            req = urllib.request.urlopen(f"{self.cdp_url}/json", timeout=0.5)
            alive = req.status == 200
        except Exception:
            pass
        self._alive_cache = alive
        self._alive_cache_time = now
        return alive

    def is_busy(self) -> bool:
        return self._lock.locked() or self._reserved

    async def ensure_running(self, visible: bool = False):
        """브라우저가 꺼져있으면 프로필의 Last Browser(Chrome/Edge) 또는 선호 설정에 맞춰 디버깅 모드로 자동 기동"""
        if self.is_alive():
            self._launched_by_bridge = False
            return True

        print(f"[!] [{self.name}] 포트 {self.port} 세션 기동 중...")
        browser_path = _find_browser_binary(self.profile_dir, self.preferred_browser)
        args = [
            browser_path,
            f"--remote-debugging-port={int(self.port)}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if not visible:
            args.append("--window-position=-3000,-3000")  # 모니터 밖으로 던져 화면 노출 방지
        subprocess.Popen(args + [COPILOT_URL])
        self._launched_by_bridge = True

        for _ in range(25):
            await asyncio.sleep(0.4)
            if self.is_alive():
                print(f"[+] [{self.name}] 포트 {self.port} CDP 연결 준비 완료.")
                return True
        raise RuntimeError(f"{self.name}(포트 {self.port}) 브라우저를 기동할 수 없습니다.")

    async def connect(self):
        """CDP에 연결하고 코파일럿 탭 확보"""
        await self.ensure_running()
        if not self.playwright:
            self.playwright = await async_playwright().start()

        if not self.browser or not self.browser.is_connected():
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
            self.context = self.browser.contexts[0]

        target_page = None
        for p in self.context.pages:
            url = p.url.lower()
            if "m365.cloud.microsoft" in url or "copilot.microsoft" in url or _is_login_url(url):
                target_page = p
                break

        if not target_page:
            print(f"[+] [{self.name}] 코파일럿 탭 진입 대기...")
            target_page = await self.context.new_page()
            await target_page.goto(COPILOT_URL)
            await asyncio.sleep(2.5)

        self.page = target_page
        return self.page

    async def cleanup(self):
        """Playwright 연결 세션 정상 정리"""
        try:
            if self.page and not self.page.is_closed():
                await self.page.close()
        except Exception:
            pass
        self.page = None

        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        self.context = None

        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.browser = None

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.playwright = None

    def kill_browser_process(self, *, force: bool = False):
        """포트에 바인딩된 브라우저 프로세스 정리 (브릿지가 직접 기동하지 않은 외부 창은 force=True 시에만 종료)"""
        if not force and not self._launched_by_bridge:
            return
        self.__dict__.pop("_pids_cache_time", None)
        self.__dict__.pop("_alive_cache_time", None)
        pids = self.get_listening_pids()
        self.__dict__.pop("_pids_cache_time", None)
        for pid in pids:
            try:
                if sys.platform == "darwin":
                    subprocess.run(["kill", "-9", str(int(pid))], capture_output=True, timeout=5)
                else:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(int(pid))],
                        capture_output=True, timeout=5
                    )
                print(f"[+] [{self.name}] 브라우저 프로세스 트리(PID {pid}) 종료")
            except Exception as e:
                print(f"[!] [{self.name}] 브라우저 프로세스(PID {pid}) 종료 처리 중 경고: {e}")
        self._launched_by_bridge = False

    def _clean_text(self, text: str) -> str:
        """응답 텍스트 정제"""
        if not text:
            return ""
        if "Copilot said:\n" in text:
            text = text.split("Copilot said:\n", 1)[-1]
        elif "Copilot said:" in text:
            text = text.split("Copilot said:", 1)[-1]

        skip_phrases = {
            "복사", "공유", "좋아요", "싫어요", "새로 고침", "편집",
            "준비 중입니다…", "준비 중입니다...", "생각 중…", "생각 중...",
            "잠시만 기다려 주세요…", "잠시만 기다려 주세요...", "살펴보는 중...", "살펴보는 중…",
            "자세히 살펴보는 중…", "자세히 살펴보는 중...", "작업 중...", "작업 중…",
            "진행 중…", "진행 중...", "가능하게 만드는 중...", "가능하게 만드는 중…",
            "항목을 정리하는 중...", "항목을 정리하는 중…", "정리하는 중...", "정리하는 중…"
        }
        # 상태 문구는 응답 앞에만 붙는다. 본문의 같은 단어는 지우지 않는다.
        stripped = text.lstrip()
        status_prefix = next((p for p in skip_phrases if p.endswith(("…", "...")) and stripped.startswith(p)), None)
        while status_prefix:
            stripped = stripped[len(status_prefix):].lstrip()
            status_prefix = next((p for p in skip_phrases if p.endswith(("…", "...")) and stripped.startswith(p)), None)
        text = stripped

        lines = text.split("\n")
        clean_lines = []
        for line in lines:
            trimmed = line.strip()
            if trimmed in skip_phrases:
                continue
            clean_lines.append(line)
        return "\n".join(clean_lines).strip()

    async def ensure_model_selected(self, page: Page):
        """GPT-5.6 Sol 깊이 생각하기 모드가 항상 유지되도록 자동 보정"""
        try:
            btn = page.locator("#gptModeSwitcher").first
            if await btn.is_visible():
                txt = await btn.inner_text()
                if "GPT-5.6" in txt and ("Think" in txt or "깊이" in txt):
                    return

                await btn.click()
                await asyncio.sleep(0.3)
                gpt_item = page.locator('[role="menuitem"]:has-text("GPT"), .fui-MenuItem:has-text("GPT")').first
                if await gpt_item.is_visible():
                    await gpt_item.hover()
                    await asyncio.sleep(0.3)
                    target = page.locator('[role="menuitem"]:has-text("GPT-5.6 Sol 깊이 생각하기"), [role="menuitem"]:has-text("깊이 생각하기")').first
                    if await target.is_visible():
                        await target.click()
                        await asyncio.sleep(0.3)
                        print(f"[+] [{self.name}] 모델 설정 완료: GPT-5.6 Sol 깊이 생각하기")
        except Exception:
            pass

    async def new_chat(self):
        """새 채팅 세션 시작 (이전 대화 맥락 초기화)"""
        page = await self.connect()
        try:
            btn = page.locator("a[aria-label*='새 채팅'], button[aria-label*='새 채팅'], .fai-CopilotNavItem").first
            if await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.2)
        except Exception:
            pass

        await self.ensure_model_selected(page)
        return True

    async def _wait_for_composer(self, page: Page, timeout: float = COMPOSER_TIMEOUT_SEC, fast_fail: bool = True) -> bool:
        """로그인 리다이렉트가 끝나고 Copilot 입력창이 보일 때까지 대기한다.
        fast_fail=True인 경우, Entra ID/Conditional Access 리디렉션 감지 시 불필요한 45초 지연을 방지하고 1.5초 내 Fast-Fail을 수행한다.
        """
        deadline = time.time() + timeout
        textbox = page.locator(COMPOSER_SELECTOR).first
        login_detected_start: Optional[float] = None
        while time.time() < deadline:
            current_url = page.url
            if not _is_login_url(current_url) and await textbox.is_visible():
                return True

            if fast_fail and _is_login_url(current_url):
                # 자율 세션 복구 시도 (Self-Healing Re-auth): 계정 선택 타일이 감지되면 자동 마우스 클릭
                try:
                    tile = page.locator('.tile-container, [data-test-id*="@"], div:has-text("로그인되어 있음")').first
                    if await tile.is_visible():
                        box = await tile.bounding_box()
                        if box:
                            cx = box['x'] + box['width'] / 2
                            cy = box['y'] + box['height'] / 2
                            print(f"[*] [{self.name}] [Self-Healing] Entra ID 계정 타일 감지 -> 자동 클릭 복구 시도...")
                            await page.mouse.click(cx, cy)
                            await asyncio.sleep(1.2)
                            continue
                except Exception:
                    pass

                if login_detected_start is None:
                    login_detected_start = time.time()
                elif time.time() - login_detected_start >= 2.5:
                    print(f"[!] [{self.name}] [Fast-Fail] Entra ID 로그인 리디렉션 감지: {current_url[:120]}")
                    return False
            else:
                login_detected_start = None

            await asyncio.sleep(0.3)
        return False

    async def _submit_prompt(self, page: Page, prompt: str):
        """프롬프트를 입력하고, 메시지가 실제로 전송될 때까지 재시도한다.

        Copilot은 서버 렌더링된 입력창을 먼저 표시하므로, 페이지가 동작하기 전의
        입력과 Enter는 오류 없이 무시된다. 전송 여부는 메시지 생성 또는 대화 URL로 판정한다.
        """
        textbox = page.locator(COMPOSER_SELECTOR).first
        expected = _normalize_composer_text(prompt)
        articles = page.locator(ARTICLE_SELECTOR)
        baseline = await articles.count()
        url_before = page.url

        async def was_sent(wait_seconds: float) -> bool:
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                if await articles.count() > baseline:
                    return True
                if page.url != url_before and "/conversation/" in page.url:
                    return True
                await asyncio.sleep(0.25)
            return False

        async def composer_text() -> str:
            raw = await textbox.evaluate("e => e.innerText ?? e.value ?? ''")
            return _normalize_composer_text(raw)

        deadline = time.time() + SEND_TIMEOUT_SEC
        while time.time() < deadline:
            await textbox.click()
            if await composer_text() != expected:
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Delete")
                await page.keyboard.insert_text(prompt)
                await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            if await was_sent(4.0):
                return
            if not await composer_text() and await was_sent(10.0):
                return
        raise RuntimeError(f"Copilot 메시지 전송 실패: {SEND_TIMEOUT_SEC}초 안에 전송이 확인되지 않았습니다. (URL: {page.url[:120]})")

    async def open_login(self, timeout: float = LOGIN_TIMEOUT_SEC) -> bool:
        """로그인할 수 있도록 브라우저 창을 화면에 띄우고, 입력창이 보이면 연결 완료로 기록한다."""
        async with self._lock:
            try:
                self.kill_browser_process(force=True)
                await self.ensure_running(visible=True)
                page = await self.connect()
                connected = await self._wait_for_composer(page, timeout, fast_fail=False)
                self._set_login_state("ok" if connected else "required")
                return connected
            except Exception as exc:
                print(f"[!] [{self.name}] 계정 연결 실패: {type(exc).__name__}: {exc}")
                self._set_login_state("required")
                return False
            finally:
                await self.cleanup()
                self.kill_browser_process()

    async def _attach_files(self, page: Page, file_paths: List[str]):
        """Copilot 웹페이지 입력창에 이미지 및 파일을 안전하게 첨부"""
        valid_files = [str(Path(f).resolve()) for f in file_paths if os.path.isfile(f)]
        if not valid_files:
            return

        print(f"[*] [{self.name}] 파일 {len(valid_files)}개 첨부 시도: {[Path(f).name for f in valid_files]}")
        try:
            file_input = page.locator('input[type="file"]')
            if await file_input.count() == 0:
                triggers = page.locator('button[aria-label*="첨부"], button[aria-label*="Attach"], button[aria-label*="Add"], button[title*="첨부"], button[title*="Attach"], button[title*="Add"]')
                if await triggers.count() > 0:
                    await triggers.first.click()
                    await asyncio.sleep(0.5)

            await page.set_input_files('input[type="file"]', valid_files, timeout=6000)
            print(f"[+] [{self.name}] 파일 업로드 주입 완료. 프리뷰 렌더링 대기...")
            await asyncio.sleep(2.5)
        except Exception as exc:
            print(f"[!] [{self.name}] 파일 첨부 중 경고 (텍스트 질의 계속 진행): {exc}")

    async def _prepare_and_submit(self, prompt: str, *, reset_chat: bool = True, file_paths: Optional[List[str]] = None) -> Page:
        page = await self.connect()
        if not await self._wait_for_composer(page):
            self._set_login_state("required")
            raise CopilotLoginRequired(
                f"[{self.name}] Copilot 입력창을 {COMPOSER_TIMEOUT_SEC}초 안에 찾지 못했습니다. "
                f"프로그램에서 계정 연결을 진행하십시오. (URL: {page.url[:120]})"
            )
        if reset_chat:
            await self.new_chat()
        if file_paths:
            await self._attach_files(page, file_paths)
        await self._submit_prompt(page, prompt)
        self._set_login_state("ok")
        return page

    async def stream_query(self, prompt: str, reset_chat: bool = True, file_paths: Optional[List[str]] = None) -> AsyncGenerator[str, None]:
        """질문을 던지고 실시간 스트리밍 텍스트 델타를 yield"""
        async with self._lock:
            self._cancel_standby()
            self.last_text = ""
            try:
                page = await self._prepare_and_submit(prompt, reset_chat=reset_chat, file_paths=file_paths)

                emitted_text = ""
                stable_count = 0
                done_stable = 0
                timeout = float(os.environ.get("COPILOT_BRIDGE_TIMEOUT_SEC", "600"))
                start_gen = time.time()

                while time.time() - start_gen < timeout:
                    info = await page.evaluate(r"""() => {
                        const articles = Array.from(document.querySelectorAll('div[role="article"], .fai-CopilotMessage'))
                            .filter(a => !a.classList.contains('fai-UserMessage') && !(a.innerText || '').startsWith('You said'));
                        if (articles.length === 0) return { text: "", isDone: false };
                        const last = articles[articles.length - 1];
                        const copyBtns = Array.from(last.querySelectorAll('button[aria-label*="복사"], button[title*="복사"], button[aria-label*="Copy"]'));
                        const msgCopy = copyBtns.some(b => !b.closest('pre, code, [class*="code" i], [class*="Code"]'));
                        const stopBtn = document.querySelector('button[aria-label*="중지"], button[aria-label*="Stop"], button[title*="중지"]');

                        // Extract generated images (e.g. Copilot Designer / DALL-E)
                        const imgs = Array.from(last.querySelectorAll('img'))
                            .filter(img => {
                                if (!img.src) return false;
                                const isBig = (img.naturalWidth > 100 && img.naturalHeight > 100) || (img.width > 100 && img.height > 100);
                                const isSpecialSrc = img.src.startsWith('data:image') || img.src.startsWith('blob:') || img.src.includes('dalle') || img.src.includes('th?id=');
                                return isBig || isSpecialSrc;
                            })
                            .map(img => {
                                const alt = (img.alt || 'Generated Image').replace(/[\\r\\n]+/g, ' ').trim();
                                return `![${alt}](${img.src})`;
                            });

                        let text = last.innerText || "";
                        if (imgs.length > 0) {
                            const trimmed = text.replace(/^Copilot said:\s*/i, '').trim();
                            if (trimmed.length > 0) {
                                text = text + "\\n\\n" + imgs.join("\\n\\n");
                            } else {
                                text = "Copilot said:\\n\\n" + imgs.join("\\n\\n");
                            }
                        }

                        const hasCompletedImage = imgs.length > 0 && !stopBtn;
                        return {
                            text: text,
                            isDone: (msgCopy && !stopBtn) || hasCompletedImage
                        };
                    }""")

                    raw_text = info.get("text", "")
                    is_done = info.get("isDone", False)
                    clean_current = self._clean_text(raw_text)

                    if clean_current:
                        if not clean_current.startswith(emitted_text):
                            delta = clean_current
                            emitted_text = clean_current
                            stable_count = 0
                            yield delta
                        elif len(clean_current) > len(emitted_text):
                            delta = clean_current[len(emitted_text):]
                            emitted_text = clean_current
                            stable_count = 0
                            yield delta
                        else:
                            stable_count += 1
                    else:
                        stable_count += 1

                    done_stable = done_stable + 1 if (is_done and stable_count > 0) else 0
                    if is_done and len(clean_current) > 0 and done_stable >= 4:
                        break

                    if stable_count >= 180 and len(clean_current) > 0:
                        break

                    await asyncio.sleep(0.5)
                self.last_text = emitted_text

                if not emitted_text:
                    raise TimeoutError(f"Copilot 응답 없음: 메시지 전송 후 {timeout}초 안에 응답을 받지 못했습니다.")

            finally:
                if self.mode == "cold":
                    await self.cleanup()
                    self.kill_browser_process()
                else:
                    self._schedule_standby()

    async def generate_image(
        self,
        prompt: str,
        *,
        file_paths: Optional[List[str]] = None,
        reset_chat: bool = True,
        timeout_sec: float = 240.0,
        min_bytes: int = 50_000,
    ) -> Dict[str, Any]:
        """프롬프트(및 선택적 참조 이미지)를 전송한 뒤 생성 이미지 바이너리(base64)를 브라우저 컨텍스트에서 추출한다."""
        ref_hashes: set = set()
        ref_sizes: set = set()
        for fp in (file_paths or []):
            p = Path(fp)
            if not p.is_file():
                continue
            raw_ref = p.read_bytes()
            ref_hashes.add(hashlib.sha256(raw_ref).hexdigest())
            try:
                from PIL import Image
                with Image.open(io.BytesIO(raw_ref)) as im:
                    ref_sizes.add(im.size)
            except Exception:
                pass

        async with self._lock:
            self._cancel_standby()
            self.last_text = ""
            try:
                page = await self._prepare_and_submit(prompt, reset_chat=reset_chat, file_paths=file_paths)

                deadline = time.time() + max(10.0, float(timeout_sec))
                done_ticks = 0
                await asyncio.sleep(3.0)
                while time.time() < deadline:
                    state = await page.evaluate(r"""() => {
                        const articles = Array.from(document.querySelectorAll('div[role="article"], .fai-CopilotMessage'))
                            .filter(a => !a.classList.contains('fai-UserMessage') && !(a.innerText || '').startsWith('You said'));
                        const stopBtn = document.querySelector('button[aria-label*="중지"], button[aria-label*="Stop"], button[title*="중지"]');
                        const last = articles.length ? articles[articles.length - 1] : null;
                        const hasText = last ? ((last.innerText || '').trim().length > 0) : false;
                        const imgCount = last ? last.querySelectorAll('img').length : 0;
                        return { stopping: !!stopBtn, hasContent: hasText || imgCount > 0 };
                    }""")
                    if not state.get("stopping") and state.get("hasContent"):
                        done_ticks += 1
                        if done_ticks >= 3:
                            break
                    else:
                        done_ticks = 0
                    await asyncio.sleep(1.0)
                else:
                    raise TimeoutError(f"Copilot 이미지 생성이 {timeout_sec:.0f}초 안에 완료되지 않았습니다.")

                extracted = await page.evaluate(r"""async () => {
                    const articles = Array.from(document.querySelectorAll('div[role="article"], .fai-CopilotMessage'))
                        .filter(a => !a.classList.contains('fai-UserMessage') && !(a.innerText || '').startsWith('You said'));
                    if (!articles.length) return { text: "", items: [] };
                    const last = articles[articles.length - 1];
                    const items = [];
                    for (const img of Array.from(last.querySelectorAll('img'))) {
                        const src = img.getAttribute('src') || '';
                        if (!src) continue;
                        if (src.startsWith('data:image/')) {
                            const comma = src.indexOf(',');
                            const header = src.slice(5, comma);
                            const mime = header.split(';')[0] || 'image/png';
                            items.push({ b64: src.slice(comma + 1), mime });
                        } else if (src.startsWith('blob:') || src.startsWith('https://')) {
                            try {
                                const resp = await fetch(src);
                                const ct = resp.headers.get('content-type') || 'image/png';
                                const buf = new Uint8Array(await resp.arrayBuffer());
                                let bin = '';
                                for (let i = 0; i < buf.length; i += 8192) {
                                    bin += String.fromCharCode(...buf.subarray(i, i + 8192));
                                }
                                items.push({ b64: btoa(bin), mime: ct.split(';')[0] });
                            } catch (e) {}
                        }
                    }
                    return { text: last.innerText || "", items };
                }""")

                clean_text = self._clean_text(extracted.get("text", ""))
                self.last_text = clean_text
                valid_images: List[Dict[str, Any]] = []
                for item in extracted.get("items", []):
                    b64 = item.get("b64") or ""
                    if not b64:
                        continue
                    try:
                        raw = base64.b64decode(b64)
                    except Exception:
                        continue
                    if len(raw) < min_bytes:
                        continue
                    sha = hashlib.sha256(raw).hexdigest()
                    if sha in ref_hashes:
                        continue
                    if ref_sizes:
                        try:
                            from PIL import Image
                            with Image.open(io.BytesIO(raw)) as im:
                                if im.size in ref_sizes:
                                    continue
                        except Exception:
                            pass
                    valid_images.append({
                        "b64_json": b64,
                        "mime_type": item.get("mime") or "image/png",
                        "sha256": sha,
                        "bytes_len": len(raw),
                    })

                if not valid_images:
                    if _RE_QUOTA.search(clean_text):
                        raise CopilotQuotaError(f"[일일 한도 초과] {clean_text[:250]}")
                    if _RE_TRANSIENT.search(clean_text):
                        raise CopilotTransientError(f"[일시 제한] {clean_text[:250]}")
                    if _RE_REFUSAL.search(clean_text):
                        raise CopilotPolicyRefusalError(f"[정책 거부] {clean_text[:300]}")
                    raise RuntimeError(f"생성된 이미지를 찾지 못했습니다(수신 <img> {len(extracted.get('items', []))}건). 응답: {clean_text[:200]}")

                return {"images": valid_images, "text": clean_text, "worker_port": self.port}
            finally:
                if self.mode == "cold":
                    await self.cleanup()
                    self.kill_browser_process()
                else:
                    self._schedule_standby()

    async def query(self, prompt: str, file_paths: Optional[List[str]] = None) -> str:
        collected = []
        async for chunk in self.stream_query(prompt, file_paths=file_paths):
            collected.append(chunk)
        return "".join(collected).strip()

    async def close(self, *, force: bool = False):
        self._cancel_standby()
        await self.cleanup()
        self.kill_browser_process(force=force)


CONFIG_DIR = os.path.join(str(Path.home()), ".amv_cp_bridge")
CONFIG_PATH = os.path.join(CONFIG_DIR, "accounts.json")
LOGIN_STATE_PATH = os.path.join(CONFIG_DIR, "account_state.json")


def _read_login_states() -> Dict[str, str]:
    if not os.path.isfile(LOGIN_STATE_PATH):
        return {}
    try:
        with open(LOGIN_STATE_PATH, "r", encoding="utf-8") as f:
            states = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"[!] account_state.json 읽기 실패: {exc}")
        return {}
    return states if isinstance(states, dict) else {}


def _write_login_state(port: int, state: str):
    states = _read_login_states()
    states[str(port)] = state
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(LOGIN_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(states, f)


def _load_accounts() -> List[Dict[str, Any]]:
    """설정 파일에서 계정 목록 로드. 없으면 기본 계정 1개로 초기화."""
    home = str(Path.home())
    defaults = [
        {"port": 9333, "name": "기본 계정", "profile_dir": os.path.join(home, "copilot_profile_default")},
    ]
    legacy_defaults = defaults + [
        {"port": 9334, "name": "보조 계정", "profile_dir": os.path.join(home, "copilot_profile_secondary")},
    ]
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list) and len(loaded) > 0 and loaded != legacy_defaults:
                return loaded
        except Exception as exc:
            print(f"[!] accounts.json 읽기 실패, 기본값으로 재생성합니다: {exc}")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2)
    return defaults


class CopilotPool:
    """멀티 계정 로드밸런싱 풀 관리자 (계정별 병렬 실행 및 자동 페일오버)"""
    def __init__(self, mode: Optional[str] = None, standby_timeout_sec: Optional[int] = None, ephemeral_mode: Optional[bool] = None):
        self.settings = load_settings()
        if mode is not None:
            self.settings["mode"] = mode
        elif ephemeral_mode is not None:
            self.settings["mode"] = "cold" if ephemeral_mode else "hot"
        if standby_timeout_sec is not None:
            self.settings["standby_timeout_sec"] = max(10, standby_timeout_sec)

        self.mode = self.settings.get("mode", "cold")
        self.standby_timeout_sec = int(self.settings.get("standby_timeout_sec", 300))
        self.ephemeral_mode = (self.mode == "cold")

        accounts = _load_accounts()
        self.workers: List[CopilotWorker] = [self._make_worker(acc) for acc in accounts]
        self._accounts_mtime: float = os.path.getmtime(CONFIG_PATH) if os.path.isfile(CONFIG_PATH) else 0.0
        self._queue_lock = asyncio.Lock()
        self.queued_count: int = 0
        self.active_count: int = 0
        self.current_task: Optional[str] = None
        self.task_start_time: Optional[float] = None
        self._active_tasks: Dict[str, str] = {}
        # 실시간 태스크 큐 추적 [{id, source, preview, status, worker, queued_at, started_at}]
        self._task_queue: List[Dict[str, Any]] = []

    def _make_worker(self, acc: Dict[str, Any]) -> CopilotWorker:
        return CopilotWorker(
            port=int(acc["port"]),
            name=acc["name"],
            profile_dir=acc["profile_dir"],
            mode=self.mode,
            standby_timeout_sec=self.standby_timeout_sec,
            browser=acc.get("browser"),
        )

    def update_settings(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        """동적으로 설정을 갱신하고 디스크에 저장 및 워커들에 전파"""
        persisted = save_settings(new_data)
        self.settings = persisted
        self.mode = persisted.get("mode", "cold")
        self.standby_timeout_sec = int(persisted.get("standby_timeout_sec", 300))
        self.ephemeral_mode = (self.mode == "cold")
        for w in self.workers:
            w.apply_settings(persisted)
        self._push({
            "type": "settings_updated",
            "settings": persisted,
            "workers": self._worker_brief()
        })
        return persisted

    def get_status_summary(self) -> str:
        status_lines = []
        for w in self.workers:
            alive = w.is_alive()
            busy = w.is_busy()
            st = "BUSY" if busy else ("IDLE" if alive else "OFFLINE")
            status_lines.append(f"{w.name}(port {w.port}): {st}")
        return " | ".join(status_lines) if status_lines else "no workers"

    def get_telemetry_status(self) -> Dict[str, Any]:
        """웹 대시보드 및 실시간 상태 모니터링용 종합 메트릭스"""
        worker_details = []
        available_cnt = 0
        now = time.time()
        for w in self.workers:
            busy = w.is_busy()
            alive = w.is_alive()
            pids = w.get_listening_pids()
            if not busy:
                available_cnt += 1
            st = "BUSY" if busy else ("IDLE" if alive else "OFFLINE_0MB")
            standby_rem = round(max(0, w._standby_deadline - now), 1) if (alive and not busy and w._standby_deadline) else 0.0
            worker_details.append({
                "name": w.name,
                "port": w.port,
                "status": st,
                "is_busy": busy,
                "is_alive": alive,
                "external": bool(alive and not w._launched_by_bridge),
                "browser": w.preferred_browser or "",
                "login_state": w.login_state,
                "pids": pids,
                "memory_mb": 0 if not alive else (len(pids) * 35), # 추정치
                "mode": w.mode,
                "standby_remaining_sec": standby_rem,
            })

        elapsed = round(time.time() - self.task_start_time, 1) if (self.active_count > 0 and self.task_start_time) else 0.0

        bridge_status = "PROCESSING" if self.active_count > 0 else "IDLE_0MB"

        return {
            "bridge_status": bridge_status,
            "is_busy": self.active_count > 0,
            "active_requests": self.active_count,
            "queued_requests": self.queued_count,
            "current_task": self.current_task,
            "current_task_elapsed_sec": elapsed,
            "available_accounts": available_cnt,
            "total_accounts": len(self.workers),
            "mode": self.mode,
            "standby_timeout_sec": self.standby_timeout_sec,
            "ephemeral_mode": self.ephemeral_mode,
            "settings": self.settings,
            "workers": worker_details,
            "task_queue": list(self._task_queue[-20:]),  # 최근 20개
        }

    def _sync_workers_from_disk(self):
        """accounts.json 변경 시 비사용 중 워커 구성을 동적으로 재적재한다."""
        if not os.path.isfile(CONFIG_PATH):
            return
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            return
        if mtime == self._accounts_mtime:
            return
        accounts = _load_accounts()
        by_port = {w.port: w for w in self.workers}
        updated: List[CopilotWorker] = []
        for acc in accounts:
            p = int(acc["port"])
            if p in by_port:
                w = by_port[p]
                w.name = acc["name"]
                w.profile_dir = acc["profile_dir"]
                b = acc.get("browser")
                w.preferred_browser = b.strip().lower() if isinstance(b, str) and b.strip() else None
                updated.append(w)
            else:
                updated.append(self._make_worker(acc))
        self.workers = updated
        self._accounts_mtime = mtime

    async def acquire_worker(self, exclude_ports: Optional[set] = None) -> CopilotWorker:
        """가장 빠르게 사용 가능한 워커를 원자적으로 선점(로그인 만료 워커는 후순위 배치, 없으면 대기)"""
        excluded = exclude_ports or set()
        wait_logged = False
        while True:
            async with self._queue_lock:
                self._sync_workers_from_disk()
                candidates = [w for w in self.workers if w.port not in excluded] or list(self.workers)
                ready = [w for w in candidates if w.login_state != "required"]
                fallback = [w for w in candidates if w.login_state == "required"]
                for w in ready + fallback:
                    if not w.is_busy():
                        w._reserved = True
                        if wait_logged:
                            print(f"[+] [로드밸런서] {w.name}(포트 {w.port}) 확보 완료!")
                        return w
            if not wait_logged and len(self.workers) > 1:
                print("[*] [로드밸런서] 모든 계정 사용 중. 먼저 완료되는 세션으로 대기 대열에 진입합니다...")
                wait_logged = True
            await asyncio.sleep(0.25)

    def _worker_brief(self) -> List[Dict[str, Any]]:
        now = time.time()
        return [
            {
                "name": w.name,
                "port": w.port,
                "is_busy": w.is_busy(),
                "is_alive": w.is_alive(),
                "external": bool(w.is_alive() and not w._launched_by_bridge),
                "browser": w.preferred_browser or "",
                "login_state": w.login_state,
                "mode": w.mode,
                "standby_remaining_sec": round(max(0, w._standby_deadline - now), 1) if (w.is_alive() and not w.is_busy() and w._standby_deadline) else 0.0
            }
            for w in self.workers
        ]

    async def open_login(self, port: int) -> bool:
        worker = next((w for w in self.workers if w.port == port), None)
        if worker is None:
            raise ValueError(f"등록되지 않은 계정 포트입니다: {port}")
        login_task = asyncio.ensure_future(worker.open_login())
        await asyncio.sleep(0)
        self._push({"type": "accounts", "workers": self._worker_brief()})
        try:
            return await login_task
        finally:
            self._push({"type": "accounts", "workers": self._worker_brief()})

    def _push(self, event: dict):
        """이벤트 발행 (동기 컨텍스트에서도 안전하게 호출)."""
        event_bus.publish(event)

    def _enqueue_task(self, prompt: str, source: str) -> tuple[str, str, Dict[str, Any]]:
        task_id = uuid.uuid4().hex[:10]
        preview = (prompt[:60] + "…") if len(prompt) > 60 else prompt
        task_entry: Dict[str, Any] = {
            "id": task_id, "source": source, "preview": preview,
            "status": "queued", "worker": None,
            "queued_at": time.time(), "started_at": None, "done_at": None,
            "success": None, "tokens": 0,
        }
        self._task_queue.append(task_entry)
        if len(self._task_queue) > 100:
            self._task_queue.pop(0)
        self.queued_count += 1
        self._push({"type": "task_queued", "task": dict(task_entry),
                    "queued": self.queued_count, "active": self.active_count})
        return task_id, preview, task_entry

    def _mark_running(self, task_id: str, preview: str, task_entry: Dict[str, Any]) -> None:
        self.queued_count = max(0, self.queued_count - 1)
        self.active_count += 1
        self._active_tasks[task_id] = preview
        self.current_task = preview
        if self.task_start_time is None:
            self.task_start_time = time.time()
        task_entry["status"] = "running"
        task_entry["started_at"] = time.time()

    def _finish_counters(self, task_id: str, started_running: bool) -> None:
        if started_running:
            self._active_tasks.pop(task_id, None)
            self.active_count = max(0, self.active_count - 1)
            if self.active_count == 0:
                self.current_task = None
                self.task_start_time = None
            elif self._active_tasks:
                self.current_task = next(reversed(self._active_tasks.values()))
        else:
            self.queued_count = max(0, self.queued_count - 1)

    def _finalize_task(
        self,
        *,
        task_id: str,
        task_entry: Dict[str, Any],
        prompt: str,
        collected_chunks: list,
        collected_bytes: int,
        worker: CopilotWorker,
        t_start: float,
        source: str,
        client_app: str,
        client_version: str,
        prompt_bytes: int,
        ip_addr: str,
        success: bool,
        model: str = "gpt-5.6-sol",
        full_response: Optional[str] = None,
    ) -> None:
        duration_ms = (time.time() - t_start) * 1000
        tokens_est = max(1, int(collected_bytes / 4.2)) if collected_bytes > 0 else 0
        queue_wait = (task_entry["started_at"] or t_start) - task_entry["queued_at"]
        task_entry.update({
            "status": "done" if success else "error",
            "done_at": time.time(),
            "success": success,
            "tokens": tokens_est,
        })
        self._push({
            "type": "task_done",
            "task": dict(task_entry),
            "active": max(0, self.active_count - 1),
            "stats_dirty": True,
            "workers": self._worker_brief(),
        })
        try:
            telemetry_db.record_query(
                prompt=prompt,
                duration_ms=duration_ms,
                bytes_len=collected_bytes,
                worker_port=worker.port,
                account_label=worker.name,
                model=model,
                source=source,
                success=success,
                task_id=task_id,
                client_app=client_app,
                client_version=client_version,
                queue_wait_ms=queue_wait * 1000,
                prompt_bytes=prompt_bytes,
                ip_addr=ip_addr,
                full_response=("".join(collected_chunks) if full_response is None else full_response),
            )
        except Exception as _db_err:
            print(f"[!] telemetry record_query 실패: {_db_err}")

    async def stream_query(self, prompt: str, reset_chat: bool = True, file_paths: Optional[List[str]] = None,
                           source: str = "api", client_app: str = "", client_version: str = "",
                           prompt_bytes: int = 0, ip_addr: str = "") -> AsyncGenerator[str, None]:
        task_id, preview, task_entry = self._enqueue_task(prompt, source)
        t_start = time.time()
        self._mark_running(task_id, preview, task_entry)
        excluded_ports: set = set()
        max_attempts = max(1, len(self.workers))
        last_worker: Optional[CopilotWorker] = None
        collected_bytes = 0
        collected_chunks: list = []
        success = False

        try:
            for attempt in range(max_attempts):
                worker = await self.acquire_worker(exclude_ports=excluded_ports)
                last_worker = worker
                task_entry["worker"] = f"{worker.name}:{worker.port}"
                self._push({"type": "task_start", "task": dict(task_entry),
                            "active": self.active_count,
                            "workers": self._worker_brief()})
                try:
                    async for chunk in worker.stream_query(prompt, reset_chat=reset_chat, file_paths=file_paths):
                        collected_bytes += len(chunk.encode("utf-8", errors="ignore"))
                        collected_chunks.append(chunk)
                        yield chunk
                    success = True
                    break
                except Exception as e:
                    if not collected_chunks and (attempt + 1) < max_attempts:
                        excluded_ports.add(worker.port)
                        print(f"[!] [페일오버] {worker.name}(:{worker.port}) 실패 ({type(e).__name__}: {e}), 다음 계정으로 전환합니다.")
                        continue
                    raise
                finally:
                    worker._reserved = False
        finally:
            if last_worker is not None:
                self._finalize_task(
                    task_id=task_id,
                    task_entry=task_entry,
                    prompt=prompt,
                    collected_chunks=collected_chunks,
                    collected_bytes=collected_bytes,
                    worker=last_worker,
                    t_start=t_start,
                    source=source,
                    client_app=client_app,
                    client_version=client_version,
                    prompt_bytes=prompt_bytes,
                    ip_addr=ip_addr,
                    success=success,
                )
            self._finish_counters(task_id, True)

    async def query(self, prompt: str, file_paths: Optional[List[str]] = None,
                    source: str = "api", client_app: str = "", client_version: str = "",
                    prompt_bytes: int = 0, ip_addr: str = "") -> str:
        """비스트리밍 질의: 응답 완료 전 실패(부분 출력 후 중단 포함) 시 다음 가용 워커로 전체 재시도한다."""
        task_id, preview, task_entry = self._enqueue_task(prompt, source)
        t_start = time.time()
        self._mark_running(task_id, preview, task_entry)
        excluded_ports: set = set()
        max_attempts = max(1, len(self.workers))
        last_worker: Optional[CopilotWorker] = None
        collected_chunks: list = []
        collected_bytes = 0
        success = False

        try:
            for attempt in range(max_attempts):
                worker = await self.acquire_worker(exclude_ports=excluded_ports)
                last_worker = worker
                task_entry["worker"] = f"{worker.name}:{worker.port}"
                self._push({"type": "task_start", "task": dict(task_entry),
                            "active": self.active_count,
                            "workers": self._worker_brief()})
                attempt_chunks: list = []
                attempt_bytes = 0
                try:
                    async for chunk in worker.stream_query(prompt, reset_chat=True, file_paths=file_paths):
                        attempt_bytes += len(chunk.encode("utf-8", errors="ignore"))
                        attempt_chunks.append(chunk)
                    collected_chunks = attempt_chunks
                    collected_bytes = attempt_bytes
                    success = True
                    return "".join(collected_chunks).strip()
                except Exception as e:
                    if (attempt + 1) < max_attempts:
                        excluded_ports.add(worker.port)
                        print(f"[!] [버퍼 페일오버] {worker.name}(:{worker.port}) 중단 ({type(e).__name__}: {e}), 다음 계정으로 전체 재시도합니다.")
                        continue
                    collected_chunks = attempt_chunks
                    collected_bytes = attempt_bytes
                    raise
                finally:
                    worker._reserved = False
        finally:
            if last_worker is not None:
                self._finalize_task(
                    task_id=task_id,
                    task_entry=task_entry,
                    prompt=prompt,
                    collected_chunks=collected_chunks,
                    collected_bytes=collected_bytes,
                    worker=last_worker,
                    t_start=t_start,
                    source=source,
                    client_app=client_app,
                    client_version=client_version,
                    prompt_bytes=prompt_bytes,
                    ip_addr=ip_addr,
                    success=success,
                )
            self._finish_counters(task_id, True)
        return ""

    async def generate_image(
        self,
        prompt: str,
        *,
        file_paths: Optional[List[str]] = None,
        reset_chat: bool = True,
        timeout_sec: float = 240.0,
        min_bytes: int = 50_000,
        source: str = "images",
        client_app: str = "",
        client_version: str = "",
        prompt_bytes: int = 0,
        ip_addr: str = "",
    ) -> Dict[str, Any]:
        """이미지 생성: 완료 시까지 버퍼링하고 정책 거부를 제외한 실패/할당량 소진 시 다음 워커로 페일오버한다."""
        task_id, preview, task_entry = self._enqueue_task(prompt, source)
        t_start = time.time()
        self._mark_running(task_id, preview, task_entry)
        excluded_ports: set = set()
        max_attempts = max(1, len(self.workers))
        last_worker: Optional[CopilotWorker] = None
        collected_bytes = 0
        resp_text = ""
        success = False

        try:
            for attempt in range(max_attempts):
                worker = await self.acquire_worker(exclude_ports=excluded_ports)
                last_worker = worker
                task_entry["worker"] = f"{worker.name}:{worker.port}"
                self._push({"type": "task_start", "task": dict(task_entry),
                            "active": self.active_count,
                            "workers": self._worker_brief()})
                try:
                    out = await worker.generate_image(
                        prompt,
                        file_paths=file_paths,
                        reset_chat=reset_chat,
                        timeout_sec=timeout_sec,
                        min_bytes=min_bytes,
                    )
                    collected_bytes = sum(int(im.get("bytes_len", 0)) for im in out.get("images", []))
                    resp_text = str(out.get("text") or "")
                    success = True
                    return out
                except CopilotPolicyRefusalError:
                    raise
                except Exception as e:
                    if (attempt + 1) < max_attempts:
                        excluded_ports.add(worker.port)
                        print(f"[!] [이미지 페일오버] {worker.name}(:{worker.port}) 실패 ({type(e).__name__}: {e}), 다음 계정으로 전환합니다.")
                        continue
                    raise
                finally:
                    worker._reserved = False
        finally:
            if last_worker is not None:
                self._finalize_task(
                    task_id=task_id,
                    task_entry=task_entry,
                    prompt=prompt,
                    collected_chunks=[],
                    collected_bytes=collected_bytes,
                    worker=last_worker,
                    t_start=t_start,
                    source=source,
                    client_app=client_app,
                    client_version=client_version,
                    prompt_bytes=prompt_bytes,
                    ip_addr=ip_addr,
                    success=success,
                    model="copilot-image",
                    full_response=resp_text,
                )
            self._finish_counters(task_id, True)
        raise RuntimeError("사용 가능한 Copilot 워커가 없습니다.")

    async def new_chat(self):
        worker = await self.acquire_worker()
        try:
            return await worker.new_chat()
        finally:
            worker._reserved = False

    async def connect(self):
        worker = await self.acquire_worker()
        try:
            return await worker.connect()
        finally:
            worker._reserved = False

    async def ensure_browser_running(self):
        if self.mode == "hot" and self.workers:
            await self.workers[0].ensure_running()

    async def close(self):
        for w in self.workers:
            await w.close()

CopilotEngine = CopilotPool

if __name__ == "__main__":
    pool = CopilotPool()
    print("현재 풀 상태:", pool.get_status_summary())
