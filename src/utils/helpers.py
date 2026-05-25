# -*- coding: utf-8 -*-
"""
시장 운영 시간 등 공통 헬퍼.

KST 시간 처리는 src/utils/timekit.py 로 단일화되어 있으며, 본 모듈은
호환성과 의미적 명확성을 위해 thin wrapper 만 제공한다. 신규 호출부는
가능한 한 timekit 을 직접 사용한다.
"""
from src.utils.timekit import (
    KST,
    is_market_open as _is_market_open_impl,
    kst_strftime,
)
from src.utils.market_calendar import is_trading_day as _is_trading_day_impl


def is_market_open():
    """한국 주식 장중 여부 (KST 거래일 09:00 ~ 15:30)."""
    return _is_market_open_impl()


def is_trading_day(now=None):
    """KST 거래일 여부 (평일 + KRX 공휴일 제외)."""
    return _is_trading_day_impl(now)


def get_current_kst_time():
    """현재 KST 시각 문자열 (YYYY-MM-DD HH:MM:SS KST)."""
    return kst_strftime("%Y-%m-%d %H:%M:%S KST")


__all__ = ["KST", "is_market_open", "is_trading_day", "get_current_kst_time"]
