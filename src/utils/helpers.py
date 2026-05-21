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


def is_market_open():
    """한국 주식 시장 개장 여부 (KST 평일 09:00 ~ 15:30)."""
    return _is_market_open_impl()


def get_current_kst_time():
    """현재 KST 시각 문자열 (YYYY-MM-DD HH:MM:SS KST)."""
    return kst_strftime("%Y-%m-%d %H:%M:%S KST")


__all__ = ["KST", "is_market_open", "get_current_kst_time"]
