# -*- coding: utf-8 -*-
"""v001_initial — A/B 도메인 5 테이블 + schema_version 메타.

상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §9.2
"""
from __future__ import annotations

import sqlite3


VERSION = 1
DESCRIPTION = "A/B 도메인 5 테이블 + schema_version 메타 (Phase 2 v1)"


_SCHEMA_DDL_LIST = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL,
        description TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio (
        ticker TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS split_orders (
        order_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS theme_context (
        ticker TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scalp_session (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_uuid TEXT UNIQUE,
        ts TEXT NOT NULL,
        ticker TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        extra_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts)",
    "CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)",
)


def up(conn: sqlite3.Connection) -> None:
    """A/B 도메인 5 테이블 + 인덱스 + schema_version 메타 생성.

    호출자(runner) 가 BEGIN/COMMIT 트랜잭션을 관리한다.
    """
    cursor = conn.cursor()
    for ddl in _SCHEMA_DDL_LIST:
        cursor.execute(ddl)
