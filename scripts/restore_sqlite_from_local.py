"""LightSail 로컬 백업 디렉터리 -> SQLite 수동 복원 스크립트 (정책 SCP/Local).

운영자가 SSH/CLI 로 명시적으로 실행하는 단방향 스크립트. 자동 복원은
의도적으로 미지원 (P4F6). 봇이 라이브 DB 를 점유 중이면 안전 가드로
즉시 차단한다 (P4F7-1).

흐름 상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §13.7

종료 코드:
    0 - 정상 (또는 ``--list`` / ``--dry-run`` 정상).
    1 - 백업 파일 미발견.
    2 - 봇 실행 중이어서 차단 (``--force`` 없을 시).
    3 - 압축 풀이 / 원자적 교체 실패.
    4 - integrity_check 실패 (P4E5).
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from typing import Any, Callable, Dict, List, Literal, Optional


# scripts/_common.py 경로 활성화 (sys.path 등록).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=False)

# DRY: backup 스크립트의 helper 재사용 (KST / listing / 슬랙).
from backup_sqlite_local import (  # noqa: E402
    _BACKUP_FILE_PREFIX,
    _BACKUP_FILE_SUFFIX,
    _format_kst_stamp,
    _kst_now,
    _list_kind_files,
    _parse_stamp_to_kst,
    _resolve_slack_notifier,
    _send_slack,
)


_VALID_KIND_LIST = ("daily", "weekly", "monthly")


def _is_db_in_use(target_path: str) -> bool:
    """``target_path`` 가 다른 프로세스에 의해 점유 중인지 점검 (P4F7-1).

    1. ``lsof`` (Ubuntu/macOS 기본) → 동일 inode 점유 여부.
    2. ``fuser`` 폴백.
    3. 둘 다 실패하면 보수적으로 False (점검 도구 부재).
       단, ``-wal`` / ``-shm`` 파일이 존재하면 SQLite 가 활성 상태일 가능성 높으므로 True 로 분류.
    """
    if not os.path.exists(target_path):
        return False

    abs_path = os.path.abspath(target_path)
    for cmd in (["lsof", "--", abs_path], ["fuser", abs_path]):
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and (proc.stdout.strip() or proc.stderr.strip()):
            return True
        if proc.returncode == 0:
            return False

    wal_path = abs_path + "-wal"
    shm_path = abs_path + "-shm"
    if os.path.exists(wal_path) or os.path.exists(shm_path):
        return True
    return False


def _format_size(num_bytes: int) -> str:
    """사람이 읽기 쉬운 사이즈 포맷."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes}{unit}"
        num_bytes //= 1024
    return f"{num_bytes}TB"


