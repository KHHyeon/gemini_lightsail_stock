"""Phase 4 SCP/Local 백업/복원 smoke 테스트 (12 항목).

본 스크립트는 외부 통신 없이 로컬 임시 디렉터리에서 모든 사이클을
검증한다 (정책 변경: GitHub 의존 0). schedule 라이브러리가 미설치된
환경에서도 자체 ``_StubScheduler`` 로 [3] 단계까지 검증된다.

흐름:
    [1] BACKUP_ENABLED=false -> register 0 jobs.
    [2] BACKUP_ENABLED=true + 8 키 정상 -> register 3 jobs (day 2 + sunday 1).
    [3] backup dry-run -> .gz 폐기 + daily/ 비어있음.
    [4] backup 실 실행 (kind=daily) -> daily/{stamp}.db.gz 1건.
    [5] 회전: 31일 전 1개 + 30일 이내 4개 + 신규 1개 -> 5개 잔존.
    [6] monthly 승격 (daily 1개 -> monthly/).
    [7] monthly 일간 미존재 시 skip + status=skip_no_daily.
    [8] restore --list (`_list_all_backups`) 카운트 정확.
    [9] restore --dry-run -> integrity_check=ok + target 미생성.
    [10] restore 실 설치 -> target 생성 + integrity_check=ok + status=ok.
    [11] 복원 cycle 무손실 (schema_version + portfolio test row 동일).
    [12] 사전 점검 (DB 미존재 시 status=preflight_failed).

종료 코드:
    0 - 12/12 PASS.
    1 - 1건 이상 FAIL.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# 프로젝트 루트 sys.path 등록.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_THIS_DIR)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
_SCRIPTS_DIR = os.path.join(_ROOT_DIR, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


_PASS_LIST: List[str] = []
_FAIL_LIST: List[str] = []


def _record(label: str, ok: bool, detail: str = "") -> None:
    """단계 결과 기록 + 즉시 출력."""
    if ok:
        _PASS_LIST.append(label)
        print(
            f"  [PASS] {label}" + (f" -- {detail}" if detail else ""),
            flush=True,
        )
    else:
        _FAIL_LIST.append(label)
        print(
            f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""),
            flush=True,
        )


# ---------------------------------------------------------------------------
# StubScheduler — schedule 라이브러리 미설치 환경 대응
# ---------------------------------------------------------------------------
class _StubJob:
    def __init__(self, weekday: str, at: str) -> None:
        self.weekday = weekday
        self.at = at
        self._handler = None
        self._kwargs: Dict[str, Any] = {}

    def do(self, func, **kwargs):
        self._handler = func
        self._kwargs = kwargs
        return self


class _StubEvery:
    def __init__(self, scheduler: "_StubScheduler", weekday: str = "day") -> None:
        self._scheduler = scheduler
        self._weekday = weekday

    @property
    def day(self) -> "_StubEvery":
        return _StubEvery(self._scheduler, "day")

    @property
    def sunday(self) -> "_StubEvery":
        return _StubEvery(self._scheduler, "sunday")

    @property
    def monday(self) -> "_StubEvery":
        return _StubEvery(self._scheduler, "monday")

    def __getattr__(self, item: str) -> "_StubEvery":
        if item in {
            "tuesday", "wednesday", "thursday", "friday", "saturday",
        }:
            return _StubEvery(self._scheduler, item)
        raise AttributeError(item)

    def at(self, hhmm: str) -> _StubJob:
        job = _StubJob(self._weekday, hhmm)
        self._scheduler.jobs.append(job)
        return job


class _StubScheduler:
    """``schedule`` 모듈 최소 호환 stub. ``every().day.at("18:00").do(fn)`` 만 지원."""

    def __init__(self) -> None:
        self.jobs: List[_StubJob] = []

    def every(self, interval: int = 1) -> _StubEvery:
        return _StubEvery(self)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _seed_sqlite_db(db_path: str) -> None:
    """smoke 용 최소 SQLite DB 생성 (schema_version + portfolio 1 row)."""
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (1)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS portfolio "
            "(ticker TEXT PRIMARY KEY, qty INTEGER, avg_price REAL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO portfolio (ticker, qty, avg_price) "
            "VALUES ('TEST', 10, 1234.5)"
        )
        conn.commit()
    finally:
        conn.close()


def _setup_env(workspace: str, db_path: str) -> None:
    """smoke 용 환경변수 설정 (8 키)."""
    backup_dir = os.path.join(workspace, "backup_local")
    os.environ["BACKUP_ENABLED"] = "true"
    os.environ["BACKUP_LOCAL_DIR"] = backup_dir
    os.environ["BACKUP_DAILY_AT"] = "18:00"
    os.environ["BACKUP_WEEKLY_AT"] = "sunday 22:00"
    os.environ["BACKUP_MONTHLY_AT"] = "01 00:30"
    os.environ["BACKUP_RETENTION_DAILY"] = "30"
    os.environ["BACKUP_RETENTION_WEEKLY"] = "12"
    os.environ["BACKUP_RETENTION_MONTHLY"] = "12"
    os.environ["STATE_STORE_DB_PATH"] = db_path


def _seed_old_daily_files(backup_dir: str) -> None:
    """회전 검증용 시드: 31일 전 1개 + 30일 이내 4개 (총 5개)."""
    daily_dir = os.path.join(backup_dir, "daily")
    os.makedirs(daily_dir, exist_ok=True)
    now = datetime.now()
    seeds: List[datetime] = [
        now - timedelta(days=31),
        now - timedelta(days=20),
        now - timedelta(days=10),
        now - timedelta(days=5),
        now - timedelta(days=1),
    ]
    for dt in seeds:
        stamp = dt.strftime("%Y%m%d-%H%M")
        path = os.path.join(daily_dir, f"autostock-{stamp}.db.gz")
        with open(path, "wb") as fh:
            fh.write(b"placeholder gzip content")


# ---------------------------------------------------------------------------
# 검증 단계
# ---------------------------------------------------------------------------
def _step_register_disabled() -> None:
    """[1] BACKUP_ENABLED=false -> register 0 jobs."""
    print("\n[1] BACKUP_ENABLED=false -> register 0 jobs", flush=True)
    os.environ["BACKUP_ENABLED"] = "false"
    from src.storage.backup_scheduler import register_backup_jobs

    sched = _StubScheduler()
    result = register_backup_jobs(sched, notify_fn=None)
    _record(
        "register_backup_jobs(BACKUP_ENABLED=false) -> False + jobs=0",
        result is False and len(sched.jobs) == 0,
        f"result={result} jobs={len(sched.jobs)}",
    )


def _step_register_enabled() -> None:
    """[2] BACKUP_ENABLED=true + 8 키 정상 -> register 3 jobs."""
    print("\n[2] BACKUP_ENABLED=true + 8 키 정상 -> register 3 jobs", flush=True)
    os.environ["BACKUP_ENABLED"] = "true"
    from src.storage.backup_scheduler import register_backup_jobs

    sched = _StubScheduler()
    result = register_backup_jobs(sched, notify_fn=None)
    _record(
        "register_backup_jobs(BACKUP_ENABLED=true) -> True + jobs=3",
        result is True and len(sched.jobs) == 3,
        f"result={result} jobs={len(sched.jobs)}",
    )

    weekday_set = {job.weekday for job in sched.jobs}
    weekday_count = {
        "day": sum(1 for j in sched.jobs if j.weekday == "day"),
        "sunday": sum(1 for j in sched.jobs if j.weekday == "sunday"),
    }
    _record(
        "weekday 매핑 (day 2건 + sunday 1건)",
        weekday_count["day"] == 2 and weekday_count["sunday"] == 1,
        f"weekday_set={weekday_set} count={weekday_count}",
    )


def _step_backup_dry_run(db_path: str, backup_dir: str) -> None:
    """[3] backup dry-run -> .gz 폐기 + daily/ 비어있음."""
    print("\n[3] backup dry-run", flush=True)
    import backup_sqlite_local as bm

    try:
        result = bm.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=True,
        )
    except Exception as exc:
        _record("dry-run 실행", False, f"{type(exc).__name__}: {exc}")
        return

    _record(
        "dry-run status=ok + vacuum_db_size>0",
        result.get("status") == "ok" and result.get("vacuum_db_size", 0) > 0,
        f"status={result.get('status')} vacuum={result.get('vacuum_db_size')}",
    )
    daily_files = bm._list_kind_files(backup_dir, "daily")
    _record(
        "dry-run 후 daily/ 잔존 0건",
        len(daily_files) == 0,
        f"daily files={len(daily_files)}",
    )


def _step_backup_first_run(db_path: str, backup_dir: str) -> None:
    """[4] backup 실 실행 -> daily/{stamp}.db.gz 1건."""
    print("\n[4] backup 실 실행 (kind=daily)", flush=True)
    import backup_sqlite_local as bm

    try:
        result = bm.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=False,
        )
    except Exception as exc:
        _record("실 백업 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    _record(
        "실 백업 status=ok",
        result.get("status") == "ok",
        f"status={result.get('status')}",
    )
    daily_files = bm._list_kind_files(backup_dir, "daily")
    gz_rel = result.get("gz_file_rel", "")
    gz_abs = os.path.join(backup_dir, gz_rel) if gz_rel else ""
    actual_size = os.path.getsize(gz_abs) if gz_abs and os.path.exists(gz_abs) else 0
    _record(
        "daily/ 1건 + gz_size 일치",
        len(daily_files) >= 1 and result.get("gz_size", 0) == actual_size,
        f"daily={len(daily_files)} gz_size={result.get('gz_size')} actual={actual_size}",
    )


def _step_retention_rotate(backup_dir: str) -> None:
    """[5] 회전: 31일 전 1개 + 30일 이내 4개 -> 31일 전만 회전, 4개 잔존 + 신규 1개."""
    print("\n[5] 보관 정책 회전", flush=True)
    import backup_sqlite_local as bm

    daily_dir = os.path.join(backup_dir, "daily")
    if os.path.exists(daily_dir):
        shutil.rmtree(daily_dir)
    _seed_old_daily_files(backup_dir)
    seeded_files = bm._list_kind_files(backup_dir, "daily")
    print(f"  seeded daily files: {len(seeded_files)}", flush=True)

    try:
        result = bm.run_backup_cycle(
            kind="daily",
            db_path=os.environ["STATE_STORE_DB_PATH"],
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=False,
        )
    except Exception as exc:
        _record("회전 사이클 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    rotated_list = result.get("rotated_files_list", [])
    daily_files = bm._list_kind_files(backup_dir, "daily")
    _record(
        "31일 전 1개 회전 (rotated=1)",
        len(rotated_list) == 1,
        f"rotated={len(rotated_list)} list={rotated_list}",
    )
    # 시드 5개 + 신규 1개 - 회전 1개 = 5개
    _record(
        "회전 후 daily/ 5건 잔존 (시드 4 + 신규 1)",
        len(daily_files) == 5,
        f"daily files={len(daily_files)}",
    )


def _step_monthly_promotion(db_path: str, backup_dir: str) -> None:
    """[6/7] monthly 승격 + monthly 일간 미존재 시 skip."""
    print("\n[6] monthly 승격", flush=True)
    import backup_sqlite_local as bm

    try:
        result = bm.run_backup_cycle(
            kind="monthly",
            db_path=db_path,
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=False,
        )
    except Exception as exc:
        _record("monthly 승격 실행", False, f"{type(exc).__name__}: {exc}")
        return

    monthly_files = bm._list_kind_files(backup_dir, "monthly")
    _record(
        "monthly 승격 status=ok + monthly/ 1건",
        result.get("status") == "ok" and len(monthly_files) >= 1,
        f"status={result.get('status')} monthly={len(monthly_files)}",
    )

    print("\n[7] monthly skip (daily 미존재)", flush=True)
    # daily/ 비우고 monthly 호출
    empty_workspace = tempfile.mkdtemp(prefix="autostock_smoke_empty_")
    empty_backup = os.path.join(empty_workspace, "backup_local")
    try:
        result = bm.run_backup_cycle(
            kind="monthly",
            db_path=db_path,
            backup_dir=empty_backup,
            notify_fn=None,
            dry_run=False,
        )
    except Exception as exc:
        _record("monthly skip 실행", False, f"{type(exc).__name__}: {exc}")
        shutil.rmtree(empty_workspace, ignore_errors=True)
        return
    finally:
        pass

    _record(
        "monthly skip_no_daily 분기",
        result.get("status") == "skip_no_daily",
        f"status={result.get('status')}",
    )
    shutil.rmtree(empty_workspace, ignore_errors=True)


def _step_restore_list(backup_dir: str) -> None:
    """[8] restore --list (_list_all_backups) 카운트."""
    print("\n[8] restore --list (_list_all_backups)", flush=True)
    import restore_sqlite_from_local as rm

    try:
        meta_map = rm._list_all_backups(backup_dir)
    except Exception as exc:
        _record("_list_all_backups 실행", False, f"{type(exc).__name__}: {exc}")
        return

    daily_count = len(meta_map.get("daily", []))
    monthly_count = len(meta_map.get("monthly", []))
    _record(
        "_list_all_backups daily>=1 + monthly>=1",
        daily_count >= 1 and monthly_count >= 1,
        f"daily={daily_count} monthly={monthly_count}",
    )


def _step_restore_dry_run(
    backup_dir: str,
    target_path: str,
) -> None:
    """[9] restore --dry-run -> integrity_check=ok + target 미생성."""
    print("\n[9] restore --dry-run", flush=True)
    import restore_sqlite_from_local as rm

    if os.path.exists(target_path):
        os.remove(target_path)

    try:
        result = rm.run_restore(
            kind="daily",
            stamp=None,
            target_path=target_path,
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=True,
            force=True,
        )
    except SystemExit as exc:
        _record("dry-run 정상 종료", False, f"SystemExit: {exc.code}")
        return
    except Exception as exc:
        _record("dry-run 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    _record(
        "dry-run integrity=ok + target 미생성",
        result.get("integrity_check") == "ok" and not os.path.exists(target_path),
        f"integrity={result.get('integrity_check')} "
        f"target_exists={os.path.exists(target_path)}",
    )


def _step_restore_real(
    backup_dir: str,
    target_path: str,
    db_path: str,
) -> None:
    """[10/11] restore 실 설치 + cycle 무손실."""
    print("\n[10] restore 실 설치", flush=True)
    import restore_sqlite_from_local as rm

    if os.path.exists(target_path):
        os.remove(target_path)

    try:
        result = rm.run_restore(
            kind="daily",
            stamp=None,
            target_path=target_path,
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=False,
            force=True,
        )
    except SystemExit as exc:
        _record("실 복원 정상 종료", False, f"SystemExit: {exc.code}")
        return
    except Exception as exc:
        _record("실 복원 실행", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return

    _record(
        "복원 status=ok + target 생성",
        result.get("status") == "ok" and os.path.exists(target_path),
        f"status={result.get('status')} exists={os.path.exists(target_path)}",
    )

    print("\n[11] 복원 DB cycle 무손실 (schema_version + portfolio TEST)", flush=True)
    if not os.path.exists(target_path):
        _record("복원 DB 조회", False, "target 미생성")
        return
    try:
        conn = sqlite3.connect(target_path)
        try:
            schema_rows = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchall()
            portfolio_rows = conn.execute(
                "SELECT ticker, qty, avg_price FROM portfolio WHERE ticker='TEST'"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        _record("복원 DB 조회", False, f"{type(exc).__name__}: {exc}")
        return

    schema_ok = bool(schema_rows) and schema_rows[0][0] == 1
    pf_ok = (
        bool(portfolio_rows)
        and portfolio_rows[0][0] == "TEST"
        and portfolio_rows[0][1] == 10
        and abs(portfolio_rows[0][2] - 1234.5) < 1e-6
    )
    _record(
        "schema_version=1 + portfolio TEST row 동일",
        schema_ok and pf_ok,
        f"schema={schema_rows} portfolio={portfolio_rows}",
    )


def _step_preflight_missing_db() -> None:
    """[12] DB 미존재 -> status=preflight_failed."""
    print("\n[12] DB 미존재 사전 점검", flush=True)
    import backup_sqlite_local as bm

    workspace = tempfile.mkdtemp(prefix="autostock_smoke_preflight_")
    backup_dir = os.path.join(workspace, "backup_local")
    fake_db = os.path.join(workspace, "missing.db")
    try:
        result = bm.run_backup_cycle(
            kind="daily",
            db_path=fake_db,
            backup_dir=backup_dir,
            notify_fn=None,
            dry_run=False,
        )
    except Exception as exc:
        _record("preflight 실행", False, f"{type(exc).__name__}: {exc}")
        shutil.rmtree(workspace, ignore_errors=True)
        return

    _record(
        "DB 미존재 -> status=preflight_failed",
        result.get("status") == "preflight_failed",
        f"status={result.get('status')}",
    )
    shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    started = time.monotonic()
    print("=" * 64, flush=True)
    print("Phase 4 SCP/Local 백업/복원 smoke (12 항목)", flush=True)
    print("=" * 64, flush=True)

    workspace = tempfile.mkdtemp(prefix="autostock_smoke_local_")
    db_path = os.path.join(workspace, "sqlite", "autostock.db")
    backup_dir = os.path.join(workspace, "backup_local")
    target_path = os.path.join(workspace, "restore_target.db")

    print(f"  workspace: {workspace}", flush=True)

    try:
        _seed_sqlite_db(db_path)
        _setup_env(workspace, db_path)

        _step_register_disabled()
        _step_register_enabled()
        _step_backup_dry_run(db_path, backup_dir)
        _step_backup_first_run(db_path, backup_dir)
        _step_retention_rotate(backup_dir)
        _step_monthly_promotion(db_path, backup_dir)
        _step_restore_list(backup_dir)
        _step_restore_dry_run(backup_dir, target_path)
        _step_restore_real(backup_dir, target_path, db_path)
        _step_preflight_missing_db()
    except Exception:
        print("[FATAL] smoke 중 예기치 못한 예외:", flush=True)
        traceback.print_exc()
        _FAIL_LIST.append("uncaught exception")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    elapsed = time.monotonic() - started
    print("=" * 64, flush=True)
    summary = (
        f"PASS: {len(_PASS_LIST)} | FAIL: {len(_FAIL_LIST)} | "
        f"elapsed={elapsed:.2f}s"
    )
    print(summary, flush=True)
    if _FAIL_LIST:
        print("FAIL list:", flush=True)
        for label in _FAIL_LIST:
            print(f"  - {label}", flush=True)
        return 1
    print("ALL OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
