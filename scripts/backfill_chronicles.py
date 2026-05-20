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

    # 기존 백필 결과 초기화 (master_index 에서 source=backfill 엔트리 제거 + state 초기화)
    python scripts/backfill_chronicles.py --reset

    # 초기화 + .md 리포트 파일까지 Drive 에서 삭제
    python scripts/backfill_chronicles.py --reset --purge-reports

    # 초기화 후 즉시 새 백필 실행 (가장 깔끔한 재구축)
    python scripts/backfill_chronicles.py --reset --purge-reports --lookback 60 --run

    # AI 호출 비용 최소화 - .md 리포트는 그대로 두고 keyphrases 만 v3.2 포맷으로 재추출
    python scripts/backfill_chronicles.py --reindex --delay 3

    # master_index 와 분리된 백필 표식(.md) 만 청소 (T-Day 리포트는 절대 안 건드림)
    python scripts/backfill_chronicles.py --purge-orphan-reports
    # 실삭제 없이 어떤 파일이 대상인지만 보고 (드라이런)
    python scripts/backfill_chronicles.py --purge-orphan-reports --dry-run

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
        "--reset",
        action="store_true",
        help="기존 백필 결과 초기화 (master_index 의 source=backfill 엔트리 + backfill_state 비움)",
    )
    parser.add_argument(
        "--purge-reports",
        action="store_true",
        help="--reset 과 함께 사용 시 .md 리포트 파일까지 Drive 에서 삭제",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="기존 .md 리포트는 보존하고 keyphrases 만 v3.2 포맷으로 재추출하여 master_index 갱신",
    )
    parser.add_argument(
        "--purge-orphan-reports",
        action="store_true",
        help="master_index 에 없는 백필 표식 .md (헤더 '(Backfill)') 만 청소. T-Day 리포트는 보호.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="--purge-orphan-reports 와 함께 사용 시 실제 삭제 없이 대상만 보고",
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

    if args.reset:
        print("\n[초기화] 기존 백필 결과 정리 중...")
        result = backfill.reset_backfill(
            delete_reports=args.purge_reports, notify_fn=_print
        )
        print(
            f"\n[초기화 결과] master_index 제거 {result['removed_entries']}건 / "
            f".md 삭제 {result['deleted_reports']}건"
        )
        if not (args.run or args.scan_only or args.reindex):
            print("\n[종료] 초기화만 수행했습니다. 새로 채우려면 --run 을 함께 사용하세요.")
            return

    if args.reindex:
        print(f"\n[재인덱싱] 기존 백필 엔트리 keyphrases v3.2 재추출 (건당 {args.delay}초)")
        result = backfill.reindex_keyphrases(notify_fn=_print, delay_sec=args.delay)
        print(
            f"\n[재인덱싱 결과] 갱신 {result['updated']} / 스킵 {result['skipped']} / 실패 {result['failed']}"
        )
        return

    if args.purge_orphan_reports:
        mode = "DRY-RUN" if args.dry_run else "실삭제"
        print(f"\n[고아 청소 - {mode}] reports 트리에서 백필 표식 .md 식별 중...")
        result = backfill.purge_orphan_backfill_reports(notify_fn=_print, dry_run=args.dry_run)
        print(
            f"\n[고아 청소 결과] 스캔 {result['scanned']} / 백필 고아 {result['backfill_orphans']} / 삭제 {result['deleted']}"
        )
        return

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
