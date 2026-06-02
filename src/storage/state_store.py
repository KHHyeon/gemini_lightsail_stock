# -*- coding: utf-8 -*-
"""state_store — 영속화 도메인 API.

호출자는 본 모듈만 사용한다. 백엔드(Drive/SQLite/PG) 종류와 파일명·테이블명은
캡슐화되어 호출자에 노출되지 않는다.

Phase 1 (현재): 모든 도메인은 ``_DriveBackend`` 로 위임. 동작은 기존과 100% 동일.
Phase 2 예정: 환경변수 ``STATE_STORE_BACKEND=sqlite`` 로 백엔드 교체. 호출자 영향 0.

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# 내부 파일명 매핑 (Phase 1). 호출자는 본 상수에 직접 접근하지 않는다.
# Phase 2 에서는 SQLite 테이블 매핑으로 치환된다.
# ---------------------------------------------------------------------------
_FILENAME_PORTFOLIO = "paper_portfolio.json"
_FILENAME_SPLIT_ORDERS = "split_orders.json"
_FILENAME_THEME_CONTEXT = "theme_context.json"
_FILENAME_SCALP_SESSION = "scalp_session.json"
_FILENAME_TRADES = "paper_trades.json"

_RESET_DOMAIN_LIST = [
    ("portfolio", _FILENAME_PORTFOLIO, dict),
    ("split_orders", _FILENAME_SPLIT_ORDERS, dict),
    ("theme_context", _FILENAME_THEME_CONTEXT, dict),
    ("trades", _FILENAME_TRADES, list),
]


# ---------------------------------------------------------------------------
# 백엔드 인터페이스 + 기본 구현 (Drive 위임)
# ---------------------------------------------------------------------------
class _DriveBackend:
    """Phase 1 백엔드: 기존 logger 모듈에 위임하여 Drive/로컬 폴백 흐름을 그대로 사용."""

    def read_json(self, filename: str, default: Any) -> Any:
        from src.utils import logger

        data = logger.load_json_from_gdrive(filename)
        return data if data is not None else default

    def write_json(self, filename: str, data: Any) -> None:
        from src.utils import logger

        logger.save_json_to_gdrive(data, filename)


_backend = _DriveBackend()


# ---------------------------------------------------------------------------
# Domain A. 운영 상태
# ---------------------------------------------------------------------------
def get_portfolio() -> dict:
    return _backend.read_json(_FILENAME_PORTFOLIO, {}) or {}


def save_portfolio(portfolio_dict: dict) -> None:
    if not isinstance(portfolio_dict, dict):
        raise TypeError("portfolio_dict must be dict")
    _backend.write_json(_FILENAME_PORTFOLIO, portfolio_dict)


def get_split_orders() -> dict:
    return _backend.read_json(_FILENAME_SPLIT_ORDERS, {}) or {}


def save_split_orders(split_orders_dict: dict) -> None:
    if not isinstance(split_orders_dict, dict):
        raise TypeError("split_orders_dict must be dict")
    _backend.write_json(_FILENAME_SPLIT_ORDERS, split_orders_dict)


def get_theme_context() -> dict:
    return _backend.read_json(_FILENAME_THEME_CONTEXT, {}) or {}


def save_theme_context(theme_dict: dict) -> None:
    if not isinstance(theme_dict, dict):
        raise TypeError("theme_dict must be dict")
    _backend.write_json(_FILENAME_THEME_CONTEXT, theme_dict)


def get_scalp_session():
    """단타 세션 페이로드. 없으면 ``None`` 반환 (기존 호출부의 None 분기 호환)."""
    data = _backend.read_json(_FILENAME_SCALP_SESSION, None)
    if not isinstance(data, dict):
        return None
    return data


def save_scalp_session(session_dict: dict) -> None:
    if not isinstance(session_dict, dict):
        raise TypeError("session_dict must be dict")
    _backend.write_json(_FILENAME_SCALP_SESSION, session_dict)


# ---------------------------------------------------------------------------
# Domain B. 거래 이력 (append-only 의미. Phase 2 에서 append_trade 추가 예정)
# ---------------------------------------------------------------------------
def list_trades() -> list:
    return _backend.read_json(_FILENAME_TRADES, []) or []


def replace_trades(trades_list: list) -> None:
    if not isinstance(trades_list, list):
        raise TypeError("trades_list must be list")
    _backend.write_json(_FILENAME_TRADES, trades_list)


# ---------------------------------------------------------------------------
# 일괄 초기화 (슬랙 !초기화 명령 전용)
# ---------------------------------------------------------------------------
def reset_app_data() -> None:
    """portfolio / split_orders / theme_context / trades 4 도메인 초기화."""
    for _name, filename, kind in _RESET_DOMAIN_LIST:
        empty_value = [] if kind is list else {}
        _backend.write_json(filename, empty_value)
