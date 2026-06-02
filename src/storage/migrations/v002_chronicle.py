# -*- coding: utf-8 -*-
"""v002_chronicle — Market Chronicles C/D 도메인 + FTS5 + 섹션 정규화 + backfill_state.

상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §11.3
"""
from __future__ import annotations

import sqlite3
import sys


VERSION = 2
DESCRIPTION = "Phase 3: chronicle C/D + FTS5 + sections + backfill_state"


_SCHEMA_DDL_LIST = (
    # C 도메인: Chronicle 인덱스 (master_index.entries v2 평탄화)
    """
    CREATE TABLE IF NOT EXISTS chronicle_entries (
        entry_id        TEXT    PRIMARY KEY,
        chronicle_date  TEXT    NOT NULL,
        source          TEXT    NOT NULL,
        trigger_reason  TEXT    NOT NULL,
        regime          TEXT    NOT NULL,
        regime_label    TEXT,
        main_actor      TEXT,
        sentiment       TEXT,
        action_preview  TEXT    NOT NULL,
        context_tags_json  TEXT NOT NULL,
        phrases_json       TEXT,
        embedding_vector   BLOB,
        report_rel_path TEXT    NOT NULL,
        written_at      TEXT    NOT NULL,
        reindexed_at    TEXT,
        migrated_at     TEXT,
        schema_version  INTEGER NOT NULL DEFAULT 2,
        extra_json      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chr_entries_date   ON chronicle_entries(chronicle_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_chr_entries_regime ON chronicle_entries(regime)",
    "CREATE INDEX IF NOT EXISTS idx_chr_entries_source ON chronicle_entries(source)",
    # D 도메인: Chronicle 본문 (.md 파일 보존)
    """
    CREATE TABLE IF NOT EXISTS chronicle_reports (
        entry_id        TEXT    PRIMARY KEY,
        chronicle_date  TEXT    NOT NULL,
        header_md       TEXT    NOT NULL,
        body_md         TEXT    NOT NULL,
        full_md         TEXT    NOT NULL,
        written_at      TEXT    NOT NULL,
        schema_version  INTEGER NOT NULL DEFAULT 2,
        FOREIGN KEY (entry_id) REFERENCES chronicle_entries(entry_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chr_reports_date ON chronicle_reports(chronicle_date DESC)",
    # D-2: 본문 5섹션 정규화
    """
    CREATE TABLE IF NOT EXISTS chronicle_report_sections (
        entry_id        TEXT    NOT NULL,
        section_index   INTEGER NOT NULL,
        section_key     TEXT    NOT NULL,
        section_title   TEXT    NOT NULL,
        body_md         TEXT    NOT NULL,
        PRIMARY KEY (entry_id, section_index),
        FOREIGN KEY (entry_id) REFERENCES chronicle_entries(entry_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chr_sections_key ON chronicle_report_sections(section_key)",
    # 운영 상태: backfill 큐 (단일 row)
    """
    CREATE TABLE IF NOT EXISTS chronicle_backfill_state (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json    TEXT    NOT NULL,
        updated_at      TEXT    NOT NULL
    )
    """,
)

# FTS5 가상 테이블 DDL (별도 — 빌드 가용성 검사 후 적용).
_FTS5_DDL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS chronicle_search USING fts5(
        entry_id        UNINDEXED,
        chronicle_date  UNINDEXED,
        section_key     UNINDEXED,
        body_md,
        tokenize = 'unicode61 remove_diacritics 2'
    )
"""


def _is_fts5_available(conn: sqlite3.Connection) -> bool:
    """SQLite 빌드에 FTS5 모듈이 포함되었는지 1회 점검."""
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(c)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def up(conn: sqlite3.Connection) -> None:
    """C/D 도메인 4 테이블 + (옵션) FTS5 + 인덱스 + backfill_state 생성.

    FTS5 가 빌드에 없으면 chronicle_search 만 스킵하고 stderr 경고 1회 출력
    (P3E2 정책). 봇 운영은 정상 계속하며 search_fulltext 는 정규식 폴백.
    호출자(runner) 가 BEGIN/COMMIT 트랜잭션을 관리한다.
    """
    cursor = conn.cursor()
    for ddl in _SCHEMA_DDL_LIST:
        cursor.execute(ddl)

    if _is_fts5_available(conn):
        cursor.execute(_FTS5_DDL)
    else:
        print(
            "[storage.v002] FTS5 모듈이 SQLite 빌드에 없습니다. "
            "chronicle_search 생성 생략 -> search_fulltext 는 정규식 폴백 동작.",
            file=sys.stderr,
        )
