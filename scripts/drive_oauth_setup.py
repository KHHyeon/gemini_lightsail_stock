# -*- coding: utf-8 -*-
"""
[1회 실행] 개인 Gmail Drive 쓰기용 OAuth 토큰 발급.

서버(Ubuntu SSH)에는 브라우저가 없으므로 기본값은 --no-browser (콘솔 인증).

사전 준비 (Google Cloud Console):
  1. Drive API 활성화
  2. OAuth 2.0 클라이언트 ID (데스크톱 앱)
  3. OAuth 동의 화면: Testing 이면 테스트 사용자에 Gmail 등록
  4. client_secret JSON 다운로드

.env:
  GOOGLE_DRIVE_OAUTH_CLIENT_FILE=/path/to/client_secret.json

사용법:
  # 서버 SSH (권장)
  python scripts/drive_oauth_setup.py --no-browser

  # PC 브라우저 자동 열기
  python scripts/drive_oauth_setup.py

  # SSH 포트 포워딩 후 로컬 콜백 (다른 터미널에서 ssh -L 8080:127.0.0.1:8080 ...)
  python scripts/drive_oauth_setup.py --local-server --port 8080

토큰 상태/갱신:
  python scripts/drive_oauth_refresh.py
  python scripts/drive_oauth_refresh.py --refresh
"""
import argparse
import os
import sys
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _load_env():
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass


def _has_gui_browser():
    try:
        webbrowser.get()
        return True
    except webbrowser.Error:
        return False


def _run_console_flow(flow):
    """브라우저 없음: URL 출력 후 인증 코드 붙여넣기 (refresh_token 확보용 offline)."""
    print("=" * 60)
    print("1) 아래 URL을 PC/휴대폰 브라우저에서 엽니다.")
    print("2) Quant_Logs 소유 Gmail 로 로그인 후 Drive 권한 허용.")
    print("3) 화면에 나온 인증 코드를 복사해 이 터미널에 붙여넣습니다.")
    print("   (Testing 모드: OAuth 동의 화면에 테스트 사용자로 등록된 계정만 가능)")
    print("=" * 60)

    try:
        if hasattr(flow, "run_console"):
            return flow.run_console(
                authorization_prompt_message="인증 URL:",
                code_verifier_prompt_message="인증 코드 입력: ",
            )
    except TypeError:
        pass

    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    print(auth_url)
    print("=" * 60)
    code = input("인증 코드: ").strip()
    flow.fetch_token(code=code)
    return flow.credentials


def _run_local_server_flow(flow, port, open_browser):
    if open_browser:
        print("브라우저에서 Google 계정 로그인 및 Drive 권한을 허용하세요.")
    else:
        print("=" * 60)
        print(f"1) 다른 PC에서 SSH 터널: ssh -L {port}:127.0.0.1:{port} user@서버")
        print("2) 아래에 표시될 URL을 브라우저에서 엽니다.")
        print("=" * 60)
    return flow.run_local_server(
        port=port,
        open_browser=open_browser,
        authorization_prompt_message="인증 URL (브라우저에서 열기):",
        success_message="인증 완료. 이 창을 닫고 터미널로 돌아가세요.",
    )


def main():
    parser = argparse.ArgumentParser(description="Drive OAuth 토큰 최초 발급")
    parser.add_argument("--client-file", help="OAuth client_secret.json 경로")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="콘솔 인증 (서버 SSH 기본 권장)",
    )
    parser.add_argument(
        "--local-server",
        action="store_true",
        help="localhost 콜백 (SSH -L 포워딩 필요)",
    )
    parser.add_argument("--port", type=int, default=8080, help="local server 포트")
    args = parser.parse_args()

    _load_env()

    client_path = (args.client_file or os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "")).strip()
    if not client_path or not os.path.isfile(client_path):
        print("[FAIL] GOOGLE_DRIVE_OAUTH_CLIENT_FILE 경로가 없습니다.")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)

    use_console = args.no_browser or (not args.local_server and not _has_gui_browser())
    if use_console:
        creds = _run_console_flow(flow)
    else:
        creds = _run_local_server_flow(flow, args.port, open_browser=not args.no_browser)

    from src.memory.oauth_token import get_token_path

    out = get_token_path()
    with open(out, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"[OK] 토큰 저장: {out}")
    print("상태 확인: python scripts/drive_oauth_refresh.py")
    print("폴더 생성: python scripts/drive_folder_bootstrap.py")


if __name__ == "__main__":
    main()
