# -*- coding: utf-8 -*-
"""KRX 거래일·장중 판별 (공휴일 JSON + 주말).

상세: Doc/features/market_calendar/02_market_calendar_api_spec.md
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

from src.utils.jsonio import read_local_json
from src.utils.paths import project_root
from src.utils.timekit import KST, now_kst

_HOLIDAY_FILE = os.path.join(project_root(), "data", "krx_holidays.json")
_holiday_date_set = None
_holiday_label_map = {}  # date -> 사유 라벨 (있는 경우만)
_holiday_file_warned = False
_holiday_load_status = {
    "file_exists": False,
    "file_path": _HOLIDAY_FILE,
    "count": 0,
    "extra_count": 0,
    "schema_version": None,
    "loaded": False,
}


def load_holiday_date_set(*, reload=False):
    """KRX 공휴일 date set (lazy load)."""
    global _holiday_date_set, _holiday_label_map, _holiday_file_warned
    if _holiday_date_set is not None and not reload:
        return _holiday_date_set

    holiday_set = set()
    label_map = {}
    file_exists = os.path.isfile(_HOLIDAY_FILE)
    _holiday_load_status["file_exists"] = file_exists
    if not file_exists:
        if not _holiday_file_warned:
            print(
                f"Log: [MarketCalendar] 휴장일 파일 없음: {_HOLIDAY_FILE} "
                "(주말만 제외. KRX_HOLIDAYS_EXTRA 또는 data/krx_holidays.json 배포 필요)"
            )
            _holiday_file_warned = True
    payload = read_local_json(_HOLIDAY_FILE, default=None) or {}
    _holiday_load_status["schema_version"] = payload.get("schema_version")
    for raw in payload.get("holidays") or []:
        try:
            holiday_set.add(date.fromisoformat(str(raw).strip()))
        except ValueError:
            continue
    # details_YYYY 매핑은 사유 노출에 사용. 키 형식: "details_2026" 같은 yearly map.
    for key, mapping in (payload.items() if isinstance(payload, dict) else []):
        if not isinstance(key, str) or not key.startswith("details_"):
            continue
        if not isinstance(mapping, dict):
            continue
        for raw_date, label in mapping.items():
            try:
                d = date.fromisoformat(str(raw_date).strip())
            except ValueError:
                continue
            if isinstance(label, str) and label.strip():
                label_map[d] = label.strip()

    extra_count = 0
    extra = (os.getenv("KRX_HOLIDAYS_EXTRA") or "").strip()
    if extra:
        for part in extra.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                holiday_set.add(date.fromisoformat(part))
                extra_count += 1
            except ValueError:
                continue

    _holiday_date_set = holiday_set
    _holiday_label_map = label_map
    _holiday_load_status.update({
        "count": len(holiday_set),
        "extra_count": extra_count,
        "loaded": True,
    })
    return _holiday_date_set


def get_holiday_label(now=None):
    """입력일이 공휴일이면 사유 라벨(있을 때) 또는 빈 문자열을 반환.

    거래일이면 None 을 반환.
    """
    current = _as_kst_datetime(now)
    if current.weekday() >= 5:
        return "주말"
    holiday_set = load_holiday_date_set()
    if current.date() not in holiday_set:
        return None
    return _holiday_label_map.get(current.date(), "")


def get_holiday_load_status():
    """기동·진단용 — 휴장일 파일 로드 상태 dict 반환."""
    if not _holiday_load_status.get("loaded"):
        load_holiday_date_set()
    return dict(_holiday_load_status)


def _as_kst_datetime(now):
    if now is None:
        return now_kst()
    if isinstance(now, datetime):
        current = now
    else:
        current = datetime.combine(now, time(12, 0))
    if current.tzinfo is None:
        return current.replace(tzinfo=KST)
    return current.astimezone(KST)


def is_trading_day(now=None):
    """KST 거래일 여부 (평일 + 공휴일 제외)."""
    current = _as_kst_datetime(now)
    if current.weekday() >= 5:
        return False
    return current.date() not in load_holiday_date_set()


def is_market_hours(now=None):
    """KST 장중 여부 (거래일 09:00~15:30)."""
    current = _as_kst_datetime(now)
    if not is_trading_day(current):
        return False
    start_time = current.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = current.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= current <= end_time


def is_first_trading_day_of_week(now=None):
    """해당 ISO 주의 첫 거래일인지 (월 공휴 시 다음 거래일)."""
    current = _as_kst_datetime(now)
    if not is_trading_day(current):
        return False
    monday = current.date() - timedelta(days=current.weekday())
    probe = monday
    while probe < current.date():
        probe_dt = datetime.combine(probe, time(12, 0), tzinfo=KST)
        if is_trading_day(probe_dt):
            return False
        probe += timedelta(days=1)
    return True
