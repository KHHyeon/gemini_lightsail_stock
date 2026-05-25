# -*- coding: utf-8 -*-
"""KIS Open API 토큰 캐시 관리 (24시간 TTL + scheduled/on-demand 정책).

상세: Doc/features/kis_token/02_kis_token_api_spec.md
"""
import os
from datetime import datetime, timedelta

import requests

from src.utils.jsonio import read_local_json, write_local_json
from src.utils.paths import project_root

TOKEN_FILE = "token_info.json"
TOKEN_TTL_HOURS = 24
DEFAULT_MIN_INTERVAL_MIN = 60
KIS_TOKEN_ENDPOINT = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"


def _token_path():
    return os.path.join(project_root(), TOKEN_FILE)


def _min_interval_minutes():
    try:
        return max(1, int(os.getenv("KIS_TOKEN_MIN_INTERVAL_MIN", str(DEFAULT_MIN_INTERVAL_MIN))))
    except (TypeError, ValueError):
        return DEFAULT_MIN_INTERVAL_MIN


def _parse_issued_at(issued_at_str):
    if not issued_at_str:
        return None
    try:
        return datetime.strptime(issued_at_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _read_cache():
    return read_local_json(_token_path(), default=None) or {}


def _minutes_since_issue(issued_at_dt):
    if issued_at_dt is None:
        return None
    return (datetime.now() - issued_at_dt).total_seconds() / 60.0


def _is_cache_valid(cached, *, ignore_ttl=False):
    token = cached.get("access_token")
    issued_at_dt = _parse_issued_at(cached.get("issued_at"))
    if not token or issued_at_dt is None:
        return False
    if ignore_ttl:
        return True
    return datetime.now() < issued_at_dt + timedelta(hours=TOKEN_TTL_HOURS)


def get_token_cache_info():
    """캐시 메타 조회 (디버그/테스트)."""
    cached = _read_cache()
    issued_at_dt = _parse_issued_at(cached.get("issued_at"))
    minutes = _minutes_since_issue(issued_at_dt)
    expires_at = None
    if issued_at_dt is not None:
        expires_at = (issued_at_dt + timedelta(hours=TOKEN_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "has_token": bool(cached.get("access_token")),
        "issued_at": cached.get("issued_at"),
        "expires_at": expires_at,
        "minutes_since_issue": minutes,
        "is_valid": _is_cache_valid(cached),
    }


def _request_new_token(app_key, secret_key):
    print("Log: KIS 서버에 새 토큰을 요청합니다.")
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": secret_key,
    }
    try:
        res = requests.post(KIS_TOKEN_ENDPOINT, json=body, timeout=10)
        res.raise_for_status()
        token = res.json().get("access_token")
    except requests.RequestException as e:
        print(f"Log: [Token Manager] 발급 실패: {e}")
        return None
    except ValueError:
        return None

    if not token:
        return None
    write_local_json(
        _token_path(),
        {
            "access_token": token,
            "issued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        indent=2,
    )
    return token


def get_access_token(app_key, secret_key, force=False, *, context="on_demand"):
    """KIS Open API access token 발급/캐시.

    Args:
        app_key / secret_key: KIS API 키 쌍.
        force: True 면 TTL/간격 무시 즉시 재발급.
        context: ``on_demand`` | ``scheduled`` (08:00 거래일 갱신).
    """
    cached = _read_cache()
    cached_token = cached.get("access_token")
    issued_at_dt = _parse_issued_at(cached.get("issued_at"))
    minutes = _minutes_since_issue(issued_at_dt)

    if force:
        return _request_new_token(app_key, secret_key)

    if context == "scheduled":
        from src.utils.market_calendar import is_trading_day

        if not is_trading_day():
            return cached_token if _is_cache_valid(cached) else None
        if minutes is not None and minutes < _min_interval_minutes():
            return cached_token if _is_cache_valid(cached, ignore_ttl=True) else cached_token
        # 거래일 scheduled: 24h 미경과여도 갱신 (1h 간격만 준수)
        return _request_new_token(app_key, secret_key)

    # on_demand
    if _is_cache_valid(cached):
        return cached_token
    return _request_new_token(app_key, secret_key)


def issue_scheduled_token(app_key, secret_key):
    """거래일 08:00 스케줄용 토큰 발급."""
    from src.utils.market_calendar import is_trading_day

    cached = _read_cache()
    cached_token = cached.get("access_token")

    if not is_trading_day():
        return {
            "issued": False,
            "reason": "not_trading_day",
            "token": cached_token if _is_cache_valid(cached) else None,
        }

    issued_at_dt = _parse_issued_at(cached.get("issued_at"))
    minutes = _minutes_since_issue(issued_at_dt)
    if minutes is not None and minutes < _min_interval_minutes():
        return {
            "issued": False,
            "reason": "min_interval",
            "token": cached_token if cached_token else None,
        }

    token = _request_new_token(app_key, secret_key)
    if token:
        return {"issued": True, "reason": "scheduled_refresh", "token": token}
    return {
        "issued": False,
        "reason": "request_failed",
        "token": cached_token if _is_cache_valid(cached) else None,
    }
