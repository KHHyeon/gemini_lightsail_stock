# -*- coding: utf-8 -*-
"""KIS Open API 토큰 캐시 관리 (24시간 TTL)."""
import os
from datetime import datetime, timedelta

import requests

from src.utils.jsonio import read_local_json, write_local_json
from src.utils.paths import project_root

TOKEN_FILE = "token_info.json"
TOKEN_TTL_HOURS = 24
KIS_TOKEN_ENDPOINT = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"


def _token_path():
    return os.path.join(project_root(), TOKEN_FILE)


def get_access_token(app_key, secret_key, force=False):
    """KIS Open API access token 발급/캐시.

    Args:
        app_key / secret_key: KIS API 키 쌍.
        force: True 면 캐시 무시하고 강제 재발급.
    """
    if not force:
        cached = read_local_json(_token_path(), default=None) or {}
        issued_at_str = cached.get("issued_at")
        token = cached.get("access_token")
        if token and issued_at_str:
            try:
                issued_at_dt = datetime.strptime(issued_at_str, "%Y-%m-%d %H:%M:%S")
                if datetime.now() < issued_at_dt + timedelta(hours=TOKEN_TTL_HOURS):
                    return token
            except ValueError:
                pass

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
