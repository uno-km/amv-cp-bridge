# Copyright (c) 2026 Eunho Kim / AMEVA Foundation. All rights reserved.
# SPDX-License-Identifier: Apache-2.0 OR Commercial-License
"""
Ultra-Lightweight Embedded SQLite Telemetry Database for amv-cp-bridge
Tracks daily, weekly, monthly, and yearly cognitive offloading metrics with Zero-Heap footprint.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

DB_DIR = Path.home() / ".amv_cp_bridge"
DB_PATH = DB_DIR / "telemetry.db"

class TelemetryDB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        try:
            self._init_db()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                f"사용 기록 DB를 열 수 없습니다: {self.db_path} ({exc}). "
                "프로그램을 종료하고 이 파일을 다른 곳으로 옮긴 뒤 다시 실행하십시오. 새 DB가 만들어집니다."
            ) from exc

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # 신규 컬럼 목록 (기존 DB 마이그레이션 대상)
    _NEW_COLS = {
        "source":           "TEXT DEFAULT 'api'",
        "task_id":          "TEXT",
        "client_app":       "TEXT",       # claude-desktop, cursor, antigravity, whale, chrome, cli, api
        "client_version":   "TEXT",       # UA에서 파싱한 버전
        "queue_wait_ms":    "REAL",       # 큐 대기 시간
        "prompt_tokens_est":"INTEGER",    # 입력 토큰 추정 (입력 바이트 / 4.2)
        "ip_addr":          "TEXT",       # 클라이언트 IP
        "full_prompt":      "TEXT",       # 전체 프롬프트 (모달 상세보기용)
        "full_response":    "TEXT",       # 전체 응답 (모달 상세보기용)
    }

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    prompt_preview TEXT,
                    duration_ms REAL,
                    tokens_est INTEGER,
                    bytes_len INTEGER,
                    worker_port INTEGER,
                    account_label TEXT,
                    model TEXT,
                    source TEXT DEFAULT 'api',
                    success INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON usage_records(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON usage_records(source)")
            # 누락 컬럼 자동 마이그레이션
            existing = {row[1] for row in conn.execute("PRAGMA table_info(usage_records)").fetchall()}
            for col, typedef in self._NEW_COLS.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE usage_records ADD COLUMN {col} {typedef}")
            conn.commit()

    def record_query(
        self,
        prompt: str,
        duration_ms: float,
        bytes_len: int,
        worker_port: int,
        account_label: str,
        model: str = "gpt-5.6-sol",
        source: str = "api",
        success: bool = True,
        task_id: str = "",
        client_app: str = "",
        client_version: str = "",
        queue_wait_ms: float = 0.0,
        prompt_bytes: int = 0,
        ip_addr: str = "",
        full_response: str = "",
    ) -> int:
        """기록 1건 추가.
        source: 'api' | 'mcp:claude' | 'mcp:cursor' | 'mcp:antigravity' | 'extension' | 'cli'
        """
        tokens_est = max(1, int(bytes_len / 4.2)) if bytes_len > 0 else 0
        prompt_tokens = max(1, int(prompt_bytes / 4.2)) if prompt_bytes > 0 else 0
        prompt_preview = (prompt[:300] + "...") if len(prompt) > 300 else prompt

        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO usage_records (
                    prompt_preview, duration_ms, tokens_est, bytes_len,
                    worker_port, account_label, model, source, success,
                    task_id, client_app, client_version,
                    queue_wait_ms, prompt_tokens_est, ip_addr,
                    full_prompt, full_response
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prompt_preview, round(duration_ms, 2), tokens_est, bytes_len,
                worker_port, account_label, model, source, 1 if success else 0,
                task_id or "", client_app or "", client_version or "",
                round(queue_wait_ms, 2), prompt_tokens, ip_addr or "",
                prompt or "", full_response or "",
            ))
            conn.commit()
            return cursor.lastrowid

    def get_summary(self) -> Dict[str, Any]:
        """일/주/월/년 및 누적 사용량 통계 집계"""
        with self._get_connection() as conn:
            # 1. Total
            total_row = conn.execute("""
                SELECT 
                    COUNT(*) as total_queries,
                    COALESCE(SUM(tokens_est), 0) as total_tokens,
                    COALESCE(SUM(bytes_len), 0) as total_bytes,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms,
                    COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) as success_queries
                FROM usage_records
            """).fetchone()

            # 2. Today
            today_row = conn.execute("""
                SELECT 
                    COUNT(*) as queries,
                    COALESCE(SUM(tokens_est), 0) as tokens,
                    COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                FROM usage_records
                WHERE DATE(timestamp, 'localtime') = DATE('now', 'localtime')
            """).fetchone()

            # 3. This Week
            week_row = conn.execute("""
                SELECT 
                    COUNT(*) as queries,
                    COALESCE(SUM(tokens_est), 0) as tokens
                FROM usage_records
                WHERE strftime('%Y-%W', timestamp, 'localtime') = strftime('%Y-%W', 'now', 'localtime')
            """).fetchone()

            # 4. This Month
            month_row = conn.execute("""
                SELECT 
                    COUNT(*) as queries,
                    COALESCE(SUM(tokens_est), 0) as tokens
                FROM usage_records
                WHERE strftime('%Y-%m', timestamp, 'localtime') = strftime('%Y-%m', 'now', 'localtime')
            """).fetchone()

            # 5. This Year
            year_row = conn.execute("""
                SELECT 
                    COUNT(*) as queries,
                    COALESCE(SUM(tokens_est), 0) as tokens
                FROM usage_records
                WHERE strftime('%Y', timestamp, 'localtime') = strftime('%Y', 'now', 'localtime')
            """).fetchone()

            # 6. Recent 20 queries
            recent_rows = conn.execute("""
                SELECT
                    id,
                    datetime(timestamp, 'localtime') as time_str,
                    prompt_preview,
                    duration_ms,
                    tokens_est,
                    bytes_len,
                    worker_port,
                    account_label,
                    model,
                    COALESCE(source, 'api') as source,
                    COALESCE(task_id, '') as task_id,
                    COALESCE(client_app, '') as client_app,
                    COALESCE(client_version, '') as client_version,
                    COALESCE(queue_wait_ms, 0) as queue_wait_ms,
                    COALESCE(prompt_tokens_est, 0) as prompt_tokens_est,
                    COALESCE(ip_addr, '') as ip_addr,
                    success
                FROM usage_records
                ORDER BY id DESC
                LIMIT 20
            """).fetchall()

            # 7. Per-source breakdown
            source_rows = conn.execute("""
                SELECT
                    COALESCE(source, 'api') as source,
                    COUNT(*) as queries,
                    COALESCE(SUM(tokens_est), 0) as tokens
                FROM usage_records
                GROUP BY COALESCE(source, 'api')
            """).fetchall()

            total_q = total_row["total_queries"]
            succ_q = total_row["success_queries"]
            success_rate = round((succ_q / total_q * 100), 1) if total_q > 0 else 100.0

            by_source = {row["source"]: {"queries": row["queries"], "tokens": row["tokens"]} for row in source_rows}

            return {
                "total": {
                    "queries": total_q,
                    "tokens": total_row["total_tokens"],
                    "bytes": total_row["total_bytes"],
                    "avg_duration_ms": round(total_row["avg_duration_ms"], 1),
                    "success_rate": success_rate
                },
                "by_source": by_source,
                "today": {
                    "queries": today_row["queries"],
                    "tokens": today_row["tokens"],
                    "avg_duration_ms": round(today_row["avg_duration_ms"], 1)
                },
                "week": {
                    "queries": week_row["queries"],
                    "tokens": week_row["tokens"]
                },
                "month": {
                    "queries": month_row["queries"],
                    "tokens": month_row["tokens"]
                },
                "year": {
                    "queries": year_row["queries"],
                    "tokens": year_row["tokens"]
                },
                "recent": [dict(r) for r in recent_rows]
            }

    def get_record_full(self, record_id: int) -> Dict[str, Any]:
        """id로 full_prompt, full_response 조회"""
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT id, datetime(timestamp, 'localtime') as time_str,
                       full_prompt, full_response,
                       source, client_app, client_version,
                       duration_ms, tokens_est, queue_wait_ms,
                       worker_port, account_label, ip_addr, success
                FROM usage_records WHERE id = ?
            """, (record_id,)).fetchone()
            return dict(row) if row else {}

    def get_daily_chart(self, days: int = 14) -> List[Dict[str, Any]]:
        """최근 N일간 일별 쿼리 수 및 토큰 수 (차트용)"""
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT
                    DATE(timestamp, 'localtime') as day,
                    COUNT(*) as queries,
                    COALESCE(SUM(tokens_est), 0) as tokens
                FROM usage_records
                WHERE timestamp >= datetime('now', '-{int(days)} days')
                GROUP BY DATE(timestamp, 'localtime')
                ORDER BY day ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def reset_all(self) -> bool:
        """모든 통계 및 사용 기록 원클릭 영구 초기화"""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM usage_records")
            conn.execute("DELETE FROM sqlite_sequence WHERE name='usage_records'")
            conn.commit()
            conn.execute("VACUUM")
        return True

# Global Singleton
telemetry_db = TelemetryDB()
