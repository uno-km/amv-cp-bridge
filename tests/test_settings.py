# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""Unit tests for amv_cp_bridge.settings persistence and engine mode switching."""

import os
import unittest
from amv_cp_bridge._version import __version__
from amv_cp_bridge.settings import load_settings, save_settings, SETTINGS_PATH, DEFAULT_SETTINGS
from amv_cp_bridge.engine import CopilotPool


class TestSettings(unittest.TestCase):
    def test_version(self):
        self.assertEqual(__version__, "1.3.0")

    def test_load_default(self):
        settings = load_settings()
        self.assertIn("mode", settings)
        self.assertIn(settings["mode"], ("cold", "hot"))
        self.assertIn("standby_timeout_sec", settings)

    def test_save_and_persist(self):
        # Hot mode 전환 테스트
        updated = save_settings({"mode": "hot", "standby_timeout_sec": 600})
        self.assertEqual(updated["mode"], "hot")
        self.assertEqual(updated["standby_timeout_sec"], 600)

        # 디스크에서 다시 읽기
        reloaded = load_settings()
        self.assertEqual(reloaded["mode"], "hot")
        self.assertEqual(reloaded["standby_timeout_sec"], 600)

        # Cold mode 복구 테스트 (기본값 원복)
        restored = save_settings({"mode": "cold", "standby_timeout_sec": 300})
        self.assertEqual(restored["mode"], "cold")
        self.assertEqual(restored["standby_timeout_sec"], 300)

    def test_engine_settings_sync(self):
        pool = CopilotPool()
        self.assertIn(pool.mode, ("cold", "hot"))
        # 엔진 동적 설정 업데이트
        res = pool.update_settings({"mode": "hot", "standby_timeout_sec": 120})
        self.assertEqual(pool.mode, "hot")
        self.assertEqual(pool.standby_timeout_sec, 120)
        for w in pool.workers:
            self.assertEqual(w.mode, "hot")
            self.assertEqual(w.standby_timeout_sec, 120)

        # 원복 (기본 cold)
        pool.update_settings({"mode": "cold", "standby_timeout_sec": 300})
        self.assertEqual(pool.mode, "cold")
        for w in pool.workers:
            self.assertEqual(w.mode, "cold")


if __name__ == "__main__":
    unittest.main()
