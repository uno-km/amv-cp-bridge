# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""Unit tests for TelemetryDB WAL mode, /v1/images/generations, /api/accounts/{port}/close, parallelism, and pool failover."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from amv_cp_bridge import engine, gateway
from amv_cp_bridge.telemetry_db import TelemetryDB


def test_telemetry_db_uses_wal_and_records(tmp_path: Path) -> None:
    db_file = tmp_path / "telemetry.db"
    tdb = TelemetryDB(db_file)
    conn = sqlite3.connect(str(db_file))
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        conn.close()
    assert str(mode).lower() == "wal"

    row_id = tdb.record_query(
        prompt="hello world",
        duration_ms=123.4,
        bytes_len=512,
        worker_port=9334,
        account_label="아주대 (:9334)",
        source="pytest",
        success=True,
    )
    assert row_id > 0
    summary = tdb.get_summary()
    assert summary["total"]["queries"] == 1
    assert summary["total"]["bytes"] == 512


def test_gateway_images_generations_and_error_mapping(tmp_path: Path, monkeypatch) -> None:
    raw_png = b"\x89PNG\r\n\x1a\n" + b"X" * 128
    b64_png = base64.b64encode(raw_png).decode("ascii")
    captured_calls: list[dict] = []

    async def fake_generate_image(prompt: str, **kwargs):
        captured_calls.append({"prompt": prompt, **kwargs})
        assert len(kwargs.get("file_paths") or []) == 1
        assert Path(kwargs["file_paths"][0]).is_file()
        return {
            "worker_port": 9334,
            "text": "Generated image ready.",
            "images": [
                {
                    "b64_json": b64_png,
                    "mime_type": "image/png",
                    "sha256": hashlib.sha256(raw_png).hexdigest(),
                    "bytes_len": len(raw_png),
                }
            ],
        }

    monkeypatch.setattr(gateway.engine, "generate_image", fake_generate_image)
    ref_b64 = base64.b64encode(b"fake-ref-bytes").decode("ascii")

    client = TestClient(gateway.app)
    resp = client.post(
        "/v1/images/generations",
        json={
            "prompt": "render neon alley",
            "reference_images": [f"data:image/png;base64,{ref_b64}"],
        },
        headers={"X-Bridge-Source": "test-client:image"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["worker_port"] == 9334
    assert body["data"][0]["b64_json"] == b64_png
    assert captured_calls and captured_calls[0]["source"] == "test-client:image"

    async def fake_refusal(*a, **kw):
        raise engine.CopilotPolicyRefusalError("content policy blocked")

    monkeypatch.setattr(gateway.engine, "generate_image", fake_refusal)
    resp_422 = client.post("/v1/images/generations", json={"prompt": "blocked"})
    assert resp_422.status_code == 422

    async def fake_quota(*a, **kw):
        raise engine.CopilotQuotaError("daily limit")

    monkeypatch.setattr(gateway.engine, "generate_image", fake_quota)
    resp_429 = client.post("/v1/images/generations", json={"prompt": "quota"})
    assert resp_429.status_code == 429


def test_gateway_account_close_and_purge(tmp_path: Path, monkeypatch) -> None:
    w1 = engine.CopilotWorker(9334, "ajou", str(tmp_path / "p9334"))
    w2 = engine.CopilotWorker(9333, "main", str(tmp_path / "p9333"))
    cleanups: list[int] = []
    kills: list[tuple[int, bool]] = []

    for w in (w1, w2):
        async def _clean(port=w.port):
            cleanups.append(port)

        w.cleanup = _clean  # type: ignore[method-assign]
        w.kill_browser_process = lambda force=False, port=w.port: kills.append((port, force))  # type: ignore[method-assign]

    monkeypatch.setattr(gateway.engine, "workers", [w1, w2])
    monkeypatch.setattr(gateway.event_bus, "publish", lambda ev: None)

    client = TestClient(gateway.app)
    r_close = client.post("/api/accounts/9334/close")
    assert r_close.status_code == 200
    assert cleanups == [9334]
    assert kills == [(9334, True)]

    r_404 = client.post("/api/accounts/9999/close")
    assert r_404.status_code == 404

    w1._reserved = True
    r_409 = client.post("/api/accounts/9334/close")
    assert r_409.status_code == 409
    w1._reserved = False

    r_purge = client.post("/api/purge")
    assert r_purge.status_code == 200
    assert (9333, True) in kills and kills.count((9334, True)) == 2


def test_find_browser_binary_preserves_last_browser_and_browser_hint(tmp_path: Path) -> None:
    chrome_prof = tmp_path / "ajou"
    chrome_prof.mkdir()
    (chrome_prof / "Last Browser").write_bytes(b"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\x00")
    assert Path(engine._find_browser_binary(str(chrome_prof))).name.lower() == "chrome.exe"
    assert Path(engine._find_browser_binary(str(chrome_prof), preferred_browser="edge")).name.lower() == "chrome.exe"

    edge_prof = tmp_path / "prof2"
    edge_prof.mkdir()
    (edge_prof / "Last Browser").write_bytes(b"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe\x00")
    assert Path(engine._find_browser_binary(str(edge_prof))).name.lower() == "msedge.exe"

    empty_prof = tmp_path / "fresh"
    empty_prof.mkdir()
    assert Path(engine._find_browser_binary(str(empty_prof), preferred_browser="chrome")).name.lower() == "chrome.exe"
    assert Path(engine._find_browser_binary(None, preferred_browser="edge")).name.lower() == "msedge.exe"
    assert Path(engine._find_browser_binary(None)).name.lower() == "msedge.exe"


def test_kill_browser_process_protects_external_sessions(tmp_path: Path, monkeypatch) -> None:
    w = engine.CopilotWorker(9334, "ajou", str(tmp_path / "prof"))
    monkeypatch.setattr(w, "get_listening_pids", lambda: [4242])
    killed_cmds: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: killed_cmds.append(list(cmd)))

    # External manual browser window (_launched_by_bridge=False) must NOT be killed unless force=True
    w._launched_by_bridge = False
    w.kill_browser_process(force=False)
    assert killed_cmds == []

    # Force=True terminates even external window and resets _launched_by_bridge
    w._launched_by_bridge = True
    w.kill_browser_process(force=True)
    assert len(killed_cmds) == 1
    assert w._launched_by_bridge is False


def test_pool_reloads_deprioritizes_required_and_midstream_failover(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / ".amv_cp_bridge"
    cfg_dir.mkdir()
    acc_file = cfg_dir / "accounts.json"
    acc_file.write_text(
        json.dumps([{"port": 9334, "name": "ajou", "profile_dir": str(tmp_path / "p9334"), "browser": "chrome"}]),
        encoding="utf-8",
    )

    monkeypatch.setattr(engine, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(engine, "CONFIG_PATH", str(acc_file))
    monkeypatch.setattr(engine, "load_settings", lambda: {"mode": "cold", "standby_timeout_sec": 300})
    monkeypatch.setattr(engine, "telemetry_db", TelemetryDB(tmp_path / "telemetry.db"))

    pool = engine.CopilotPool()
    assert [w.port for w in pool.workers] == [9334]
    assert pool.workers[0].preferred_browser == "chrome"

    acc_file.write_text(
        json.dumps([
            {"port": 9334, "name": "ajou", "profile_dir": str(tmp_path / "p9334"), "browser": "chrome"},
            {"port": 9332, "name": "third", "profile_dir": str(tmp_path / "p9332"), "browser": "edge"},
        ]),
        encoding="utf-8",
    )
    os.utime(acc_file, (acc_file.stat().st_atime, acc_file.stat().st_mtime + 2.0))
    pool._sync_workers_from_disk()
    assert [w.port for w in pool.workers] == [9334, 9332]

    # Mark worker 0 as login_state == "required": acquire_worker must pick worker 1 first
    pool.workers[0].login_state = "required"

    async def _check_order():
        w = await pool.acquire_worker()
        try:
            return w.port
        finally:
            w._reserved = False

    assert asyncio.run(_check_order()) == 9332

    # Reset login_state and verify buffered mid-stream failover drops partial chunk from failing worker
    pool.workers[0].login_state = "ok"

    async def midstream_failing_stream(prompt: str, reset_chat: bool = True, file_paths=None):
        yield "partial-corrupted-"
        raise RuntimeError("session dropped midstream")

    async def ok_stream(prompt: str, reset_chat: bool = True, file_paths=None):
        yield "ok-from-9332"

    pool.workers[0].stream_query = midstream_failing_stream  # type: ignore[method-assign]
    pool.workers[1].stream_query = ok_stream                 # type: ignore[method-assign]

    ans = asyncio.run(pool.query("ping", source="pytest"))
    assert ans == "ok-from-9332"
    assert pool.active_count == 0
    assert pool.queued_count == 0
    assert engine.telemetry_db.get_summary()["total"]["queries"] == 1


def test_pool_true_concurrent_parallelism_across_two_workers(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / ".amv_cp_bridge"
    cfg_dir.mkdir()
    acc_file = cfg_dir / "accounts.json"
    acc_file.write_text(
        json.dumps([
            {"port": 9334, "name": "ajou", "profile_dir": str(tmp_path / "p9334")},
            {"port": 9333, "name": "main", "profile_dir": str(tmp_path / "p9333")},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(engine, "CONFIG_PATH", str(acc_file))
    monkeypatch.setattr(engine, "load_settings", lambda: {"mode": "cold", "standby_timeout_sec": 300})
    monkeypatch.setattr(engine, "telemetry_db", TelemetryDB(tmp_path / "telemetry.db"))

    pool = engine.CopilotPool()
    used_ports: list[int] = []

    for w in pool.workers:
        w.is_alive = lambda: True  # type: ignore[method-assign]

        async def slow_stream(prompt: str, reset_chat: bool = True, file_paths=None, _port=w.port):
            used_ports.append(_port)
            await asyncio.sleep(0.20)
            yield f"reply-{_port}"

        w.stream_query = slow_stream  # type: ignore[method-assign]

    async def run_two():
        t0 = time.perf_counter()
        res = await asyncio.gather(pool.query("a", source="t"), pool.query("b", source="t"))
        return res, time.perf_counter() - t0

    results, elapsed = asyncio.run(run_two())
    assert set(used_ports) == {9334, 9333}
    assert set(results) == {"reply-9334", "reply-9333"}
    assert elapsed < 0.34


def test_worker_stream_query_done_stable_completes(tmp_path: Path, monkeypatch) -> None:
    w = engine.CopilotWorker(9334, "ajou", str(tmp_path / "prof"))
    w.mode = "hot"

    eval_calls = {"n": 0}

    class FakePage:
        url = "https://m365.cloud.microsoft/chat"

        async def evaluate(self, script: str):
            eval_calls["n"] += 1
            return {"text": "Copilot said:\nHello clean answer", "isDone": True}

    async def fake_prepare(prompt: str, *, reset_chat: bool = True, file_paths=None):
        return FakePage()

    monkeypatch.setattr(w, "_prepare_and_submit", fake_prepare)
    monkeypatch.setattr(w, "_schedule_standby", lambda: None)

    orig_sleep = asyncio.sleep

    async def fast_sleep(_sec: float):
        await orig_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    async def collect():
        chunks = []
        async for ch in w.stream_query("hi"):
            chunks.append(ch)
        return "".join(chunks)

    out = asyncio.run(collect())
    assert out == "Hello clean answer"
    assert w.last_text == "Hello clean answer"
    # Poll loop requires done_stable >= 4 (first poll emits delta, 4 subsequent stable ticks reach done_stable==4)
    assert eval_calls["n"] >= 5
