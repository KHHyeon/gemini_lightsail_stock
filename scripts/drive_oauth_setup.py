# -*- coding: utf-8 -*-
"""
[1회 실행] 개인 Gmail Drive 쓰기용 OAuth 토큰 발급.

필수: Google Cloud OAuth 클라이언트 유형 = **데스크톱 앱 (Desktop app)**
      (웹 애플리케이션 JSON 은 redirect_uri 오류 발생)

서버 SSH:
  python scripts/drive_oauth_setup.py --no-browser

클라이언트 JSON 검증만:
  python scripts/drive_oauth_setup.py --check-client
"""
import argparse
import json
import os
import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

from _common import load_env_file, setup_script_path

ROOT = setup_script_path()

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _load_env():
    load_env_file()


def validate_client_secrets(client_path):
    """
  client_secret JSON 유형 검증.
  Returns: (client_type, section_dict)
  """
    with open(client_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "installed" in data:
        section = data["installed"]
        return "installed", section

    if "web" in data:
        print("[FAIL] 이 JSON 은 '웹 애플리케이션' 유형입니다.")
        print("  InstalledAppFlow 는 '데스크톱 앱' 클라이언트 ID 가 필요합니다.")
        print()
        print("  Google Cloud Console -> 사용자 인증 정보 ->")
        print("  + 사용자 인증 정보 만들기 -> OAuth 클라이언트 ID ->")
        print("  애플리케이션 유형: **데스크톱 앱** -> JSON 다시 다운로드")
        sys.exit(1)

    print("[FAIL] client_secret JSON 에 'installed' 또는 'web' 키가 없습니다.")
    sys.exit(1)


def resolve_redirect_uri(installed_section, port=8080, prefer_oob=False):
    """
    redirect_uri 결정 (authorization_url / fetch_token 에 동일하게 사용).
    """
    uris = installed_section.get("redirect_uris") or []

    if prefer_oob and "urn:ietf:wg:oauth:oauth2:out-of-band" in uris:
        return "urn:ietf:wg:oauth:oauth2:out-of-band"

    port_uri = f"http://localhost:{port}/"
    port_uri_alt = f"http://127.0.0.1:{port}/"

    for candidate in (port_uri, port_uri_alt, "http://localhost", "http://127.0.0.1"):
        if candidate in uris:
            return candidate

    # 데스크톱 앱은 loopback 동적 포트 허용 (JSON 에 포트 없어도 됨)
    return port_uri


def create_flow(client_path):
    """InstalledAppFlow 생성 + redirect_uri 사전 검증."""
    client_type, section = validate_client_secrets(client_path)
    if client_type != "installed":
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
    return flow, section


def _parse_auth_code(user_input):
    """인증 코드 또는 리다이렉트 전체 URL 에서 code 추출."""
    text = (user_input or "").strip()
    if not text:
        return None

    if "code=" in text:
        if text.startswith("http"):
            qs = parse_qs(urlparse(text).query)
        else:
            qs = parse_qs(text.lstrip("?"))
        codes = qs.get("code", [])
        return codes[0] if codes else None

    return text


def _run_manual_flow(flow, redirect_uri):
    """서버 SSH: URL 출력 -> 브라우저 인증 -> code 붙여넣기."""
    flow.redirect_uri = redirect_uri

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    print("=" * 60)
    print(f"redirect_uri: {redirect_uri}")
    print()
    print("1) 아래 URL 을 PC/휴대폰 브라우저에서 엽니다.")
    print("2) Gmail 로그인 후 Drive 권한 허용.")
    print("3) 리다이렉트 후 주소창 URL 전체 또는 code= 뒤 값을 붙여넣습니다.")
    print("   (localhost 연결 실패 화면이어도 주소창 URL 은 복사 가능)")
    print("   Testing 모드: OAuth 테스트 사용자에 Gmail 등록 필수")
    print("=" * 60)
    print(auth_url)
    print("=" * 60)

    raw = input("인증 코드 또는 리다이렉트 URL: ").strip()
    code = _parse_auth_code(raw)
    if not code:
        print("[FAIL] code 를 찾을 수 없습니다.")
        sys.exit(1)

    flow.fetch_token(code=code)
    return flow.credentials


def _run_local_server_flow(flow, redirect_uri, port, open_browser):
    flow.redirect_uri = redirect_uri
    if open_browser:
        print("브라우저에서 Google 로그인 및 Drive 권한을 허용하세요.")
    else:
        print("=" * 60)
        print(f"redirect_uri: {redirect_uri}")
        print(f"SSH 터널 (PC에서): ssh -L {port}:127.0.0.1:{port} user@서버")
        print("이후 아래 URL 을 브라우저에서 엽니다.")
        print("=" * 60)
    return flow.run_local_server(
        host="localhost",
        port=port,
        open_browser=open_browser,
        authorization_prompt_message="인증 URL:",
        success_message="인증 완료. 터미널로 돌아가세요.",
    )


def _has_gui_browser():
    try:
        webbrowser.get()
        return True
    except webbrowser.Error:
        return False


def main():
    parser = argparse.ArgumentParser(description="Drive OAuth 토큰 최초 발급")
    parser.add_argument("--client-file", help="OAuth client_secret.json 경로")
    parser.add_argument(
        "--check-client",
        action="store_true",
        help="JSON 이 데스크톱 앱 유형인지만 검사",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="수동 code 입력 (서버 SSH 기본)",
    )
    parser.add_argument(
        "--local-server",
        action="store_true",
        help="localhost 콜백 서버 (SSH -L 포워딩)",
    )
    parser.add_argument("--port", type=int, default=8080, help="local server 포트")
    args = parser.parse_args()

    _load_env()

    client_path = (args.client_file or os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "")).strip()
    if not client_path or not os.path.isfile(client_path):
        print("[FAIL] GOOGLE_DRIVE_OAUTH_CLIENT_FILE 경로가 없습니다.")
        sys.exit(1)

    client_type, section = validate_client_secrets(client_path)
    uris = section.get("redirect_uris", [])
    print(f"[OK] 클라이언트 유형: {client_type} (데스크톱 앱)")
    print(f"     등록된 redirect_uris: {uris}")

    if args.check_client:
        return

    flow, section = create_flow(client_path)
    redirect_uri = resolve_redirect_uri(section, port=args.port)

    if args.local_server:
        creds = _run_local_server_flow(
            flow, redirect_uri, args.port, open_browser=not args.no_browser
        )
    elif args.no_browser or not _has_gui_browser():
        creds = _run_manual_flow(flow, redirect_uri)
    else:
        creds = _run_local_server_flow(flow, redirect_uri, args.port, open_browser=True)

    from src.memory.oauth_token import get_token_path

    out = get_token_path()
    with open(out, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    has_refresh = bool(getattr(creds, "refresh_token", None))
    print(f"[OK] 토큰 저장: {out}")
    print(f"     refresh_token: {'있음' if has_refresh else '없음 (재실행 시 --no-browser 로 consent 재요청)'}")
    print("다음: python scripts/drive_oauth_refresh.py")
    print("      python scripts/drive_folder_bootstrap.py")


if __name__ == "__main__":
    main()