def _list_all_backups(backup_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """daily/weekly/monthly 의 모든 백업 메타데이터 수집.

    Returns:
        ``{kind: [{filename, stamp, size, dt}], ...}``.
    """
    result: Dict[str, List[Dict[str, Any]]] = {kind: [] for kind in _VALID_KIND_LIST}
    for kind in _VALID_KIND_LIST:
        for filename in _list_kind_files(backup_dir, kind):
            abs_path = os.path.join(backup_dir, kind, filename)
            stamp_dt = _parse_stamp_to_kst(filename)
            stamp_raw = filename
            if stamp_raw.startswith(_BACKUP_FILE_PREFIX):
                stamp_raw = stamp_raw[len(_BACKUP_FILE_PREFIX):]
            if stamp_raw.endswith(_BACKUP_FILE_SUFFIX):
                stamp_raw = stamp_raw[: -len(_BACKUP_FILE_SUFFIX)]
            result[kind].append({
                "filename": filename,
                "stamp": stamp_raw,
                "size": os.path.getsize(abs_path),
                "dt": stamp_dt,
            })
    return result


def _print_listing(meta_map: Dict[str, List[Dict[str, Any]]]) -> None:
    """``--list`` 출력. 사양 §02 §9.4 의 표 형식 따름."""
    for kind in _VALID_KIND_LIST:
        rows = meta_map.get(kind, [])
        print_flush(f"=== {kind} ({len(rows)}건) ===")
        for row in rows:
            print_flush(f"  {row['filename']}  {_format_size(row['size'])}")
        if not rows:
            print_flush("  (empty)")


def _resolve_source_file(
    backup_dir: str,
    *,
    kind: str,
    stamp: Optional[str],
) -> Optional[str]:
    """``--latest`` 또는 ``--stamp`` 분기로 source 파일명 결정.

    Returns:
        rel_path (예: ``daily/autostock-20260606-1800.db.gz``) 또는 None.
    """
    files = _list_kind_files(backup_dir, kind)
    if not files:
        return None
    if stamp is None:
        return f"{kind}/{files[-1]}"
    target_filename = f"{_BACKUP_FILE_PREFIX}{stamp}{_BACKUP_FILE_SUFFIX}"
    if target_filename not in files:
        return None
    return f"{kind}/{target_filename}"


def _gunzip_file(src_path: str, dst_path: str) -> int:
    """``src_path`` (.gz) 를 ``dst_path`` 로 압축 풀이. 결과 크기 반환."""
    parent_dir = os.path.dirname(os.path.abspath(dst_path))
    os.makedirs(parent_dir, exist_ok=True)
    if os.path.exists(dst_path):
        os.remove(dst_path)
    with gzip.open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return os.path.getsize(dst_path)


def _integrity_check(db_path: str) -> str:
    """``PRAGMA integrity_check`` 실행 후 첫 row 반환."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    if not rows:
        return "no_result"
    return str(rows[0][0])


def run_restore(
    *,
    kind: Literal["daily", "weekly", "monthly"],
    target_path: str,
    backup_dir: str,
    stamp: Optional[str] = None,
    notify_fn: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """단일 복원 사이클 (6단계).

    Returns:
        result dict (사양 §02 §9.4 참조).
    """
    if kind not in _VALID_KIND_LIST:
        raise ValueError(f"kind 는 {_VALID_KIND_LIST} 중 하나여야 합니다 (현재: {kind!r}).")

    started_at = time.monotonic()
    now_kst = _kst_now()
    target_path = os.path.abspath(target_path)
    backup_dir = os.path.abspath(backup_dir)

    result: Dict[str, Any] = {
        "kind": kind,
        "stamp": stamp or "",
        "gz_size": 0,
        "restored_db_size": 0,
        "integrity_check": "",
        "backup_of_target": "",
        "elapsed_ms": 0,
        "status": "ok",
    }

    print_flush(
        f"[Step 1/6] kind={kind} stamp={stamp or '<latest>'} "
        f"target={target_path} backup_dir={backup_dir}"
    )

    print_flush("[Step 2/6] source 파일 결정")
    source_rel = _resolve_source_file(backup_dir, kind=kind, stamp=stamp)
    if source_rel is None:
        message = (
            f"[Restore FAIL] step=resolve_source | err=백업 파일 미발견 "
            f"(kind={kind}, stamp={stamp or '<latest>'}, backup_dir={backup_dir})"
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "source_not_found"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(1)
    source_abs = os.path.join(backup_dir, source_rel)
    result["gz_size"] = os.path.getsize(source_abs)
    resolved_filename = os.path.basename(source_rel)
    if stamp is None:
        stripped = resolved_filename
        if stripped.startswith(_BACKUP_FILE_PREFIX):
            stripped = stripped[len(_BACKUP_FILE_PREFIX):]
        if stripped.endswith(_BACKUP_FILE_SUFFIX):
            stripped = stripped[: -len(_BACKUP_FILE_SUFFIX)]
        result["stamp"] = stripped
    print_flush(f"  source {source_rel} ({_format_size(result['gz_size'])})")

    print_flush(f"[Step 3/6] 봇 실행 점검 (target={target_path})")
    if not force and _is_db_in_use(target_path):
        message = (
            "[Restore FAIL] step=preflight | err=봇이 실행 중일 가능성 (lsof / wal / shm 감지). "
            "운영자 조치: 먼저 s-stop 후 재시도. (--force 옵션으로 우회 가능, 위험)."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "bot_running"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(2)

    print_flush("[Step 4/6] gunzip -> staging/restored.db")
    staging_dir = os.path.join(backup_dir, "staging")
    os.makedirs(staging_dir, exist_ok=True)
    staging_db = os.path.join(staging_dir, "restored.db")
    try:
        result["restored_db_size"] = _gunzip_file(source_abs, staging_db)
    except Exception as exc:
        message = (
            f"[Restore FAIL] step=gunzip | err={type(exc).__name__}: {exc}\n"
            "운영자 조치: .gz 파일 손상 가능성 — 다른 stamp 로 재시도."
        )
        print_flush(message)
        traceback.print_exc()
        _send_slack(message, notify_fn)
        result["status"] = "gunzip_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(3)
    print_flush(f"  staging .db {result['restored_db_size']} bytes")

    print_flush("[Step 5/6] integrity_check")
    try:
        integrity = _integrity_check(staging_db)
    except Exception as exc:
        try:
            os.remove(staging_db)
        except OSError:
            pass
        message = (
            f"[Restore FAIL] step=integrity_check | err={type(exc).__name__}: {exc}\n"
            "운영자 조치: SQLite 라이브러리 / .gz 손상 점검."
        )
        print_flush(message)
        traceback.print_exc()
        _send_slack(message, notify_fn)
        result["status"] = "integrity_exception"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(4)
    result["integrity_check"] = integrity
    print_flush(f"  integrity={integrity}")
    if integrity != "ok":
        try:
            os.remove(staging_db)
        except OSError:
            pass
        message = (
            f"[Restore FAIL] step=integrity_check | err=integrity={integrity!r}\n"
            "운영자 조치: 백업 파일 손상. 다른 stamp 로 재시도 권고."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "integrity_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(4)

    if dry_run:
        try:
            os.remove(staging_db)
        except OSError:
            pass
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        result["elapsed_ms"] = elapsed_ms
        message = (
            f"[Restore DRY-RUN OK] {kind} {result['stamp']} | "
            f"size={result['restored_db_size']//1024}KB | integrity=ok | "
            f"elapsed={elapsed_ms//1000}s"
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        return result

    print_flush("[Step 6/6] atomic rename (target.bak-* + 신규 적용)")
    bak_path = ""
    if os.path.exists(target_path):
        bak_stamp = _format_kst_stamp(now_kst)
        bak_path = f"{target_path}.bak-{bak_stamp}"
        try:
            os.rename(target_path, bak_path)
        except OSError as exc:
            try:
                os.remove(staging_db)
            except OSError:
                pass
            message = (
                f"[Restore FAIL] step=backup_target | "
                f"err={type(exc).__name__}: {exc}"
            )
            print_flush(message)
            _send_slack(message, notify_fn)
            result["status"] = "rename_failed"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            sys.exit(3)

    target_parent = os.path.dirname(target_path)
    if target_parent:
        os.makedirs(target_parent, exist_ok=True)
    try:
        os.replace(staging_db, target_path)
    except OSError as exc:
        if bak_path and os.path.exists(bak_path):
            try:
                os.replace(bak_path, target_path)
            except OSError:
                pass
        message = (
            f"[Restore FAIL] step=install | "
            f"err={type(exc).__name__}: {exc}\n"
            "기존 DB 자동 롤백 시도. 수동 점검 필요."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "install_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(3)
    result["backup_of_target"] = bak_path

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    result["elapsed_ms"] = elapsed_ms

    message = (
        f"[Restore OK] {kind} {result['stamp']} -> {target_path} | "
        f"size={result['restored_db_size']//1024}KB | integrity=ok | "
        f"elapsed={elapsed_ms//1000}s"
    )
    print_flush(message)
    _send_slack(message, notify_fn)
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LightSail 로컬 백업 디렉터리 -> SQLite 수동 복원 (정책 SCP/Local)",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="사용 가능한 백업 파일 나열 (kind/stamp/size).",
    )
    mode_group.add_argument(
        "--latest",
        action="store_true",
        help="가장 최신 백업으로 복원. --kind 미지정 시 daily.",
    )
    mode_group.add_argument(
        "--stamp",
        default=None,
        help="특정 시점 복원. 형식: YYYYMMDD-HHMM. --kind 와 함께 사용.",
    )
    parser.add_argument(
        "--kind",
        default="daily",
        choices=list(_VALID_KIND_LIST),
        help="복원할 백업 종류 (기본: daily).",
    )
    parser.add_argument(
        "--target-path",
        default=os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db"),
        help="복원 대상 DB 경로 (기본: STATE_STORE_DB_PATH).",
    )
    parser.add_argument(
        "--backup-dir",
        default=os.getenv("BACKUP_LOCAL_DIR", "data/backup_local"),
        help="백업 소스 디렉터리 (기본: BACKUP_LOCAL_DIR).",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="슬랙 보고 생략.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="압축 풀이 + integrity_check 까지만. INSTALL 미실행.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="봇 실행 점검 우회 (위험. 운영자 명시 책임).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    notify_fn = _resolve_slack_notifier(args.no_slack)
    backup_dir = os.path.abspath(args.backup_dir)

    if args.list_only:
        meta_map = _list_all_backups(backup_dir)
        _print_listing(meta_map)
        return 0

    if args.stamp is not None:
        kind = args.kind
        stamp = args.stamp
    else:
        kind = args.kind
        stamp = None

    try:
        result = run_restore(
            kind=kind,
            stamp=stamp,
            target_path=args.target_path,
            backup_dir=backup_dir,
            notify_fn=notify_fn,
            dry_run=args.dry_run,
            force=args.force,
        )
    except SystemExit:
        raise
    except Exception as exc:
        message = (
            f"[Restore FAIL] uncaught | kind={kind} | "
            f"err={type(exc).__name__}: {exc}"
        )
        print_flush(message)
        traceback.print_exc()
        _send_slack(message, notify_fn)
        return 3

    status = result.get("status", "ok")
    if status == "ok":
        return 0
    if status == "source_not_found":
        return 1
    if status == "bot_running":
        return 2
    if status in {"integrity_failed", "integrity_exception"}:
        return 4
    return 3


if __name__ == "__main__":
    sys.exit(main())
