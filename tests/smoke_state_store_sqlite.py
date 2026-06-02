# -*- coding: utf-8 -*-
"""Phase 2 Step 2 smoke test — SQLite 백엔드 라운드트립 + Drive 보존 확인.

본 스크립트는 자동 실행 회귀가 아닌 일회성 검증용이다. py_compile 의 lint 와
별개로, 모듈을 실제로 import 했을 때의 동작을 점검한다.

실행:
    python tests/smoke_state_store_sqlite.py
"""
from __future__ import annotations

import os
import sys
import tempfile


def _purge_state_store_modules() -> None:
    for name in list(sys.modules.keys()):
        if name.startswith("src.storage"):
            del sys.modules[name]


def _check_drive_backend_default() -> None:
    """환경변수 미설정 시 _DriveBackend 가 선택되어야 한다 (Phase 1 보존)."""
    os.environ.pop("STATE_STORE_BACKEND", None)
    os.environ.pop("STATE_STORE_DB_PATH", None)
    _purge_state_store_modules()
    from src.storage import state_store

    assert type(state_store._backend).__name__ == "_DriveBackend", (
        f"기본 백엔드는 _DriveBackend 여야 합니다 (실측: {type(state_store._backend).__name__})"
    )
    print("[1/4] 기본=Drive 보존 OK")


def _check_unknown_backend_fallback() -> None:
    """알 수 없는 백엔드 값은 _DriveBackend 로 폴백해야 한다."""
    os.environ["STATE_STORE_BACKEND"] = "postgres"
    _purge_state_store_modules()
    from src.storage import state_store

    assert type(state_store._backend).__name__ == "_DriveBackend", "알 수 없는 값은 Drive 폴백"
    os.environ.pop("STATE_STORE_BACKEND", None)
    print("[2/4] 알 수 없는 값 -> Drive 폴백 OK")


def _check_sqlite_roundtrip(tmpdir: str) -> None:
    """SQLite 백엔드의 5 도메인 read/write 라운드트립."""
    db_path = os.path.join(tmpdir, "smoke.db")
    os.environ["STATE_STORE_BACKEND"] = "sqlite"
    os.environ["STATE_STORE_DB_PATH"] = db_path
    _purge_state_store_modules()
    from src.storage import state_store

    assert type(state_store._backend).__name__ == "_SQLiteBackend"

    # 빈 상태 read
    assert state_store.get_portfolio() == {}
    assert state_store.get_split_orders() == {}
    assert state_store.get_theme_context() == {}
    assert state_store.get_scalp_session() is None
    assert state_store.list_trades() == []

    # write -> read 라운드트립
    portfolio_dict = {"005930": {"name": "삼성전자", "quantity": 10, "avg_price": 70000}}
    state_store.save_portfolio(portfolio_dict)
    assert state_store.get_portfolio() == portfolio_dict

    split_dict = {"auto_1": {"ticker": "005930", "remaining_days": 10}}
    state_store.save_split_orders(split_dict)
    assert state_store.get_split_orders() == split_dict

    theme_dict = {"000660": {"name": "SK하이닉스", "theme": "AI반도체"}}
    state_store.save_theme_context(theme_dict)
    assert state_store.get_theme_context() == theme_dict

    session_dict = {"amount": 1000000, "lifecycle": "S0"}
    state_store.save_scalp_session(session_dict)
    assert state_store.get_scalp_session() == session_dict

    # scalp_session 갱신 (UPSERT 검증)
    session_dict["lifecycle"] = "S1"
    state_store.save_scalp_session(session_dict)
    assert state_store.get_scalp_session()["lifecycle"] == "S1"

    trades_list = [
        {"timestamp": "2026-06-02 10:00:00", "ticker": "005930", "action": "BUY", "price": 70000, "quantity": 10, "reason": "테스트", "mode_type": "PAPER_ONLY", "strategy_tag": "SMOKE"},
        {"timestamp": "2026-06-02 11:00:00", "ticker": "000660", "action": "BUY", "price": 80000, "quantity": 5, "reason": "테스트2", "mode_type": "PAPER_ONLY", "strategy_tag": "SMOKE"},
    ]
    state_store.replace_trades(trades_list)
    read_trades = state_store.list_trades()
    assert len(read_trades) == 2
    assert read_trades[0]["ticker"] == "005930"
    assert read_trades[1]["ticker"] == "000660"

    # reset_app_data 검증
    state_store.reset_app_data()
    assert state_store.get_portfolio() == {}
    assert state_store.get_split_orders() == {}
    assert state_store.get_theme_context() == {}
    assert state_store.list_trades() == []
    # scalp_session 은 reset 대상이 아니므로 잔존.
    assert state_store.get_scalp_session() is not None

    print("[3/4] SQLite 5 도메인 라운드트립 OK")


def _check_migration_applied(tmpdir: str) -> None:
    """schema_version 테이블에 v1 row 가 1개 있어야 한다."""
    import sqlite3

    db_path = os.path.join(tmpdir, "smoke.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT version, description FROM schema_version ORDER BY version").fetchall()
    conn.close()
    assert rows == [(1, "A/B 도메인 5 테이블 + schema_version 메타 (Phase 2 v1)")], rows
    print("[4/4] schema_version v1 기록 OK")


def _close_state_store_backend() -> None:
    """Windows 환경에서 WAL/SHM 잠금이 임시 디렉터리 삭제를 막는 것을 방지."""
    if "src.storage.state_store" in sys.modules:
        st = sys.modules["src.storage.state_store"]
        backend = getattr(st, "_backend", None)
        close_fn = getattr(backend, "close", None)
        if callable(close_fn):
            close_fn()


def main() -> None:
    sys.path.insert(0, ".")
    tmpdir_obj = tempfile.TemporaryDirectory()
    try:
        _check_drive_backend_default()
        _check_unknown_backend_fallback()
        _check_sqlite_roundtrip(tmpdir_obj.name)
        _check_migration_applied(tmpdir_obj.name)
        print("\nALL OK")
    finally:
        _close_state_store_backend()
        try:
            tmpdir_obj.cleanup()
        except Exception:
            # Windows 환경의 잔여 lock 무시 (테스트 결과와 무관).
            pass


if __name__ == "__main__":
    main()
