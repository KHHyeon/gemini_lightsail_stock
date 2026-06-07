"""SQLite -> LightSail 로컬 디렉터리 백업 스크립트 (정책 SCP/Local).

봇 내부 ``schedule`` 잡(``src.storage.backup_scheduler``)이 daemon thread
에서 본 모듈의 ``run_backup_cycle`` 을 호출하거나, 운영자가 CLI 로 직접
실행한다. 단일 백업 사이클은 7단계로 구성되며, ``VACUUM INTO`` 로 일관된
스냅샷을 추출하고 gzip 압축 후 ``BACKUP_LOCAL_DIR/{daily,weekly,monthly}/``
에 누적·회전한다. 외부 통신/인증 0 — LightSail 디스크 IO 만 사용.

운영자 PC 와의 동기화는 별도 SCP/rsync 채널 (본 모듈 책임 외부).
사양 부록: Doc/features/data_persistence/02_data_persistence_api_spec.md §9.5

흐름 상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §13.4

종료 코드:
    0 - 정상 (회전 실패는 WARN 으로 분류, exit 0 유지). monthly skip_no_daily 도 0.
    1 - VACUUM INTO 실패 (P4E1).
    2 - gzip 실패 (P4E2).
    3 - 사전 점검 실패 (DB 미존재 등).
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Optional


# scripts/_common.py 경로 활성화 (sys.path 등록).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=False)


# KST 타임존 (Asia/Seoul). zoneinfo 미가용 환경 대비 timezone(UTC+9) 폴백.
try:
    from zoneinfo import ZoneInfo

    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = timezone(timedelta(hours=9))


_VALID_KIND_LIST = ("daily", "weekly", "monthly")
_BACKUP_FILE_PREFIX = "autostock-"
_BACKUP_FILE_SUFFIX = ".db.gz"


def _kst_now() -> datetime:
    """KST 현재 시각."""
    return datetime.now(_KST)


def _format_kst_stamp(dt: datetime) -> str:
    """KST 기준 ``YYYYMMDD-HHMM`` 형식 타임스탬프 생성."""
    return dt.astimezone(_KST).strftime("%Y%m%d-%H%M")


def _parse_stamp_to_kst(stamp: str) -> Optional[datetime]:
    """``autostock-YYYYMMDD-HHMM.db.gz`` 또는 ``YYYYMMDD-HHMM`` 에서
    KST datetime 복원. 형식 불일치 시 None.
    """
    raw = stamp
    if raw.startswith(_BACKUP_FILE_PREFIX):
        raw = raw[len(_BACKUP_FILE_PREFIX):]
    if raw.endswith(_BACKUP_FILE_SUFFIX):
        raw = raw[: -len(_BACKUP_FILE_SUFFIX)]
    try:
        dt = datetime.strptime(raw, "%Y%m%d-%H%M")
    except ValueError:
        return None
    return dt.replace(tzinfo=_KST)


def _resolve_slack_notifier(no_slack: bool) -> Optional[Callable[[str], None]]:
    """슬랙 알림 callable 반환. ``--no-slack`` 또는 토큰 없으면 None.

    ``scripts/migrate_drive_to_sqlite.py`` 와 동일 패턴 (DRY 원칙).
    """
    if no_slack:
        return None
    try:
        from slack_sdk import WebClient
    except ImportError:
        return None

    token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")
    if not token or not channel:
        return None
    client = WebClient(token=token)

    def _notify(text: str) -> None:
        client.chat_postMessage(channel=channel, text=text)

    return _notify


def _send_slack(text: str, notify_fn: Optional[Callable[[str], None]]) -> None:
    """슬랙 전송. notify_fn 가 None 이면 무동작. 슬랙 실패는 백업 결과 무효화 안 함."""
    if not callable(notify_fn):
        return
    try:
        notify_fn(text)
    except Exception:
        pass


def _ensure_backup_subdirs(backup_dir: str) -> None:
    """``BACKUP_LOCAL_DIR`` 의 4 개 하위 디렉터리 (staging/daily/weekly/monthly) 보장."""
    for sub in ("staging",) + _VALID_KIND_LIST:
        os.makedirs(os.path.join(backup_dir, sub), exist_ok=True)


def _vacuum_into(db_path: str, output_path: str, *, retry_after_s: float = 60.0) -> None:
    """``VACUUM INTO`` 로 라이브 DB 의 일관된 스냅샷을 ``output_path`` 에 추출.

    실패 시 1회 재시도 후 그래도 실패하면 예외 전파 (P4E1).
    """
    import sqlite3

    parent_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent_dir, exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)

    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(f"VACUUM INTO '{output_path}'")
                return
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if attempt == 0:
                print_flush(
                    f"  [WARN] VACUUM INTO 실패 (1차): {exc}. {int(retry_after_s)}s 후 재시도."
                )
                time.sleep(retry_after_s)
                continue
            raise
    if last_exc is not None:
        raise last_exc


def _gzip_file(src_path: str, dst_path: str, *, compresslevel: int = 6) -> int:
    """``src_path`` 를 gzip 으로 ``dst_path`` 에 압축. 압축본 크기 반환.

    compresslevel 6: 균형(속도/비율). 9 는 느려서 미채택.
    """
    parent_dir = os.path.dirname(os.path.abspath(dst_path))
    os.makedirs(parent_dir, exist_ok=True)
    with open(src_path, "rb") as src, gzip.open(
        dst_path, "wb", compresslevel=compresslevel,
    ) as dst:
        shutil.copyfileobj(src, dst)
    return os.path.getsize(dst_path)


def _list_kind_files(backup_dir: str, kind: str) -> List[str]:
    """``backup_dir/{kind}/`` 의 ``autostock-*.db.gz`` 파일명 목록 (정렬 오름차순)."""
    target_dir = os.path.join(backup_dir, kind)
    if not os.path.isdir(target_dir):
        return []
    file_list: List[str] = []
    for name in os.listdir(target_dir):
        if not name.endswith(_BACKUP_FILE_SUFFIX):
            continue
        if not name.startswith(_BACKUP_FILE_PREFIX):
            continue
        file_list.append(name)
    file_list.sort()
    return file_list


def _retention_cutoff(kind: str, now_kst: datetime) -> datetime:
    """보관 정책 cutoff (kind 별 보존 기간 만료 시각). cutoff 이전 파일은 회전 대상."""
    if kind == "daily":
        days = int(os.getenv("BACKUP_RETENTION_DAILY", "30"))
        return now_kst - timedelta(days=days)
    if kind == "weekly":
        weeks = int(os.getenv("BACKUP_RETENTION_WEEKLY", "12"))
        return now_kst - timedelta(weeks=weeks)
    if kind == "monthly":
        months = int(os.getenv("BACKUP_RETENTION_MONTHLY", "12"))
        return now_kst - timedelta(days=months * 31)
    return now_kst


def _rotate_files(
    backup_dir: str,
    *,
    kind: str,
    now_kst: datetime,
) -> List[str]:
    """보관 정책에 따라 cutoff 이전 파일을 ``os.remove`` 한다 (정책 변경: git rm 폐기).

    Returns:
        회전된 파일 rel_path 목록 (예: ``daily/autostock-20260507-1800.db.gz``).
    """
    cutoff_dt = _retention_cutoff(kind, now_kst)
    rotated_list: List[str] = []
    for filename in _list_kind_files(backup_dir, kind):
        stamp_dt = _parse_stamp_to_kst(filename)
        if stamp_dt is None:
            continue
        if stamp_dt < cutoff_dt:
            rel_path = f"{kind}/{filename}"
            abs_path = os.path.join(backup_dir, rel_path)
            try:
                os.remove(abs_path)
                rotated_list.append(rel_path)
            except OSError as exc:
                print_flush(f"  [WARN] rotate 실패 ({rel_path}): {exc}")
                continue
    return rotated_list


def _promote_monthly_from_daily(
    backup_dir: str, *, stamp: str,
) -> Optional[str]:
    """일간 백업 1개를 monthly/ 디렉터리로 복사 (월간 승격).

    Returns:
        승격된 monthly rel_path. 일간 백업 미존재 시 None.
    """
    daily_files = _list_kind_files(backup_dir, "daily")
    if not daily_files:
        return None
    source_file = daily_files[-1]
    monthly_rel = f"monthly/{_BACKUP_FILE_PREFIX}{stamp}{_BACKUP_FILE_SUFFIX}"
    monthly_abs = os.path.join(backup_dir, monthly_rel)
    monthly_dir = os.path.dirname(monthly_abs)
    os.makedirs(monthly_dir, exist_ok=True)
    shutil.copy(os.path.join(backup_dir, "daily", source_file), monthly_abs)
    return monthly_rel


def run_backup_cycle(
    *,
    kind: Literal["daily", "weekly", "monthly"],
    db_path: str,
    backup_dir: str,
    notify_fn: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """단일 백업 사이클을 수행한다 (7단계).

    Returns:
        result dict (사양 §02 §9.3 참조).
    """
    if kind not in _VALID_KIND_LIST:
        raise ValueError(f"kind 는 {_VALID_KIND_LIST} 중 하나여야 합니다 (현재: {kind!r}).")

    started_at = time.monotonic()
    now_kst = _kst_now()
    stamp = _format_kst_stamp(now_kst)

    backup_dir = os.path.abspath(backup_dir)
    src_db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    result: Dict[str, Any] = {
        "kind": kind,
        "stamp": stamp,
        "src_db_path": db_path,
        "src_db_size": src_db_size,
        "vacuum_db_size": 0,
        "gz_size": 0,
        "gz_file_rel": "",
        "rotated_files_list": [],
        "elapsed_ms": 0,
        "status": "ok",
    }

    print_flush(
        f"[Step 1/7] kind={kind} stamp={stamp} db_path={db_path} backup_dir={backup_dir}"
    )

    if not os.path.exists(db_path):
        message = (
            f"[Backup FAIL] {kind} {stamp} | step=preflight | err=DB 파일 미존재: {db_path}\n"
            "운영자 조치: STATE_STORE_DB_PATH 점검 또는 SQLite 마이그레이션 선행 실행."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "preflight_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        return result

    print_flush("[Step 2/7] 백업 디렉터리 보장 (staging/daily/weekly/monthly)")
    _ensure_backup_subdirs(backup_dir)

    gz_rel_path = ""
    gz_abs_path = ""

    if kind == "monthly":
        print_flush("[Step 3/7] monthly 승격 (daily/ 최신 1개 복사)")
        promoted_rel = _promote_monthly_from_daily(backup_dir, stamp=stamp)
        if promoted_rel is None:
            message = (
                f"[Backup INFO] monthly {stamp} skip — daily 백업 미존재. "
                "다음 월간 트리거 시 재시도."
            )
            print_flush(message)
            _send_slack(message, notify_fn)
            result["status"] = "skip_no_daily"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            return result
        gz_rel_path = promoted_rel
        gz_abs_path = os.path.join(backup_dir, gz_rel_path)
        result["gz_size"] = os.path.getsize(gz_abs_path)
        result["gz_file_rel"] = gz_rel_path
        print_flush(f"  promoted {promoted_rel} ({result['gz_size']} bytes)")
    else:
        print_flush("[Step 4/7] VACUUM INTO staging/")
        staging_path = os.path.join(
            backup_dir, "staging", f"{_BACKUP_FILE_PREFIX}{stamp}.db",
        )
        try:
            _vacuum_into(db_path, staging_path)
        except Exception as exc:
            message = (
                f"[Backup FAIL] {kind} {stamp} | step=vacuum_into | "
                f"err={type(exc).__name__}: {exc}\n"
                "운영자 조치: SQLite 라이브 락 / 디스크 여유 점검 후 재시도."
            )
            print_flush(message)
            traceback.print_exc()
            _send_slack(message, notify_fn)
            result["status"] = "vacuum_failed"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            sys.exit(1)
        result["vacuum_db_size"] = os.path.getsize(staging_path)
        print_flush(f"  staging .db {result['vacuum_db_size']} bytes")

        print_flush(f"[Step 5/7] gzip + 이동 ({kind}/)")
        gz_rel_path = f"{kind}/{_BACKUP_FILE_PREFIX}{stamp}{_BACKUP_FILE_SUFFIX}"
        gz_abs_path = os.path.join(backup_dir, gz_rel_path)
        try:
            result["gz_size"] = _gzip_file(staging_path, gz_abs_path)
        except Exception as exc:
            message = (
                f"[Backup FAIL] {kind} {stamp} | step=gzip | "
                f"err={type(exc).__name__}: {exc}\n"
                "운영자 조치: 디스크 여유 점검."
            )
            print_flush(message)
            traceback.print_exc()
            _send_slack(message, notify_fn)
            result["status"] = "gzip_failed"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            try:
                if os.path.exists(staging_path):
                    os.remove(staging_path)
            except OSError:
                pass
            sys.exit(2)
        try:
            os.remove(staging_path)
        except OSError:
            pass
        result["gz_file_rel"] = gz_rel_path
        print_flush(f"  gz {gz_rel_path} ({result['gz_size']} bytes)")

    if dry_run:
        print_flush("[Step 6/7] dry-run 모드: 회전 시뮬레이션만 수행 후 결과물 폐기")
        rotated_list = _rotate_files(backup_dir, kind=kind, now_kst=now_kst)
        result["rotated_files_list"] = rotated_list
        for rel_path in rotated_list:
            print_flush(f"  rotated (sim) {rel_path}")
        try:
            if gz_abs_path and os.path.exists(gz_abs_path):
                os.remove(gz_abs_path)
        except OSError:
            pass
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        result["elapsed_ms"] = elapsed_ms
        message = (
            f"[Backup DRY-RUN OK] {kind} {stamp} | gz={result['gz_size']//1024}KB | "
            f"rotated={len(rotated_list)} | elapsed={elapsed_ms//1000}s"
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        return result

    print_flush(f"[Step 6/7] 보관 정책 회전 (kind={kind})")
    rotated_list: List[str] = []
    rotate_warn = False
    try:
        rotated_list = _rotate_files(backup_dir, kind=kind, now_kst=now_kst)
        result["rotated_files_list"] = rotated_list
        if rotated_list:
            for rel_path in rotated_list:
                print_flush(f"  rotated {rel_path}")
        else:
            print_flush("  rotate 대상 0건")
    except Exception as exc:
        rotate_warn = True
        print_flush(f"  [WARN] rotate 실패: {exc}")
        traceback.print_exc()

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    result["elapsed_ms"] = elapsed_ms

    print_flush("[Step 7/7] 결과 보고")
    if rotate_warn:
        message = (
            f"[Backup WARN] {kind} {stamp} OK / rotate FAIL — "
            "백업 자체는 성공. 다음 회차 재시도."
        )
    else:
        message = (
            f"[Backup OK] {kind} {stamp} | gz={result['gz_size']//1024}KB | "
            f"rotated={len(rotated_list)} | elapsed={elapsed_ms//1000}s"
        )
    print_flush(message)
    _send_slack(message, notify_fn)
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SQLite -> LightSail 로컬 디렉터리 백업 스크립트 (정책 SCP/Local)",
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=list(_VALID_KIND_LIST),
        help="백업 종류 (daily/weekly/monthly).",
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db"),
        help="SQLite DB 파일 경로 (기본: STATE_STORE_DB_PATH 또는 data/sqlite/autostock.db).",
    )
    parser.add_argument(
        "--backup-dir",
        default=os.getenv("BACKUP_LOCAL_DIR", "data/backup_local"),
        help="백업 누적 디렉터리 (기본: BACKUP_LOCAL_DIR 또는 data/backup_local).",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="슬랙 보고 생략 (로컬 검증용).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="VACUUM INTO + gzip + 회전 시뮬레이션. 결과 .db.gz 즉시 폐기.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    notify_fn = _resolve_slack_notifier(args.no_slack)
    try:
        result = run_backup_cycle(
            kind=args.kind,
            db_path=args.db_path,
            backup_dir=args.backup_dir,
            notify_fn=notify_fn,
            dry_run=args.dry_run,
        )
    except SystemExit:
        raise
    except Exception as exc:
        message = (
            f"[Backup FAIL] uncaught | kind={args.kind} | "
            f"err={type(exc).__name__}: {exc}"
        )
        print_flush(message)
        traceback.print_exc()
        _send_slack(message, notify_fn)
        return 3

    status = result.get("status", "ok")
    if status in {"ok", "skip_no_daily"}:
        return 0
    if status == "preflight_failed":
        return 3
    if status == "vacuum_failed":
        return 1
    if status == "gzip_failed":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
