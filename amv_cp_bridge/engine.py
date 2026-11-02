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
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

COPILOT_URL = "https://m365.cloud.microsoft/chat"


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
    def __init__(self, port: int, name: str, profile_dir: str, ephemeral_mode: bool = DEFAULT_EPHEMERAL):
        self.port = port
        self.name = name
        self.profile_dir = profile_dir
        self.ephemeral_mode = ephemeral_mode
        self.cdp_url = f"http://127.0.0.1:{port}"
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._lock = asyncio.Lock()

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

    async def ensure_running(self):
        """엣지 브라우저가 꺼져있으면 디버깅 모드로 자동 기동"""
        if self.is_alive():
            return True

        print(f"[!] [{self.name}] 포트 {self.port} 세션 기동 중...")
        edge_path = _find_edge_binary()
        subprocess.Popen([
            edge_path,
            f"--remote-debugging-port={int(self.port)}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-position=-3000,-3000",  # 모니터 밖으로 던져 화면 노출 방지
            COPILOT_URL
        ])

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
            if "m365.cloud.microsoft" in url or "copilot.microsoft" in url:
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
        pids = self.get_listening_pids()
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
            "자세히 살펴보는 중…", "자세히 살펴보는 중..."
        }
        for p in skip_phrases:
            text = text.replace(p, "")

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

    async def stream_query(self, prompt: str, reset_chat: bool = True) -> AsyncGenerator[str, None]:
        """질문을 던지고 실시간 스트리밍 텍스트 델타를 yield"""
        async with self._lock:
            try:
                page = await self.connect()

                if reset_chat:
                    await self.new_chat()

                textbox = page.locator("[contenteditable='true'], .fai-EditorInput__input, textarea, [role='textbox']:not([aria-readonly='true'])").first
                await textbox.wait_for(state="visible", timeout=15000)
                await textbox.click()
                await asyncio.sleep(0.3)
                try:
                    await page.keyboard.insert_text(prompt)
                except Exception:
                    await textbox.fill(prompt)
                await asyncio.sleep(0.3)
                await page.keyboard.press("Enter")

                start_wait = time.time()
                while time.time() - start_wait < 15:
                    has_msg = await page.evaluate("""() => {
                        return document.querySelectorAll('div[role="article"], .fai-CopilotMessage').length > 0;
                    }""")
                    if has_msg:
                        break
                    await asyncio.sleep(0.5)

                emitted_text = ""
                stable_count = 0
                timeout = 180
                start_gen = time.time()

                while time.time() - start_gen < timeout:
                    info = await page.evaluate("""() => {
                        const articles = Array.from(document.querySelectorAll('div[role="article"], .fai-CopilotMessage'));
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

            finally:
                if self.ephemeral_mode:
                    await self.cleanup()
                    self.kill_browser_process()

    async def query(self, prompt: str) -> str:
        collected = []
        async for chunk in self.stream_query(prompt):
            collected.append(chunk)
        return "".join(collected).strip()

    async def close(self):
        await self.cleanup()
        self.kill_browser_process()


CONFIG_DIR = os.path.join(str(Path.home()), ".amv_cp_bridge")
CONFIG_PATH = os.path.join(CONFIG_DIR, "accounts.json")

def _load_accounts() -> List[Dict[str, Any]]:
    """설정 파일에서 계정 목록 로드. 없으면 기본 계정으로 초기화."""
    defaults = [
        {"port": 9333, "name": "기본 계정", "profile_dir": os.path.join(str(Path.home()), "copilot_profile_default")},
        {"port": 9334, "name": "보조 계정", "profile_dir": os.path.join(str(Path.home()), "copilot_profile_secondary")},
    ]
    if os.path.isfile(CONFIG_PATH):
        try:
            import json
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list) and len(loaded) > 0:
                return loaded
        except Exception:
            pass
    os.makedirs(CONFIG_DIR, exist_ok=True)
    import json
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2)
    return defaults


class CopilotPool:
    """멀티 계정 로드밸런싱 풀 관리자 (계정 간 자동 우회) 및 순차 큐 직렬화 엔진"""
    def __init__(self, ephemeral_mode: bool = DEFAULT_EPHEMERAL):
        self.ephemeral_mode = ephemeral_mode
        accounts = _load_accounts()
        self.workers: List[CopilotWorker] = [
            CopilotWorker(
                port=int(acc["port"]),
                name=acc["name"],
                profile_dir=acc["profile_dir"],
                ephemeral_mode=self.ephemeral_mode
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
        for w in self.workers:
            busy = w.is_busy()
            alive = w.is_alive()
            pids = w.get_listening_pids()
            if not busy:
                available_cnt += 1
            st = "BUSY" if busy else ("IDLE" if alive else "OFFLINE_0MB")
            worker_details.append({
                "name": w.name,
                "port": w.port,
                "status": st,
                "is_busy": busy,
                "is_alive": alive,
                "pids": pids,
                "memory_mb": 0 if not alive else (len(pids) * 35) # 추정치
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
            "ephemeral_mode": self.ephemeral_mode,
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

    def _push(self, event: dict):
        """이벤트 발행 (동기 컨텍스트에서도 안전하게 호출)."""
        event_bus.publish(event)

    async def stream_query(self, prompt: str, reset_chat: bool = True, source: str = "api",
                           client_app: str = "", client_version: str = "",
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
                            "workers": [{"name": w.name, "port": w.port,
                                         "is_busy": w.is_busy()} for w in self.workers]})

                collected_bytes = 0
                collected_chunks: list = []
                success = True
                try:
                    async for chunk in worker.stream_query(prompt, reset_chat=reset_chat):
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
                                "stats_dirty": True})
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

    async def query(self, prompt: str, source: str = "api",
                    client_app: str = "", client_version: str = "",
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
                            "workers": [{"name": w.name, "port": w.port,
                                         "is_busy": w.is_busy()} for w in self.workers]})
                success = True
                res = ""
                try:
                    res = await worker.query(prompt)
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
                                "stats_dirty": True})
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
        if not self.ephemeral_mode:
            await self.workers[0].ensure_running()

    async def close(self):
        for w in self.workers:
            await w.close()

CopilotEngine = CopilotPool

if __name__ == "__main__":
    pool = CopilotPool()
    print("현재 풀 상태:", pool.get_status_summary())
