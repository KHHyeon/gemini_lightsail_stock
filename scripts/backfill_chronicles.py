# -*- coding: utf-8 -*-
"""
Market Chronicles v3.1 - 과거 데이터 소급 구축 (Back-filling) CLI.

사용 예시:
    # 최근 60일 스캔만 (큐 저장 + 콘솔 출력)
    python scripts/backfill_chronicles.py --scan-only

    # 저장된 큐에 대해 실행 (건당 3초 대기)
    python scripts/backfill_chronicles.py --run

    # 스캔과 동시에 실행, 소급 기간 90일, 건당 5초 대기
    python scripts/backfill_chronicles.py --lookback 90 --run --delay 5

전제 조건:
    - drive_oauth_token.json 발급 완료 (scripts/drive_oauth_setup.py)
    - Drive 폴더 구조 생성 완료 (scripts/drive_folder_bootstrap.py)
    - .env 의 GOOGLE_API_KEY (Gemini), GOOGLE_DRIVE_OAUTH_CLIENT_FILE 등 설정
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_env(env_file=None):
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[WARN] python-dotenv 미설치. 시스템 환경 변수만 사용합니다.")
        return
    path = env_file or os.path.join(ROOT, ".env")
    if os.path.isfile(path):
        load_dotenv(path, override=True)
        print(f"  .env 로드: {path}")
    else:
        print(f"  [WARN] .env 파일 없음: {path}")


def _print(msg):
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Market Chronicles 과거 데이터 소급 구축 (Back-filling)"
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=60,
        help="소급 일수 (기본 60일)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=3,
        help="리포트 1건 완료 후 대기 초 (Rate Limit 보호, 기본 3초)",
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="스캔과 큐 저장만 수행하고 실제 작성은 하지 않음",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="저장된 큐를 즉시 실행 (스캔과 함께 호출 시 스캔 -> 실행 순)",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="대체 .env 파일 경로",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" Market Chronicles v3.1 Back-filling CLI")
    print("=" * 60)

    _load_env(args.env_file)

    from src.memory import backfill, drive_client

    if not drive_client.is_drive_enabled():
        print("[FAIL] Drive 가 비활성 상태입니다 (GOOGLE_DRIVE_ENABLED=0).")
        sys.exit(1)
    if not drive_client.is_drive_configured():
        print("[FAIL] Drive 미설정. .env 의 OAuth/Service Account 경로를 확인하세요.")
        sys.exit(1)

    if not drive_client.is_ready():
        ok, msg = drive_client.init_drive_or_pause(notify_fn=_print)
        if not ok:
            print(f"[FAIL] Drive 초기화 실패: {msg}")
            sys.exit(1)

    did_anything = False

    if args.scan_only or not args.run:
        print(f"\n[스캔] 최근 {args.lookback}일 트리거 충족일 추출 중...")
        events = backfill.scan_and_save(lookback_days=args.lookback, notify_fn=_print)
        print(f"\n[스캔 결과] 이벤트 데이 {len(events)}건")
        did_anything = True
        if args.scan_only:
            print("\n[종료] --scan-only 모드. 실행하려면 다음을 사용하세요:")
            print("       python scripts/backfill_chronicles.py --run --delay 3")
            return

    if args.run:
        if not args.scan_only and not did_anything:
            print(f"\n[스캔] 최근 {args.lookback}일 트리거 충족일 추출 중...")
            backfill.scan_and_save(lookback_days=args.lookback, notify_fn=_print)
        print(f"\n[실행] 저장된 큐 처리 시작 (건당 {args.delay}초 대기)")
        result = backfill.run_backfill(notify_fn=_print, delay_sec=args.delay)
        print(
            f"\n[종료] 처리 {result['started']}건 = "
            f"완료 {result['ok']} / 스킵 {result['skipped']} / 실패 {result['failed']}"
        )


if __name__ == "__main__":
    main()
