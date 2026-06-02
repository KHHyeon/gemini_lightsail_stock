# -*- coding: utf-8 -*-
"""_SQLiteBackend — state_store 의 SQLite 백엔드 구현.

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md (Phase 2 backend),
      Doc/features/data_persistence/03_data_persistence_state_logic.md §9
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Optional


_FILENAME_PORTFOLIO = "paper_portfolio.json"
_FILENAME_SPLIT_ORDERS = "split_orders.json"
_FILENAME_THEME_CONTEXT = "theme_context.json"
_FILENAME_SCALP_SESSION = "scalp_session.json"
_FILENAME_TRADES = "paper_trades.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _SQLiteBackend:
    """state_store 의 SQLite 백엔드.

    인터페이스(``read_json``/``write_json``) 는 ``_DriveBackend`` 와 동일하다.
    파일명을 도메인 테이블로 매핑하여 SELECT/INSERT 한다.
    """

    def __init__(
        self,
        db_path: str,
        notify_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._db_path = db_path
        directory = os.path.dirname(os.path.abspath(db_path))
        if directory:
            os.makedirs(directory, exist_ok=True)

        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        from src.storage.migrations.runner import apply_pending

        apply_pending(self._conn, notify_fn=notify_fn)

    # ------------------------------------------------------------------
    # 공개 인터페이스 (_StateStoreBackend 와 동일 시그니처)
    # ------------------------------------------------------------------
    def read_json(self, filename: str, default: Any) -> Any:
        if filename == _FILENAME_PORTFOLIO:
            return self._read_keyed_dict("portfolio", "ticker", default)
        if filename == _FILENAME_SPLIT_ORDERS:
            return self._read_keyed_dict("split_orders", "order_id", default)
        if filename == _FILENAME_THEME_CONTEXT:
            return self._read_keyed_dict("theme_context", "ticker", default)
        if filename == _FILENAME_SCALP_SESSION:
            return self._read_single_row_payload(default)
        if filename == _FILENAME_TRADES:
            return self._read_trades(default)
        raise ValueError(f"sqlite_backend: 알 수 없는 도메인 파일명: {filename}")

    def write_json(self, filename: str, data: Any) -> None:
        if filename == _FILENAME_PORTFOLIO:
            self._write_keyed_dict("portfolio", "ticker", data)
            return
        if filename == _FILENAME_SPLIT_ORDERS:
            self._write_keyed_dict("split_orders", "order_id", data)
            return
        if filename == _FILENAME_THEME_CONTEXT:
            self._write_keyed_dict("theme_context", "ticker", data)
            return
        if filename == _FILENAME_SCALP_SESSION:
            self._write_single_row_payload(data)
            return
        if filename == _FILENAME_TRADES:
            self._write_trades(data)
            return
        raise ValueError(f"sqlite_backend: 알 수 없는 도메인 파일명: {filename}")

    def close(self) -> None:
        """connection 종료. 운영 중에는 호출 불필요(프로세스 종료 시 자동). 테스트 정리용."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 내부: A 도메인 공통 — key->payload dict
    # ------------------------------------------------------------------
    def _read_keyed_dict(self, table: str, key_col: str, default: Any) -> Any:
        rows = self._conn.execute(
            f"SELECT {key_col}, payload_json FROM {table}"
        ).fetchall()
        if not rows:
            return default if default is not None else {}
        result_dict = {}
        for key_value, payload_json in rows:
            try:
                result_dict[key_value] = json.loads(payload_json)
            except (TypeError, ValueError):
                result_dict[key_value] = {}
        return result_dict

    def _write_keyed_dict(self, table: str, key_col: str, data: Any) -> None:
        if not isinstance(data, dict):
            raise TypeError(f"{table} write 는 dict 만 허용")
        now = _now_iso()
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(f"DELETE FROM {table}")
            self._conn.executemany(
                f"INSERT INTO {table} ({key_col}, payload_json, updated_at) VALUES (?, ?, ?)",
                [(str(k), json.dumps(v, ensure_ascii=False), now) for k, v in data.items()],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------
    # 내부: scalp_session — single row
    # ------------------------------------------------------------------
    def _read_single_row_payload(self, default: Any) -> Any:
        row = self._conn.execute(
            "SELECT payload_json FROM scalp_session WHERE id = 1"
        ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return default

    def _write_single_row_payload(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise TypeError("scalp_session write 는 dict 만 허용")
        now = _now_iso()
        payload_json = json.dumps(data, ensure_ascii=False)
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                INSERT INTO scalp_session (id, payload_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (payload_json, now),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------
    # 내부: trades — append-only 의미. 현재는 전체 교체.
    # ------------------------------------------------------------------
    def _read_trades(self, default: Any) -> Any:
        rows = self._conn.execute(
            "SELECT payload_json FROM trades ORDER BY ts, id"
        ).fetchall()
        if not rows:
            return default if default is not None else []
        result_list = []
        for (payload_json,) in rows:
            try:
                result_list.append(json.loads(payload_json))
            except (TypeError, ValueError):
                continue
        return result_list

    def _write_trades(self, data: Any) -> None:
        if not isinstance(data, list):
            raise TypeError("trades write 는 list 만 허용")
        try:
            self._conn.execute("BEGIN")
            self._conn.execute("DELETE FROM trades")
            insert_rows = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                ts = entry.get("timestamp") or entry.get("ts") or _now_iso()
                ticker = entry.get("ticker") or ""
                trade_uuid = entry.get("trade_uuid")  # 기존 데이터에 없으면 None
                payload_json = json.dumps(entry, ensure_ascii=False)
                insert_rows.append((trade_uuid, ts, ticker, payload_json, None))
            if insert_rows:
                self._conn.executemany(
                    """
                    INSERT INTO trades (trade_uuid, ts, ticker, payload_json, extra_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    insert_rows,
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
