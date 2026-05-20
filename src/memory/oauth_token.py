# -*- coding: utf-8 -*-
"""
Drive OAuth 토큰(drive_oauth_token.json) 상태 확인 및 갱신.

Google Cloud 'Testing' 모드에서는 refresh token 이 만료되거나
revoke 될 수 있으므로 주기적 확인 및 refresh 가 필요하다.
"""
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Testing 모드: refresh token 유효기간이 짧을 수 있음 (약 7일)
TESTING_MODE_WARN_DAYS = 7


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_token_path():
    custom = os.getenv("GOOGLE_DRIVE_OAUTH_TOKEN_FILE", "").strip()
    if custom:
        return custom
    return os.path.join(_project_root(), "drive_oauth_token.json")


def token_file_exists():
    return os.path.isfile(get_token_path())


def _read_token_raw():
    path = get_token_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_credentials(creds):
    path = get_token_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def check_oauth_token_status():
    """
    토큰 상태 dict 반환.
    keys: exists, valid, expired, has_refresh_token, expiry, needs_reauth, message
    """
    path = get_token_path()
    result = {
        "path": path,
        "exists": False,
        "valid": False,
        "expired": False,
        "has_refresh_token": False,
        "expiry": None,
        "expiry_kst": None,
        "needs_reauth": True,
        "message": "",
    }

    raw = _read_token_raw()
    if not raw:
        result["message"] = "drive_oauth_token.json 없음. python scripts/drive_oauth_setup.py --no-browser"
        return result

    result["exists"] = True
    result["has_refresh_token"] = bool(raw.get("refresh_token"))

    expiry_str = raw.get("expiry")
    if expiry_str:
        try:
            expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            result["expiry"] = expiry_str
            result["expiry_kst"] = expiry_dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
            result["expired"] = expiry_dt <= datetime.now(timezone.utc)
        except ValueError:
            result["expired"] = True

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(path, SCOPES)
        result["valid"] = creds.valid
        result["expired"] = creds.expired or result["expired"]

        if creds.valid:
            result["needs_reauth"] = False
            result["message"] = "토큰 유효"
            if creds.expiry:
                exp_kst = creds.expiry.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
                result["expiry_kst"] = exp_kst
                days_left = (creds.expiry - datetime.now(timezone.utc)).days
                if days_left <= TESTING_MODE_WARN_DAYS:
                    result["message"] = (
                        f"토큰 유효 (만료 {exp_kst}). Testing 모드면 만료 전 재발급 권장."
                    )
            return result

        if creds.expired and creds.refresh_token:
            result["needs_reauth"] = False
            result["message"] = "access token 만료. refresh 가능 (ensure_oauth_token_valid 호출)"
            return result

        result["needs_reauth"] = True
        result["message"] = "재인증 필요 (refresh_token 없음 또는 만료)"
        return result

    except Exception as e:
        result["needs_reauth"] = True
        result["message"] = f"토큰 파싱 실패: {e}"
        return result


def refresh_oauth_token(save=True):
    """
    refresh_token 으로 access token 갱신.
    Returns: (success: bool, message: str)
    """
    path = get_token_path()
    if not os.path.isfile(path):
        return False, "토큰 파일 없음"

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(path, SCOPES)

        if creds.valid:
            return True, "이미 유효한 토큰"

        if not creds.refresh_token:
            return False, "refresh_token 없음. drive_oauth_setup.py 로 재발급하세요."

        creds.refresh(Request())
        if save:
            _save_credentials(creds)
        exp = ""
        if creds.expiry:
            exp = creds.expiry.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        return True, f"갱신 완료 (만료: {exp})"

    except Exception as e:
        err = str(e)
        if "invalid_grant" in err.lower() or "token has been expired or revoked" in err.lower():
            return False, (
                "refresh 실패 (Testing 모드 만료 또는 revoke). "
                "python scripts/drive_oauth_setup.py --no-browser 로 재발급"
            )
        return False, f"refresh 실패: {e}"


def ensure_oauth_token_valid(verbose=False):
    """
    토큰 유효 보장. 갱신 시 파일 저장.
    Returns: Credentials or None
    """
    status = check_oauth_token_status()
    if not status["exists"]:
        if verbose:
            print(f"Log: [OAuth] {status['message']}")
        return None

    if status["valid"]:
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_file(get_token_path(), SCOPES)

    if status["expired"] and status["has_refresh_token"]:
        ok, msg = refresh_oauth_token(save=True)
        if verbose:
            print(f"Log: [OAuth] {msg}")
        if ok:
            from google.oauth2.credentials import Credentials

            return Credentials.from_authorized_user_file(get_token_path(), SCOPES)

    if verbose:
        print(f"Log: [OAuth] {status['message']}")
    return None
