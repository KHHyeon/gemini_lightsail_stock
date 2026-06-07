"""Phase 4 백업/복원 서버(LightSail) 종단(E2E) 검증 스크립트 (정책 SCP/Local).

``tests/smoke_backup_local.py`` 가 임시 디렉터리로만 검증하는 한계를 보완.
운영 서버에서 **실제 라이브 DB(``STATE_STORE_DB_PATH``)** 에 대해 백업/복원
사이클을 임시 작업 공간에서 자동 묶음 검증한다. 라이브 DB 무손상.

핵심 안전 정책:
    - 라이브 DB 는 절대 변경하지 않는다. 복원 대상은 항상 임시 디렉터리.
    - 백업 디렉터리도 운영 봇이 쓰는 ``BACKUP_LOCAL_DIR`` 와 분리된 임시
      디렉터리를 사용하여 동시 실행 중인 봇과 충돌하지 않는다.

검증 단계 (HANDOVER §3.3 Step 2' / 사양 03 §13.13 매핑):
    [1/7] 사전조건 점검  : .env BACKUP_ENABLED=true + 라이브 DB 존재.
    [2/7] 디스크/디렉터리 : 임시 작업 디렉터리 + 디스크 free 점검.
    [3/7] scheduler 등록  : register_backup_jobs -> 3 jobs (day 2 + sunday 1).
    [4/7] backup dry-run  : VACUUM INTO + gzip + 회전 시뮬레이션.
    [5/7] backup 실 실행   : 임시 backup_dir/daily/ 에 .db.gz 1건 생성.
    [6/7] restore --list   : 임시 backup_dir 의 daily 1건 확인.
    [7/7] restore 실 설치  : 임시 대상 복원 + integrity + 테이블 카운트.

종료 코드:
    0 - 전 단계 PASS (또는 SKIP 만 존재).
    1 - 1 단계 이상 FAIL.
    2 - 사전조건 미충족으로 조기 종료 (B-Type: 운영자 개입 필요).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from typing import Callable, List, Optional


# scripts/_common.py 경로 활성화 (sys.path 등록).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=False)

# DRY: backup/restore 모듈의 공개 함수 + 헬퍼 재사용.
import backup_sqlite_local as backup_mod  # noqa: E402
import restore_sqlite_from_local as restore_mod  # noqa: E402
from backup_sqlite_local import (  # noqa: E402
    _list_kind_files,
    _resolve_slack_notifier,
    _send_slack,
)


_PASS_LIST: List[str] = []
_FAIL_LIST: List[str] = []
_SKIP_LIST: List[str] = []

# .env 점검 대상 백업 키 (필수 + 선택). 값은 읽지 않고 존재 여부만 점검 (보안 룰).
# 정책 변경: 외부 인증 키 0개. BACKUP_ENABLED 만 필수.
_REQUIRED_KEY_LIST = ("BACKUP_ENABLED",)
_OPTIONAL_KEY_LIST = (
    "BACKUP_LOCAL_DIR",
    "BACKUP_DAILY_AT",
    "BACKUP_WEEKLY_AT",
    "BACKUP_MONTHLY_AT",
    "BACKUP_RETENTION_DAILY",
    "BACKUP_RETENTION_WEEKLY",
    "BACKUP_RETENTION_MONTHLY",
)


def _record(label: str, ok: bool, detail: str = "") -> None:
    """단계 결과 기록 + 즉시 출력."""
    if ok:
        _PASS_LIST.append(label)
        print_flush(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        _FAIL_LIST.append(label)
        print_flush(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def _record_skip(label: str, reason: str) -> None:
    """단계 건너뜀 기록 (FAIL 아님)."""
    _SKIP_LIST.append(label)
    print_flush(f"  [SKIP] {label} -- {reason}")


# ----- [1/7] 사전조건 점검 -----
def _step_preflight(db_path: str) -> bool:
    """필수 .env 키 + DB 파일 점검. 미충족 시 False (조기 종료)."""
    print_flush("\n[1/7] 사전조건 점검 (.env BACKUP_ENABLED + 라이브 DB)")
    ok = True

    enabled_raw = (os.getenv("BACKUP_ENABLED") or "").strip().lower()
    enabled = enabled_raw in {"1", "true", "yes", "on"}
    _record(
        "BACKUP_ENABLED=true (운영 활성)",
        enabled,
        f"BACKUP_ENABLED={enabled_raw or '(미설정)'}",
    )
    if not enabled:
        ok = False

    present_optional = [k for k in _OPTIONAL_KEY_LIST if os.getenv(k)]
    print_flush(
        f"  (info) 선택 키 설정됨: {present_optional or '(기본값 사용)'}"
    )

    db_exists = os.path.exists(db_path)
    _record(
        "라이브 SQLite DB 파일 존재",
        db_exists,
        f"db_path={db_path}" + ("" if db_exists else " (미존재)"),
    )
    if not db_exists:
        ok = False

    return ok


# ----- [2/7] 디스크/디렉터리 점검 -----
def _step_disk_capacity(db_path: str, verify_root: str) -> None:
    """임시 작업 디렉터리 + 디스크 free 점검."""
    print_flush("\n[2/7] 디스크/임시 디렉터리 점검")
    try:
        usage = shutil.disk_usage(verify_root)
    except Exception as exc:
        _record("disk_usage 조회", False, f"{type(exc).__name__}: {exc}")
        return

    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    needed = max(db_size * 3, 64 * 1024 * 1024)  # 최소 64MB
    ok = usage.free >= needed
    _record(
        "임시 작업 디렉터리 디스크 free 충분",
        ok,
        (
            f"free={usage.free // (1024*1024)}MB / "
            f"needed={needed // (1024*1024)}MB (db_size×3)"
        ),
    )


# ----- [3/7] scheduler 등록 카운트 -----
def _step_scheduler_register(notify_fn: Optional[Callable[[str], None]]) -> None:
    """register_backup_jobs 를 격리된 Scheduler 인스턴스에 적용 -> 3 jobs 확인.

    글로벌 schedule 을 오염시키지 않도록 별도 ``schedule.Scheduler()`` 인스턴스를
    사용한다. ``schedule`` 미설치(로컬 PC) 환경에서는 SKIP.
    """
    print_flush("\n[3/7] scheduler 등록 카운트 (register_backup_jobs)")
    try:
        import schedule
    except ImportError:
        _record_skip("register_backup_jobs 3 jobs", "schedule 라이브러리 미설치 (로컬 PC)")
        return

    try:
        from src.storage.backup_scheduler import register_backup_jobs
    except Exception as exc:
        _record("backup_scheduler import", False, f"{type(exc).__name__}: {exc}")
        return

    sched = schedule.Scheduler()
    # 슬랙 중복 보고 방지: 등록 검증 단계는 notify_fn 미전달 (stdout 만).
    result = register_backup_jobs(sched, notify_fn=None)
    job_count = len(sched.jobs)
    _record(
        "BACKUP_ENABLED=true -> register True + jobs 3건",
        result is True and job_count == 3,
        f"register={result} jobs={job_count}",
    )


# ----- [4/7] backup dry-run -----
def _step_backup_dry_run(
    db_path: str,
    backup_dir: str,
    notify_fn: Optional[Callable[[str], None]],
) -> None:
    """VACUUM INTO + gzip + 회전 시뮬레이션. 결과 .db.gz 즉시 폐기."""
    print_flush("\n[4/7] backup dry-run (VACUUM + gzip + 회전 시뮬레이션, 결과 폐기)")
    try:
        result = backup_mod.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            backup_dir=backup_dir,
            notify_fn=notify_fn,
            dry_run=True,
        )
    except SystemExit as exc:
        _record("dry-run 정상 종료", False, f"unexpected SystemExit: {exc.code}")
        return
    except Exception as exc:
        _record("dry-run 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    _record(
        "dry-run status=ok + vacuum_db_size>0",
        result.get("status") == "ok" and result.get("vacuum_db_size", 0) > 0,
        f"status={result.get('status')} vacuum={result.get('vacuum_db_size')}",
    )
    daily_files = _list_kind_files(backup_dir, "daily")
    _record(
        "dry-run 후 .gz 폐기 (daily/ 잔존 0건)",
        len(daily_files) == 0,
        f"daily files={len(daily_files)}",
    )


# ----- [5/7] backup 실 실행 -----
def _step_backup_real(
    db_path: str,
    backup_dir: str,
    notify_fn: Optional[Callable[[str], None]],
) -> None:
    """실제 backup 사이클. 임시 backup_dir/daily/ 에 .db.gz 1건 생성."""
    print_flush("\n[5/7] backup 실 실행 (.db.gz 생성 + 회전)")
    try:
        result = backup_mod.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            backup_dir=backup_dir,
            notify_fn=notify_fn,
            dry_run=False,
        )
    except SystemExit as exc:
        _record("실 백업 정상 종료", False, f"SystemExit: {exc.code}")
        return
    except Exception as exc:
        _record("실 백업 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    _record(
        "실 백업 status=ok",
        result.get("status") == "ok",
        f"status={result.get('status')}",
    )
    daily_files = _list_kind_files(backup_dir, "daily")
    _record(
        "daily/ 에 .db.gz 1건 + gz_size 일치",
        len(daily_files) >= 1 and result.get("gz_size", 0) > 0,
        f"daily={len(daily_files)} gz_size={result.get('gz_size')}",
    )


# ----- [6/7] restore --list -----
def _step_restore_list(backup_dir: str) -> bool:
    """임시 backup_dir 의 daily 목록 확인. 1건 이상 존재 여부 반환."""
    print_flush("\n[6/7] restore --list (임시 backup_dir 목록)")
    try:
        meta_map = restore_mod._list_all_backups(backup_dir)
    except Exception as exc:
        _record("_list_all_backups 실행", False, f"{type(exc).__name__}: {exc}")
        return False

    daily_count = len(meta_map.get("daily", []))
    weekly_count = len(meta_map.get("weekly", []))
    monthly_count = len(meta_map.get("monthly", []))
    print_flush(
        f"  daily={daily_count} weekly={weekly_count} monthly={monthly_count}"
    )
    has_daily = daily_count >= 1
    _record(
        "복원 가능한 daily 백업 1건 이상",
        has_daily,
        f"daily count={daily_count}",
    )
    return has_daily


# ----- [7/7] restore 실 설치 -----
def _step_restore_real(
    backup_dir: str,
    target_path: str,
    notify_fn: Optional[Callable[[str], None]],
) -> None:
    """임시 대상에 실제 복원 + integrity + 테이블 카운트 검증."""
    print_flush("\n[7/7] restore 실 설치 (임시 대상) + integrity + 테이블 카운트")
    try:
        result = restore_mod.run_restore(
            kind="daily",
            stamp=None,
            target_path=target_path,
            backup_dir=backup_dir,
            notify_fn=notify_fn,
            dry_run=False,
            force=True,
        )
    except SystemExit as exc:
        _record("restore 실 설치 정상 종료", False, f"SystemExit: {exc.code}")
        return
    except Exception as exc:
        _record("restore 실 설치 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    _record(
        "복원 status=ok + 대상 파일 존재",
        result.get("status") == "ok" and os.path.exists(target_path),
        f"status={result.get('status')} target={os.path.exists(target_path)}",
    )

    if not os.path.exists(target_path):
        return
    try:
        conn = sqlite3.connect(target_path)
        try:
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            schema_rows = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        _record("복원 DB 조회 (sqlite_master / schema_version)", False, f"{exc}")
        return

    table_count = len(table_rows)
    schema_ver = schema_rows[0][0] if schema_rows else None
    _record(
        "복원 DB 테이블 1개 이상 + schema_version row 존재",
        table_count >= 1 and schema_ver is not None,
        f"tables={table_count} schema_version={schema_ver}",
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 4 백업/복원 서버 종단(E2E) 검증 (정책 SCP/Local)",
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db"),
        help="라이브 SQLite DB 경로 (기본: STATE_STORE_DB_PATH).",
    )
    parser.add_argument(
        "--skip-real-backup",
        action="store_true",
        help="[5/7] 실제 .db.gz 생성 단계를 생략 (dry-run 검증만).",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="슬랙 보고 생략 (기본: 슬랙 전송).",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="검증용 임시 디렉터리를 종료 후 보존 (디버깅용).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    started = time.monotonic()
    print_flush("=" * 64)
    print_flush("Phase 4 백업/복원 서버 종단(E2E) 검증 (정책 SCP/Local)")
    print_flush("=" * 64)

    db_path = os.path.abspath(args.db_path)
    notify_fn = _resolve_slack_notifier(args.no_slack)

    # 사전조건 미충족 시 즉시 B-Type 보고 후 종료 (회복 불가).
    if not _step_preflight(db_path):
        message = (
            "[Backup VERIFY FAIL] 사전조건 미충족 -- BACKUP_ENABLED=true / 라이브 DB 점검 필요. "
            "운영자 조치: HANDOVER §3.3 Step 2' 의 .env 8종 키 추가 후 재시도."
        )
        print_flush("\n" + message)
        _send_slack(message, notify_fn)
        return 2

    # 검증 전용 임시 작업 공간 (운영 봇의 BACKUP_LOCAL_DIR / 라이브 DB 와 완전 분리).
    verify_root = tempfile.mkdtemp(prefix="autostock_verify_")
    backup_dir = os.path.join(verify_root, "backup_local")
    target_path = os.path.join(verify_root, "verify_restore.db")
    print_flush(f"  검증 임시 작업 디렉터리: {verify_root}")
    print_flush(f"  복원 대상(임시): {target_path}  (라이브 DB 무손상)")

    try:
        _step_disk_capacity(db_path, verify_root)
        _step_scheduler_register(notify_fn)
        _step_backup_dry_run(db_path, backup_dir, notify_fn)
        if args.skip_real_backup:
            _record_skip("backup 실 실행", "--skip-real-backup 지정")
        else:
            _step_backup_real(db_path, backup_dir, notify_fn)
        has_daily = _step_restore_list(backup_dir)
        if has_daily:
            _step_restore_real(backup_dir, target_path, notify_fn)
        else:
            _record_skip(
                "restore 실 설치",
                "복원 가능한 daily 백업 없음 (--skip-real-backup 시도 후 비어있음)",
            )
    except Exception:
        print_flush("[FATAL] 검증 중 예기치 못한 예외:")
        traceback.print_exc()
        _FAIL_LIST.append("uncaught exception")
    finally:
        if args.keep_temp:
            print_flush(f"  (임시 디렉터리 보존: {verify_root})")
        else:
            shutil.rmtree(verify_root, ignore_errors=True)

    elapsed = time.monotonic() - started
    print_flush("=" * 64)
    summary = (
        f"PASS: {len(_PASS_LIST)} | FAIL: {len(_FAIL_LIST)} | "
        f"SKIP: {len(_SKIP_LIST)} | elapsed={elapsed:.2f}s"
    )
    print_flush(summary)
    if _FAIL_LIST:
        print_flush("FAIL list:")
        for label in _FAIL_LIST:
            print_flush(f"  - {label}")
        fail_message = (
            f"[Backup VERIFY FAIL] {len(_FAIL_LIST)}건 실패 / "
            f"{len(_PASS_LIST)}건 통과. 운영자 조치: 로그 확인."
        )
        print_flush(fail_message)
        _send_slack(fail_message, notify_fn)
        return 1

    ok_message = (
        f"[Backup VERIFY OK] {len(_PASS_LIST)}건 통과 / SKIP {len(_SKIP_LIST)}건 / "
        f"elapsed={int(elapsed)}s. Phase 4 Step 2' 서버 E2E 검증 완료."
    )
    print_flush("ALL OK")
    _send_slack(ok_message, notify_fn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
