# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""Unit tests for dynamic account add/delete APIs and visible login window positioning."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from amv_cp_bridge import engine, gateway


class TestAccountManagement(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.cfg_dir = self.tmp_path / ".amv_cp_bridge"
        self.cfg_dir.mkdir(parents=True, exist_ok=True)
        self.cfg_path = self.cfg_dir / "accounts.json"
        self.state_path = self.cfg_dir / "account_state.json"
        self.meta_path = self.cfg_dir / "account_meta.json"

        self.initial_accounts = [
            {"port": 9333, "name": "기본 계정", "profile_dir": str(self.tmp_path / "prof_9333")},
        ]
        self.cfg_path.write_text(json.dumps(self.initial_accounts, ensure_ascii=False), encoding="utf-8")
        self.state_path.write_text(json.dumps({"9333": "ok"}), encoding="utf-8")

        self.patches = [
            patch.object(engine, "CONFIG_DIR", str(self.cfg_dir)),
            patch.object(engine, "CONFIG_PATH", str(self.cfg_path)),
            patch.object(engine, "LOGIN_STATE_PATH", str(self.state_path)),
            patch.object(engine, "ACCOUNT_META_PATH", str(self.meta_path)),
            patch.object(engine, "load_settings", return_value={"mode": "cold", "standby_timeout_sec": 300}),
            patch.object(engine.event_bus, "publish"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()

    def test_pool_add_and_remove_account_persists(self) -> None:
        pool = engine.CopilotPool()
        self.assertEqual([w.port for w in pool.workers], [9333])

        with patch.object(engine, "_is_port_in_use", return_value=False):
            added = pool.add_account("학교 계정", browser="edge")
        self.assertEqual(added["port"], 9334)
        self.assertEqual(added["name"], "학교 계정")
        self.assertEqual(added["browser"], "edge")
        self.assertTrue(Path(added["profile_dir"]).is_dir())
        self.assertEqual([w.port for w in pool.workers], [9333, 9334])

        saved = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[1]["port"], 9334)
        self.assertEqual(saved[1]["browser"], "edge")

        # Duplicate port and empty name rejected
        with self.assertRaises(ValueError):
            pool.add_account("중복", port=9334)
        with self.assertRaises(ValueError):
            pool.add_account("   ")

        # Mark 9334 login_state + meta and ensure removal cleans up config + state + meta
        self.state_path.write_text(json.dumps({"9333": "ok", "9334": "required"}), encoding="utf-8")
        self.meta_path.write_text(json.dumps({"9333": {"identity": "a@example.com"}, "9334": {"identity": "b@university.edu"}}), encoding="utf-8")
        new_worker = pool.workers[1]
        with patch.object(new_worker, "cleanup", new=AsyncMock()), patch.object(new_worker, "kill_browser_process"):
            removed = asyncio.run(pool.remove_account(9334))

        self.assertTrue(removed["ok"])
        self.assertEqual(removed["port"], 9334)
        self.assertEqual([w.port for w in pool.workers], [9333])
        self.assertEqual(len(json.loads(self.cfg_path.read_text(encoding="utf-8"))), 1)
        self.assertNotIn("9334", json.loads(self.state_path.read_text(encoding="utf-8")))
        self.assertNotIn("9334", json.loads(self.meta_path.read_text(encoding="utf-8")))

        # Cannot remove the last remaining account
        with self.assertRaises(ValueError):
            asyncio.run(pool.remove_account(9333))

    def test_gateway_accounts_rest_crud_and_busy_guard(self) -> None:
        pool = engine.CopilotPool()
        with patch.object(gateway, "engine", pool), patch.object(engine, "_is_port_in_use", return_value=False):
            client = TestClient(gateway.app)

            r_list = client.get("/api/accounts")
            self.assertEqual(r_list.status_code, 200)
            self.assertEqual(len(r_list.json()["accounts"]), 1)

            r_add = client.post("/api/accounts", json={"name": "서브 계정", "port": 9336, "browser": "chrome"})
            self.assertEqual(r_add.status_code, 201)
            self.assertEqual(r_add.json()["account"]["port"], 9336)

            r_dup = client.post("/api/accounts", json={"name": "중복 포트", "port": 9336})
            self.assertEqual(r_dup.status_code, 409)

            # Busy worker cannot be deleted (HTTP 409)
            w_sub = next(w for w in pool.workers if w.port == 9336)
            w_sub._reserved = True
            try:
                r_busy = client.delete("/api/accounts/9336")
                self.assertEqual(r_busy.status_code, 409)
            finally:
                w_sub._reserved = False

            with patch.object(w_sub, "cleanup", new=AsyncMock()), patch.object(w_sub, "kill_browser_process"):
                r_del = client.delete("/api/accounts/9336")
            self.assertEqual(r_del.status_code, 200)
            self.assertEqual(len(r_del.json()["workers"]), 1)

            r_missing = client.delete("/api/accounts/9999")
            self.assertEqual(r_missing.status_code, 404)

            r_dash = client.get("/dashboard")
            self.assertEqual(r_dash.status_code, 200)
            self.assertIn("openAddAcctModal", r_dash.text)
            self.assertIn("/api/accounts", r_dash.text)

    def test_visible_launch_forces_onscreen_window_position_and_cdp_bounds(self) -> None:
        w = engine.CopilotWorker(9334, "Edu", str(self.tmp_path / "edu"))
        popen_cmds: list[list[str]] = []

        def fake_popen(cmd, *args, **kwargs):
            popen_cmds.append(list(cmd))
            return MagicMock()

        with patch.object(w, "is_alive", side_effect=[False, True]), patch.object(
            engine.subprocess, "Popen", side_effect=fake_popen
        ):
            asyncio.run(w.ensure_running(visible=True))

        self.assertEqual(len(popen_cmds), 1)
        self.assertIn("--window-position=120,80", popen_cmds[0])
        self.assertIn("--window-size=1080,840", popen_cmds[0])
        self.assertNotIn("--window-position=-3000,-3000", popen_cmds[0])

        popen_cmds.clear()
        with patch.object(w, "is_alive", side_effect=[False, True]), patch.object(
            engine.subprocess, "Popen", side_effect=fake_popen
        ):
            asyncio.run(w.ensure_running(visible=False))
        self.assertIn("--window-position=-3000,-3000", popen_cmds[0])

        # Verify open_login invokes _bring_window_to_front (CDP setWindowBounds + bring_to_front)
        mock_cdp = MagicMock()
        mock_cdp.send = AsyncMock(side_effect=[{"windowId": 42}, {}])
        mock_cdp.detach = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.new_cdp_session = AsyncMock(return_value=mock_cdp)
        mock_page = MagicMock()
        mock_page.bring_to_front = AsyncMock()
        w.context = mock_ctx

        asyncio.run(w._bring_window_to_front(mock_page))
        mock_cdp.send.assert_any_call("Browser.getWindowForTarget")
        mock_cdp.send.assert_any_call(
            "Browser.setWindowBounds",
            {
                "windowId": 42,
                "bounds": {"left": 120, "top": 80, "width": 1080, "height": 840, "windowState": "normal"},
            },
        )
        mock_page.bring_to_front.assert_awaited_once()

    def test_verify_login_live_ok_and_sso_redirect(self) -> None:
        prof_9333 = self.tmp_path / "prof_9333" / "Default"
        prof_9333.mkdir(parents=True, exist_ok=True)
        (prof_9333 / "Preferences").write_text(
            json.dumps({"account_info": [{"email": "user@company.com", "full_name": "Example User"}]}),
            encoding="utf-8",
        )
        w = engine.CopilotWorker(9333, "기본 계정", str(self.tmp_path / "prof_9333"), mode="cold")

        mock_page = MagicMock()
        mock_page.url = "https://copilot.cloud.microsoft/chat"
        mock_page.is_closed.return_value = False
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="Example User/Engineering Team")

        mock_ctx = MagicMock()
        mock_ctx.new_page = AsyncMock(return_value=mock_page)
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_browser.contexts = [mock_ctx]
        mock_browser.close = AsyncMock()

        w.browser = mock_browser
        w.context = mock_ctx

        with patch.object(w, "is_alive", return_value=True), \
             patch.object(w, "ensure_running", new=AsyncMock(return_value=True)), \
             patch.object(w, "_wait_for_composer", new=AsyncMock(return_value=True)), \
             patch.object(w, "cleanup", new=AsyncMock()), \
             patch.object(w, "kill_browser_process"):
            res_ok = asyncio.run(w.verify_login(timeout=5.0))

        self.assertTrue(res_ok["ok"])
        self.assertEqual(res_ok["login_state"], "ok")
        self.assertEqual(res_ok["login_identity"], "Example User/Engineering Team")
        self.assertEqual(res_ok["verify_detail"], "verified_live")
        self.assertGreater(res_ok["verified_at"], 0.0)
        saved_meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_meta["9333"]["identity"], "Example User/Engineering Team")

        # Expired SSO session -> required with sso_redirect + profile hint fallback
        mock_page.url = "https://login.microsoftonline.com/common/oauth2/authorize"
        with patch.object(w, "is_alive", return_value=False), \
             patch.object(w, "ensure_running", new=AsyncMock(return_value=True)), \
             patch.object(w, "_wait_for_composer", new=AsyncMock(return_value=False)), \
             patch.object(w, "cleanup", new=AsyncMock()), \
             patch.object(w, "kill_browser_process"):
            res_fail = asyncio.run(w.verify_login(timeout=5.0))

        self.assertFalse(res_fail["ok"])
        self.assertEqual(res_fail["login_state"], "required")
        self.assertEqual(res_fail["verify_detail"], "sso_redirect")
        self.assertEqual(res_fail["login_identity"], "Example User (user@company.com)")

    def test_gateway_verify_endpoints_and_guards(self) -> None:
        pool = engine.CopilotPool()
        fake_res = {
            "ok": True,
            "port": 9333,
            "name": "기본 계정",
            "login_state": "ok",
            "login_identity": "Eunho Kim (eunho@company.com)",
            "verified_at": 1700000000.0,
            "verify_detail": "verified_live",
        }
        with patch.object(gateway, "engine", pool):
            client = TestClient(gateway.app)
            with patch.object(pool.workers[0], "verify_login", new=AsyncMock(return_value=fake_res)):
                r_one = client.post("/api/accounts/9333/verify")
                self.assertEqual(r_one.status_code, 200)
                self.assertTrue(r_one.json()["ok"])
                self.assertEqual(r_one.json()["result"]["login_identity"], "Eunho Kim (eunho@company.com)")

                r_all = client.post("/api/accounts/verify")
                self.assertEqual(r_all.status_code, 200)
                self.assertEqual(len(r_all.json()["results"]), 1)

            r_missing = client.post("/api/accounts/9999/verify")
            self.assertEqual(r_missing.status_code, 404)

            pool.workers[0]._reserved = True
            try:
                r_busy = client.post("/api/accounts/9333/verify")
                self.assertEqual(r_busy.status_code, 409)
            finally:
                pool.workers[0]._reserved = False

    def test_wait_for_composer_fast_fails_even_if_tile_stays_visible(self) -> None:
        import time as _time
        w = engine.CopilotWorker(9334, "Edu", str(self.tmp_path / "edu"))
        mock_page = MagicMock()
        mock_page.url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        mock_page.mouse = MagicMock()
        mock_page.mouse.click = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={"email": "student@university.edu", "matchesPref": False, "x": 200, "y": 125}
        )

        mock_loc = MagicMock()
        mock_loc.is_visible = AsyncMock(return_value=False)
        mock_page.locator.return_value.first = mock_loc

        t0 = _time.time()
        ok = asyncio.run(w._wait_for_composer(mock_page, timeout=20.0, fast_fail=True, allow_tile_autoclick=False))
        elapsed_no_click = _time.time() - t0
        self.assertFalse(ok)
        self.assertLess(elapsed_no_click, 4.0)
        mock_page.mouse.click.assert_not_awaited()

        t1 = _time.time()
        ok2 = asyncio.run(w._wait_for_composer(mock_page, timeout=20.0, fast_fail=True, allow_tile_autoclick=True))
        elapsed_with_click = _time.time() - t1
        self.assertFalse(ok2)
        self.assertLess(elapsed_with_click, 11.0)
        self.assertEqual(mock_page.mouse.click.await_count, 1)
        self.assertEqual(w._last_selected_email, "student@university.edu")

    def test_login_endpoint_rejects_non_interactive_desktop(self) -> None:
        pool = engine.CopilotPool()
        with patch.object(gateway, "engine", pool), \
             patch.object(gateway, "is_non_interactive_desktop", return_value=True):
            client = TestClient(gateway.app)
            r = client.post("/api/accounts/9333/login")
            self.assertEqual(r.status_code, 409)
            self.assertIn("start_gui.bat", r.json()["detail"])

    def test_ensure_running_visible_sets_shownormal_startupinfo(self) -> None:
        w = engine.CopilotWorker(9334, "Edu", str(self.tmp_path / "edu"))
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock()

        with patch.object(w, "is_alive", side_effect=[False, True]), \
             patch.object(engine.subprocess, "Popen", side_effect=fake_popen):
            ok = asyncio.run(w.ensure_running(visible=True))

        self.assertTrue(ok)
        self.assertIn("--disable-session-crashed-bubble", captured["cmd"])
        self.assertIn("--hide-crash-restore-bubble", captured["cmd"])
        if engine.sys.platform == "win32":
            si = captured["kwargs"].get("startupinfo")
            self.assertIsNotNone(si)
            self.assertEqual(si.wShowWindow, 1)
            self.assertTrue(bool(si.dwFlags & engine.subprocess.STARTF_USESHOWWINDOW))

    def test_pick_signed_in_account_tile_filters_windows_tile(self) -> None:
        w = engine.CopilotWorker(9334, "Edu", str(self.tmp_path / "edu"))
        w.login_identity = "User Name, Work Account"
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=None)
        res = asyncio.run(w._pick_signed_in_account_tile(mock_page))
        self.assertIsNone(res)
        # Ensure preferred_email passed to JS is empty when identity lacks '@'
        args, _ = mock_page.evaluate.await_args
        self.assertEqual(args[1], "")
        self.assertIn("Windows에 연결됨", args[0])
        self.assertIn("로그인되어 있음", args[0])

        w.login_identity = "User Name (student@university.edu)"
        asyncio.run(w._pick_signed_in_account_tile(mock_page))
        args2, _ = mock_page.evaluate.await_args
        self.assertEqual(args2[1], "student@university.edu")

    def test_hot_mode_tab_recycling_on_interval_and_error(self) -> None:
        w = engine.CopilotWorker(9333, "Main", str(self.tmp_path / "main"), mode="hot")
        w.tab_recycle_interval = 2

        events: list[str] = []

        def make_page(tag: str) -> MagicMock:
            p = MagicMock()
            p.url = engine.COPILOT_URL
            p.is_closed.return_value = False

            async def _goto(*args, **kwargs):
                events.append(f"goto:{tag}")

            async def _close():
                events.append(f"close:{tag}")
                p.is_closed.return_value = True

            p.goto = AsyncMock(side_effect=_goto)
            p.close = AsyncMock(side_effect=_close)
            return p

        old_p1 = make_page("old1")
        old_p2 = make_page("old2")
        new_p = make_page("new1")

        mock_ctx = MagicMock()
        mock_ctx.pages = [old_p1, old_p2]

        async def _new_page():
            events.append("new_page")
            mock_ctx.pages.append(new_p)
            return new_p

        mock_ctx.new_page = AsyncMock(side_effect=_new_page)
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True

        w.browser = mock_browser
        w.context = mock_ctx
        w.page = old_p1
        w._tab_request_count = 2

        with patch.object(w, "connect", AsyncMock(return_value=old_p1)), \
             patch.object(w, "_wait_for_composer", AsyncMock(return_value=True)), \
             patch.object(w, "ensure_model_selected", AsyncMock()), \
             patch.object(w, "new_chat", AsyncMock()) as mock_new_chat, \
             patch.object(w, "_submit_prompt", AsyncMock()), \
             patch.object(engine.asyncio, "sleep", AsyncMock()):
            # reset_chat=False must preserve conversation and defer periodic recycle
            p_keep = asyncio.run(w._prepare_and_submit("follow-up", reset_chat=False))
            self.assertIs(p_keep, old_p1)
            self.assertEqual(events, [])

            # reset_chat=True at interval triggers recycle: opens new tab BEFORE closing old tabs
            p_recycled = asyncio.run(w._prepare_and_submit("fresh", reset_chat=True))
            self.assertIs(p_recycled, new_p)
            self.assertIs(w.page, new_p)
            self.assertEqual(w._tab_request_count, 0)
            self.assertFalse(w._needs_tab_recycle)
            self.assertEqual(events[:2], ["new_page", "goto:new1"])
            self.assertIn("close:old1", events[2:])
            self.assertIn("close:old2", events[2:])
            mock_new_chat.assert_not_awaited()

        # Exception recovery flag triggers recycle even before interval
        new_p2 = make_page("new2")
        mock_ctx.pages = [new_p]
        mock_ctx.new_page = AsyncMock(return_value=new_p2)
        w._needs_tab_recycle = True
        w._tab_request_count = 0
        with patch.object(w, "connect", AsyncMock(return_value=new_p)), \
             patch.object(w, "_wait_for_composer", AsyncMock(return_value=True)), \
             patch.object(w, "ensure_model_selected", AsyncMock()), \
             patch.object(w, "_submit_prompt", AsyncMock()), \
             patch.object(engine.asyncio, "sleep", AsyncMock()):
            p_recovered = asyncio.run(w._prepare_and_submit("retry", reset_chat=False))
            self.assertIs(p_recovered, new_p2)
            self.assertFalse(w._needs_tab_recycle)
            new_p.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
