# -*- coding: utf-8 -*-
"""
drive_oauth_token.json 상태 확인 및 access token 갱신.

Google Cloud OAuth 'Testing' 모드:
  - refresh token 이 만료/revoke 될 수 있음 (약 7일, 미사용 시 등)
  - 테스트 사용자 목록에 Gmail 이 있어야 함

사용법:
  python scripts/drive_oauth_refresh.py           # 상태만 확인
  python scripts/drive_oauth_refresh.py --refresh # 만료 시 갱신 시도
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="만료된 access token 을 refresh_token 으로 갱신",
    )
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(args.env_file or os.path.join(ROOT, ".env"))
    except ImportError:
        pass

    from src.memory.oauth_token import check_oauth_token_status, refresh_oauth_token

    print("=== Drive OAuth 토큰 상태 ===\n")
    status = check_oauth_token_status()
    print(f"  경로: {status['path']}")
    print(f"  존재: {status['exists']}")
    print(f"  유효: {status['valid']}")
    print(f"  만료됨: {status['expired']}")
    print(f"  refresh_token: {status['has_refresh_token']}")
    if status.get("expiry_kst"):
        print(f"  만료 시각(KST): {status['expiry_kst']}")
    print(f"  재인증 필요: {status['needs_reauth']}")
    print(f"  메시지: {status['message']}")

    if not args.refresh:
        if status["needs_reauth"]:
            print("\n조치: python scripts/drive_oauth_setup.py --no-browser")
        elif status["expired"] and status["has_refresh_token"]:
            print("\n조치: python scripts/drive_oauth_refresh.py --refresh")
        else:
            print("\n[OK] 추가 조치 없음")
        return

    print("\n=== refresh 시도 ===")
    ok, msg = refresh_oauth_token(save=True)
    print(f"  결과: {'성공' if ok else '실패'}")
    print(f"  {msg}")

    if not ok:
        print("\n재발급: python scripts/drive_oauth_setup.py --no-browser")
        sys.exit(1)

    status2 = check_oauth_token_status()
    print(f"\n갱신 후 유효: {status2['valid']}, 만료(KST): {status2.get('expiry_kst', '-')}")


if __name__ == "__main__":
    main()
