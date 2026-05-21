# -*- coding: utf-8 -*-
"""
KST 타임존 및 시간 헬퍼 단일 정의.

기존에 main.py / drive_client.py / chronicle_writer.py / oauth_token.py /
lifecycle.py / backfill.py / logger.py 등 7개 파일에 산재되어 있던
`KST = timezone(timedelta(hours=9))` 재선언을 본 모듈로 통합한다.

helpers.py 의 `is_market_open` / `get_current_kst_time` 도 본 모듈의 KST 를
사용하도록 정정하여 pytz 의존을 제거한다.
"""
from datetime import date, datetime, timedelta, timezone


KST = timezone(timedelta(hours=9))


def now_kst():
    """KST 현재 시각 (datetime, tz=KST)."""
    return datetime.now(KST)


def today_kst():
    """KST 기준 오늘 날짜 (date 객체)."""
    return now_kst().date()


def kst_iso_now():
    """KST 현재 시각의 ISO 8601 문자열."""
    return now_kst().isoformat()


def kst_strftime(fmt="%Y-%m-%d %H:%M:%S"):
    """KST 현재 시각을 지정 포맷 문자열로 반환 (기본 'YYYY-MM-DD HH:MM:SS')."""
    return now_kst().strftime(fmt)


def parse_iso_to_kst(iso_text):
    """ISO 8601 문자열을 KST datetime 으로 변환.

    naive datetime 이면 KST 로 간주하고 그대로 tz 만 부여한다.
    """
    if not iso_text:
        return None
    try:
        dt = datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def is_market_open(now=None):
    """한국 주식 시장 개장 여부 (KST 평일 09:00 ~ 15:30)."""
    current_time = now if now is not None else now_kst()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=KST)
    if current_time.weekday() >= 5:
        return False
    start_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= current_time <= end_time
