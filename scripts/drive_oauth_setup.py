# -*- coding: utf-8 -*-
"""
[1회 실행] 개인 Gmail Drive 쓰기용 OAuth 토큰 발급.

서비스 계정은 저장 용량이 없어 Quant_Logs 같은 개인 공유 폴더에
파일을 만들 수 없습니다. 이 스크립트로 사용자 OAuth 토큰을 만듭니다.

사전 준비 (Google Cloud Console):
  1. Drive API 활성화
  2. OAuth 2.0 클라이언트 ID (데스크톱 앱) 생성
  3. client_secret JSON 다운로드

.env:
  GOOGLE_DRIVE_OAUTH_CLIENT_FILE=/path/to/client_secret_xxxxx.json

실행 (브라우저 있는 PC 또는 SSH -L 포워딩):
  python scripts/drive_oauth_setup.py

생성 파일: 프로젝트 루트/drive_oauth_token.json (서버에 복사)
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-file", help="OAuth client_secret.json 경로")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass

    client_path = (args.client_file or os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "")).strip()
    if not client_path or not os.path.isfile(client_path):
        print("[FAIL] GOOGLE_DRIVE_OAUTH_CLIENT_FILE 경로가 없습니다.")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = ["https://www.googleapis.com/auth/drive"]
    flow = InstalledAppFlow.from_client_secrets_file(client_path, scopes)
    print("브라우저에서 Google 계정 로그인 및 Drive 권한을 허용하세요.")
    creds = flow.run_local_server(port=0)

    out = os.path.join(ROOT, "drive_oauth_token.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"[OK] 토큰 저장: {out}")
    print("서버에 이 파일을 복사한 뒤 bootstrap 을 다시 실행하세요.")


if __name__ == "__main__":
    main()
