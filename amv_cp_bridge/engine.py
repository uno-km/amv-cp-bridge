# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Copilot 365 Bridge Engine - Ephemeral Zero-Leak Multi-Worker Edition
Microsoft 365 Copilot (Enterprise / Edu) CDP 기반 듀얼 워커 풀 및 무누수(Zero-Leak) 라이프사이클 엔진.
- 질문-답변 완료 즉시 Edge 브라우저 프로세스 트리 완전 강제 종료 (0MB 메모리 유지)
- 선입선출(FIFO) 순차 큐 직렬화 처리로 브라우저 충돌 및 세션 오염 원천 차단
- 포트 9333 (기본 계정) 사용 중일 때 포트 9334 (아주대 계정)로 자동 라우팅
"""

import sys
import os
import re
import json
import time
import uuid
import asyncio
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, AsyncGenerator, List, Dict, Any

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

# 기본 동작 모드: 로컬 메모리 누수 방지를 위해 단발성 즉시 종료(Ephemeral Mode) 활성화
DEFAULT_EPHEMERAL = os.environ.get("COPILOT_EPHEMERAL_MODE", "true").lower() in ("true", "1", "yes")

class CopilotWorker:
    def __init__(self, port: int, name: str, profile_dir: str, mode: str = "cold", standby_timeout_sec: int = 300, ephemeral_mode: Optional[bool] = None):
        self.port = port
        self.name = name
        self.profile_dir = profile_dir
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
        self.login_state: str = _read_login_states().get(str(port), "unknown")
        self._standby_task: Optional[asyncio.Task] = None
        self._standby_deadline: Optional[float] = None

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
            loop = asyncio.get_event_loop()
        self._standby_task = loop.create_task(self._standby_countdown())
        print(f"[*] [{self.name}] 🔥 핫로딩 모드: 웜 스탠바이 대기 중 ({self.standby_timeout_sec}초 유지)")

    async def _standby_countdown(self):
        """스탠바이 시간 경과 후 프로세스 회수"""
        try:
            await asyncio.sleep(self.standby_timeout_sec)
            if not self.is_busy():
                print(f"[+] [{self.name}] ⏱️ 웜 스탠바이({self.standby_timeout_sec}초) 만료 — Edge 프로세스 완전 종료 (0MB 회수)")
                await self.cleanup()
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
        return self._lock.locked()

    async def ensure_running(self, visible: bool = False):
        """엣지 브라우저가 꺼져있으면 디버깅 모드로 자동 기동"""
        if self.is_alive():
            return True

        print(f"[!] [{self.name}] 포트 {self.port} 세션 기동 중...")
        edge_path = _find_edge_binary()
        args = [
            edge_path,
            f"--remote-debugging-port={int(self.port)}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if not visible:
            args.append("--window-position=-3000,-3000")  # 모니터 밖으로 던져 화면 노출 방지
        subprocess.Popen(args + [COPILOT_URL])

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

    def kill_browser_process(self):
        """포트에 바인딩된 Edge 브라우저 프로세스 트리 전체를 완전 강제 종료"""
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
                print(f"[+] [{self.name}] Edge 프로세스 트리(PID {pid}) 완전 종료")
            except Exception as e:
                print(f"[!] [{self.name}] Edge 프로세스(PID {pid}) 종료 처리 중 경고: {e}")

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
            "진행 중…", "진행 중..."
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

    async def _wait_for_composer(self, page: Page, timeout: float = COMPOSER_TIMEOUT_SEC) -> bool:
        """로그인 리다이렉트가 끝나고 Copilot 입력창이 보일 때까지 대기한다."""
        deadline = time.time() + timeout
        textbox = page.locator(COMPOSER_SELECTOR).first
        while time.time() < deadline:
            if not _is_login_url(page.url) and await textbox.is_visible():
                return True
            await asyncio.sleep(0.5)
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
        """로그인할 수 있도록 Edge 창을 화면에 띄우고, 입력창이 보이면 연결 완료로 기록한다."""
        async with self._lock:
            try:
                self.kill_browser_process()
                await self.ensure_running(visible=True)
                page = await self.connect()
                connected = await self._wait_for_composer(page, timeout)
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

    async def stream_query(self, prompt: str, reset_chat: bool = True, file_paths: Optional[List[str]] = None) -> AsyncGenerator[str, None]:
        """질문을 던지고 실시간 스트리밍 텍스트 델타를 yield"""
        async with self._lock:
            self._cancel_standby()
            try:
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

                emitted_text = ""
                stable_count = 0
                timeout = 180
                start_gen = time.time()

                while time.time() - start_gen < timeout:
                    info = await page.evaluate("""() => {
                        const articles = Array.from(document.querySelectorAll('div[role="article"], .fai-CopilotMessage'))
                            .filter(a => !a.classList.contains('fai-UserMessage') && !(a.innerText || '').startsWith('You said'));
                        if (articles.length === 0) return { text: "", isDone: false };
                        const last = articles[articles.length - 1];
                        const copyBtn = last.querySelector('button[aria-label*="복사"], button[title*="복사"], button[aria-label*="Copy"]');
                        const stopBtn = document.querySelector('button[aria-label*="중지"], button[aria-label*="Stop"], button[title*="중지"]');
                        return {
                            text: last.innerText || "",
                            isDone: !!copyBtn && !stopBtn
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

                    if is_done and len(clean_current) > 0:
                        break

                    if stable_count >= 30 and len(clean_current) > 0:
                        break

                    await asyncio.sleep(0.5)

                if not emitted_text:
                    raise TimeoutError(f"Copilot 응답 없음: 메시지 전송 후 {timeout}초 안에 응답을 받지 못했습니다.")

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

    async def close(self):
        self._cancel_standby()
        await self.cleanup()
        self.kill_browser_process()


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
    """멀티 계정 로드밸런싱 풀 관리자 (계정 간 자동 우회) 및 순차 큐 직렬화 엔진"""
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
        self.workers: List[CopilotWorker] = [
            CopilotWorker(
                port=int(acc["port"]),
                name=acc["name"],
                profile_dir=acc["profile_dir"],
                mode=self.mode,
                standby_timeout_sec=self.standby_timeout_sec
            )
            for acc in accounts
        ]
        self._queue_lock = asyncio.Lock()
        self.queued_count: int = 0
        self.active_count: int = 0
        self.current_task: Optional[str] = None
        self.task_start_time: Optional[float] = None
        # 실시간 태스크 큐 추적 [{id, source, preview, status, worker, queued_at, started_at}]
        self._task_queue: List[Dict[str, Any]] = []

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

    async def acquire_worker(self) -> CopilotWorker:
        """가장 빠르게 사용 가능한 워커 선택 (순서대로 탐색, 모두 바쁘면 대기)"""
        for w in self.workers:
            if not w.is_busy():
                return w

        if len(self.workers) > 1:
            print("[*] [로드밸런서] 모든 계정 사용 중. 먼저 완료되는 세션으로 대기 대열에 진입합니다...")
        while True:
            for w in self.workers:
                if not w.is_busy():
                    print(f"[+] [로드밸런서] {w.name}(포트 {w.port}) 확보 완료!")
                    return w
            await asyncio.sleep(0.3)

    def _worker_brief(self) -> List[Dict[str, Any]]:
        now = time.time()
        return [
            {
                "name": w.name,
                "port": w.port,
                "is_busy": w.is_busy(),
                "is_alive": w.is_alive(),
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

    async def stream_query(self, prompt: str, reset_chat: bool = True, file_paths: Optional[List[str]] = None,
                           source: str = "api", client_app: str = "", client_version: str = "",
                           prompt_bytes: int = 0, ip_addr: str = "") -> AsyncGenerator[str, None]:
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
        t_start = time.time()
        try:
            async with self._queue_lock:
                self.queued_count = max(0, self.queued_count - 1)
                self.active_count += 1
                self.current_task = preview
                self.task_start_time = time.time()
                task_entry["status"] = "running"
                task_entry["started_at"] = time.time()

                worker = await self.acquire_worker()
                task_entry["worker"] = f"{worker.name}:{worker.port}"
                self._push({"type": "task_start", "task": dict(task_entry),
                            "active": self.active_count,
                            "workers": self._worker_brief()})

                collected_bytes = 0
                collected_chunks: list = []
                success = True
                try:
                    async for chunk in worker.stream_query(prompt, reset_chat=reset_chat, file_paths=file_paths):
                        collected_bytes += len(chunk.encode("utf-8", errors="ignore"))
                        collected_chunks.append(chunk)
                        yield chunk
                except Exception as e:
                    success = False
                    raise e
                finally:
                    duration_ms = (time.time() - t_start) * 1000
                    tokens_est = max(1, int(collected_bytes / 4.2)) if collected_bytes > 0 else 0
                    queue_wait = (task_entry["started_at"] or t_start) - task_entry["queued_at"]
                    task_entry.update({"status": "done" if success else "error",
                                       "done_at": time.time(), "success": success,
                                       "tokens": tokens_est})
                    self._push({"type": "task_done", "task": dict(task_entry),
                                "active": max(0, self.active_count - 1),
                                "stats_dirty": True, "workers": self._worker_brief()})
                    try:
                        telemetry_db.record_query(
                            prompt=prompt, duration_ms=duration_ms,
                            bytes_len=collected_bytes, worker_port=worker.port,
                            account_label=worker.name, model="gpt-5.6-sol",
                            source=source, success=success,
                            task_id=task_id, client_app=client_app,
                            client_version=client_version,
                            queue_wait_ms=queue_wait * 1000,
                            prompt_bytes=prompt_bytes, ip_addr=ip_addr,
                            full_response="".join(collected_chunks),
                        )
                    except Exception as _db_err:
                        print(f"[!] telemetry record_query 실패 (stream): {_db_err}")
        finally:
            self.active_count = max(0, self.active_count - 1)
            if self.active_count == 0:
                self.current_task = None
                self.task_start_time = None

    async def query(self, prompt: str, file_paths: Optional[List[str]] = None,
                    source: str = "api", client_app: str = "", client_version: str = "",
                    prompt_bytes: int = 0, ip_addr: str = "") -> str:
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
        t_start = time.time()
        try:
            async with self._queue_lock:
                self.queued_count = max(0, self.queued_count - 1)
                self.active_count += 1
                self.current_task = preview
                self.task_start_time = time.time()
                task_entry["status"] = "running"
                task_entry["started_at"] = time.time()

                worker = await self.acquire_worker()
                task_entry["worker"] = f"{worker.name}:{worker.port}"
                self._push({"type": "task_start", "task": dict(task_entry),
                            "active": self.active_count,
                            "workers": self._worker_brief()})
                success = True
                res = ""
                try:
                    res = await worker.query(prompt, file_paths=file_paths)
                    return res
                except Exception as e:
                    success = False
                    raise e
                finally:
                    duration_ms = (time.time() - t_start) * 1000
                    bytes_len = len(res.encode("utf-8", errors="ignore")) if res else 0
                    tokens_est = max(1, int(bytes_len / 4.2)) if bytes_len > 0 else 0
                    queue_wait = (task_entry["started_at"] or t_start) - task_entry["queued_at"]
                    task_entry.update({"status": "done" if success else "error",
                                       "done_at": time.time(), "success": success,
                                       "tokens": tokens_est})
                    self._push({"type": "task_done", "task": dict(task_entry),
                                "active": max(0, self.active_count - 1),
                                "stats_dirty": True, "workers": self._worker_brief()})
                    try:
                        telemetry_db.record_query(
                            prompt=prompt, duration_ms=duration_ms,
                            bytes_len=bytes_len, worker_port=worker.port,
                            account_label=worker.name, model="gpt-5.6-sol",
                            source=source, success=success,
                            task_id=task_id, client_app=client_app,
                            client_version=client_version,
                            queue_wait_ms=queue_wait * 1000,
                            prompt_bytes=prompt_bytes, ip_addr=ip_addr,
                            full_response=res,
                        )
                    except Exception as _db_err:
                        print(f"[!] telemetry record_query 실패 (query): {_db_err}")
        finally:
            self.active_count = max(0, self.active_count - 1)
            if self.active_count == 0:
                self.current_task = None
                self.task_start_time = None

    async def new_chat(self):
        async with self._queue_lock:
            worker = await self.acquire_worker()
            return await worker.new_chat()

    async def connect(self):
        worker = await self.acquire_worker()
        return await worker.connect()

    async def ensure_browser_running(self):
        if self.mode == "hot":
            await self.workers[0].ensure_running()

    async def close(self):
        for w in self.workers:
            await w.close()

CopilotEngine = CopilotPool

if __name__ == "__main__":
    pool = CopilotPool()
    print("현재 풀 상태:", pool.get_status_summary())
