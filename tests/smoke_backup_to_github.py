"""Phase 4 백업 / 복원 smoke 테스트.

외부 GitHub 의존성을 회피하기 위해 **로컬 베어 저장소**(``file:///tmp/...``)를
원격으로 사용한다. 실제 운영 흐름과 동일하게:
    - ``backup`` orphan 브랜치 자동 생성 / single-branch clone.
    - ``run_backup_cycle`` 의 10단계 (VACUUM INTO + gzip + commit + push + 회전).
    - ``run_restore`` 의 8단계 (fetch + gunzip + integrity_check + atomic rename).
    - ``BACKUP_ENABLED=false`` / ``true`` 분기.
    - ``register_backup_jobs`` 의 schedule 등록 카운트.
    - 보관 정책 회전 (mock 으로 31일 전 stamp 1개 + 30일 이내 5개).

상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §13.9.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from typing import List


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


_PASS_LIST: List[str] = []
_FAIL_LIST: List[str] = []


def _print(msg: str) -> None:
    print(msg, flush=True)


def _record(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        _PASS_LIST.append(label)
        _print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _FAIL_LIST.append(label)
        _print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def _run_git(args: list, *, cwd: str, check: bool = True):
    """smoke 자체 git 호출. ``GIT_CEILING_DIRECTORIES`` 가드 (상위 .git 차단)."""
    parent_of_cwd = os.path.dirname(os.path.abspath(cwd))
    env_map = dict(os.environ)
    env_map.setdefault("GIT_CEILING_DIRECTORIES", parent_of_cwd)
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        env=env_map,
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _ensure_local_bare_remote(bare_path: str) -> str:
    """로컬 베어 저장소를 신설하고 file:// URL 반환."""
    if os.path.exists(bare_path):
        shutil.rmtree(bare_path)
    os.makedirs(bare_path, exist_ok=True)
    _run_git(["init", "--bare", "--initial-branch", "backup"], cwd=bare_path, check=False)
    return f"file://{bare_path}"


def _seed_sqlite_db(db_path: str) -> None:
    """smoke 용 미니 SQLite DB 생성 (schema_version + portfolio 1 row)."""
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE schema_version("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
        )
        conn.execute(
            "INSERT INTO schema_version VALUES (1, '2026-06-07T00:00:00', 'smoke seed')"
        )
        conn.execute(
            "CREATE TABLE portfolio("
            "ticker TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO portfolio VALUES ('TEST', '{\"qty\": 100}', '2026-06-07T00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()


def _setup_env(workspace: str) -> dict:
    """smoke 전용 환경변수 셋업. 작업 디렉터리 별도 격리."""
    env_map = {
        "BACKUP_REPO_DIR": os.path.join(workspace, "backup_repo"),
        "STATE_STORE_DB_PATH": os.path.join(workspace, "live.db"),
        "BACKUP_BRANCH": "backup",
        "BACKUP_GITHUB_TOKEN": "fake-token-not-used-by-file-remote",
        "BACKUP_GIT_USER_NAME": "smoke-bot",
        "BACKUP_GIT_USER_EMAIL": "smoke@example.com",
        "BACKUP_DAILY_AT": "18:00",
        "BACKUP_WEEKLY_AT": "sunday 22:00",
        "BACKUP_MONTHLY_AT": "01 00:30",
        "BACKUP_RETENTION_DAILY": "30",
        "BACKUP_RETENTION_WEEKLY": "12",
        "BACKUP_RETENTION_MONTHLY": "12",
    }
    return env_map


# ----- schedule stub (로컬 PC 에 schedule 라이브러리 미설치 상황 대응) -----
class _StubSchedulerJob:
    def __init__(self):
        self._weekday: str = ""
        self._at: str = ""
        self._cb = None
        self._kwargs: dict = {}

    @property
    def day(self):
        self._weekday = "day"
        return self

    def __getattr__(self, name):
        if name in {
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        }:
            self._weekday = name
            return self
        raise AttributeError(name)

    def at(self, hhmm):
        self._at = hhmm
        return self

    def do(self, callable_, **kwargs):
        self._cb = callable_
        self._kwargs = kwargs
        return self


class _StubScheduler:
    def __init__(self):
        self.jobs: List[_StubSchedulerJob] = []

    def every(self):
        job = _StubSchedulerJob()
        self.jobs.append(job)
        return job

    def clear(self):
        self.jobs = []


# ----- 단계 1: register_backup_jobs (BACKUP_ENABLED 분기) -----
def _step_register_disabled() -> None:
    _print("\n[1/8] register_backup_jobs - BACKUP_ENABLED=false")
    os.environ.pop("BACKUP_ENABLED", None)
    stub = _StubScheduler()
    sys.modules.pop("src.storage.backup_scheduler", None)
    from src.storage import backup_scheduler

    result = backup_scheduler.register_backup_jobs(stub, notify_fn=None)
    _record(
        "BACKUP_ENABLED 미설정 -> register False + jobs 0건",
        result is False and len(stub.jobs) == 0,
        f"register={result} jobs={len(stub.jobs)}",
    )


def _step_register_enabled() -> None:
    _print("\n[2/8] register_backup_jobs - BACKUP_ENABLED=true + 필수 키 설정")
    os.environ["BACKUP_ENABLED"] = "true"
    os.environ["BACKUP_REPO_URL"] = "file:///tmp/dummy_for_register.git"
    os.environ["BACKUP_GITHUB_TOKEN"] = "fake-token"
    stub = _StubScheduler()
    sys.modules.pop("src.storage.backup_scheduler", None)
    from src.storage import backup_scheduler

    result = backup_scheduler.register_backup_jobs(stub, notify_fn=None)
    weekdays = sorted({job._weekday for job in stub.jobs})
    _record(
        "BACKUP_ENABLED=true -> register True + jobs 3건 등록",
        result is True and len(stub.jobs) == 3,
        f"register={result} jobs={len(stub.jobs)}",
    )
    _record(
        "weekday 매핑: day(2건) + sunday(1건)",
        weekdays == ["day", "sunday"],
        f"weekdays={weekdays}",
    )


# ----- 단계 2: run_backup_cycle dry-run -----
def _step_backup_dry_run(workspace: str, bare_url: str) -> None:
    _print("\n[3/8] run_backup_cycle dry-run")
    env_map = _setup_env(workspace)
    env_map["BACKUP_REPO_URL"] = bare_url
    for key, val in env_map.items():
        os.environ[key] = val
    db_path = env_map["STATE_STORE_DB_PATH"]
    _seed_sqlite_db(db_path)

    sys.modules.pop("backup_sqlite_to_github", None)
    import backup_sqlite_to_github as backup_mod

    repo_dir = env_map["BACKUP_REPO_DIR"]
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)

    try:
        result = backup_mod.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            repo_dir=repo_dir,
            notify_fn=None,
            dry_run=True,
        )
    except SystemExit as exc:
        _record("dry-run exit", False, f"unexpected SystemExit: {exc.code}")
        return

    daily_files = backup_mod._list_kind_files(repo_dir, "daily")
    _record(
        "dry-run 후 .gz 미커밋 (daily/ 비어있음)",
        len(daily_files) == 0,
        f"daily files={daily_files}",
    )
    _record(
        "dry-run result.status=ok + vacuum_db_size>0",
        result.get("status") == "ok" and result.get("vacuum_db_size", 0) > 0,
        f"status={result.get('status')} vacuum={result.get('vacuum_db_size')}",
    )


# ----- 단계 3: run_backup_cycle 실 실행 (orphan 브랜치 신설) -----
def _step_backup_first_run(workspace: str, bare_url: str) -> None:
    _print("\n[4/8] run_backup_cycle 실 실행 (orphan 브랜치 자동 신설)")
    env_map = _setup_env(workspace)
    env_map["BACKUP_REPO_URL"] = bare_url
    for key, val in env_map.items():
        os.environ[key] = val
    db_path = env_map["STATE_STORE_DB_PATH"]
    repo_dir = env_map["BACKUP_REPO_DIR"]

    sys.modules.pop("backup_sqlite_to_github", None)
    import backup_sqlite_to_github as backup_mod

    try:
        result = backup_mod.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            repo_dir=repo_dir,
            notify_fn=None,
            dry_run=False,
        )
    except SystemExit as exc:
        _record("실 실행 exit", False, f"unexpected SystemExit: {exc.code}")
        return

    _record(
        "실 실행 result.status=ok",
        result.get("status") == "ok",
        f"status={result.get('status')}",
    )
    _record(
        "result.commit_sha 존재 (7자 이상)",
        len(result.get("commit_sha", "")) >= 7,
        f"sha={result.get('commit_sha')}",
    )
    daily_files = backup_mod._list_kind_files(repo_dir, "daily")
    _record(
        "daily/ 에 .db.gz 1건 생성",
        len(daily_files) == 1 and daily_files[0].startswith("autostock-"),
        f"daily files={daily_files}",
    )
    _record(
        "result.gz_size 와 실제 파일 크기 일치",
        len(daily_files) == 1
        and result.get("gz_size") == os.path.getsize(os.path.join(repo_dir, "daily", daily_files[0])),
        f"size={result.get('gz_size')}",
    )


# ----- 단계 4: 보관 정책 회전 알고리즘 -----
def _step_retention_rotate(workspace: str, bare_url: str) -> None:
    _print("\n[5/8] 보관 정책 회전 (mock 31일 전 1개 + 30일 이내 4개)")
    env_map = _setup_env(workspace)
    env_map["BACKUP_REPO_URL"] = bare_url
    env_map["BACKUP_RETENTION_DAILY"] = "30"
    for key, val in env_map.items():
        os.environ[key] = val
    db_path = env_map["STATE_STORE_DB_PATH"]
    repo_dir = env_map["BACKUP_REPO_DIR"]

    sys.modules.pop("backup_sqlite_to_github", None)
    import backup_sqlite_to_github as backup_mod

    daily_dir = os.path.join(repo_dir, "daily")
    os.makedirs(daily_dir, exist_ok=True)
    now_kst = backup_mod._kst_now()
    expired_dt = now_kst - timedelta(days=31)
    fresh_dts = [now_kst - timedelta(days=delta) for delta in (5, 10, 15, 20)]
    seed_dt_list = [expired_dt] + fresh_dts
    expected_expired_filename = (
        f"autostock-{expired_dt.strftime('%Y%m%d-%H%M')}.db.gz"
    )
    for dt in seed_dt_list:
        filename = f"autostock-{dt.strftime('%Y%m%d-%H%M')}.db.gz"
        target = os.path.join(daily_dir, filename)
        with gzip.open(target, "wb") as fh:
            fh.write(b"smoke seed")
    _run_git(["add", "daily/"], cwd=repo_dir, check=False)
    _run_git(
        ["commit", "-m", "smoke: seed retention test files"],
        cwd=repo_dir,
        check=False,
    )
    _run_git(
        ["push", "origin", env_map["BACKUP_BRANCH"]],
        cwd=repo_dir,
        check=False,
    )

    try:
        result = backup_mod.run_backup_cycle(
            kind="daily",
            db_path=db_path,
            repo_dir=repo_dir,
            notify_fn=None,
            dry_run=False,
        )
    except SystemExit as exc:
        _record("retention 실행 exit", False, f"unexpected SystemExit: {exc.code}")
        return

    rotated_list = result.get("rotated_files_list", [])
    _record(
        "31일 전 stamp 1개 회전 + 30일 이내 보존",
        len(rotated_list) == 1 and any(expected_expired_filename in r for r in rotated_list),
        f"rotated={rotated_list}",
    )
    remaining_files = backup_mod._list_kind_files(repo_dir, "daily")
    _record(
        "회전 후 daily/ 에 신규 1개 + 기존 fresh 4개 = 5개 잔존",
        len(remaining_files) == 5,
        f"remaining={len(remaining_files)}",
    )


# ----- 단계 5: run_restore --list -----
def _step_restore_list(workspace: str, bare_url: str) -> None:
    _print("\n[6/8] run_restore --list")
    env_map = _setup_env(workspace)
    env_map["BACKUP_REPO_URL"] = bare_url
    for key, val in env_map.items():
        os.environ[key] = val

    sys.modules.pop("restore_sqlite_from_github", None)
    import restore_sqlite_from_github as restore_mod

    repo_dir = env_map["BACKUP_REPO_DIR"]
    meta_map = restore_mod._list_all_backups(repo_dir)
    daily_count = len(meta_map.get("daily", []))
    _record(
        "_list_all_backups 가 daily 5건 보고",
        daily_count == 5,
        f"daily count={daily_count}",
    )


# ----- 단계 6: run_restore --dry-run -----
def _step_restore_dry_run(workspace: str, bare_url: str) -> None:
    _print("\n[7/8] run_restore dry-run")
    env_map = _setup_env(workspace)
    env_map["BACKUP_REPO_URL"] = bare_url
    for key, val in env_map.items():
        os.environ[key] = val
    repo_dir = env_map["BACKUP_REPO_DIR"]
    target_path = os.path.join(workspace, "restore_target.db")
    if os.path.exists(target_path):
        os.remove(target_path)

    sys.modules.pop("restore_sqlite_from_github", None)
    import restore_sqlite_from_github as restore_mod

    try:
        result = restore_mod.run_restore(
            kind="daily",
            stamp=None,
            target_path=target_path,
            repo_dir=repo_dir,
            notify_fn=None,
            dry_run=True,
            force=True,
        )
    except SystemExit as exc:
        _record("dry-run restore exit", False, f"unexpected SystemExit: {exc.code}")
        return
    _record(
        "dry-run integrity=ok + target 변경 없음",
        result.get("integrity_check") == "ok" and not os.path.exists(target_path),
        f"integrity={result.get('integrity_check')} target_exists={os.path.exists(target_path)}",
    )


# ----- 단계 7: run_restore 실 실행 + integrity 검증 -----
def _step_restore_real(workspace: str, bare_url: str) -> None:
    _print("\n[8/8] run_restore 실 실행 (atomic install) + integrity_check")
    env_map = _setup_env(workspace)
    env_map["BACKUP_REPO_URL"] = bare_url
    for key, val in env_map.items():
        os.environ[key] = val
    repo_dir = env_map["BACKUP_REPO_DIR"]
    target_path = os.path.join(workspace, "restore_target.db")

    sys.modules.pop("restore_sqlite_from_github", None)
    import restore_sqlite_from_github as restore_mod

    try:
        result = restore_mod.run_restore(
            kind="daily",
            stamp=None,
            target_path=target_path,
            repo_dir=repo_dir,
            notify_fn=None,
            dry_run=False,
            force=True,
        )
    except SystemExit as exc:
        _record("실 복원 exit", False, f"unexpected SystemExit: {exc.code}")
        return
    _record(
        "복원 완료 status=ok + target 파일 존재",
        result.get("status") == "ok" and os.path.exists(target_path),
        f"status={result.get('status')} target={os.path.exists(target_path)}",
    )
    try:
        conn = sqlite3.connect(target_path)
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        ticker_rows = conn.execute("SELECT ticker FROM portfolio").fetchall()
        conn.close()
    except Exception as exc:
        _record("복원 DB 조회", False, f"exc={exc}")
        return
    _record(
        "복원된 DB 의 schema_version row + portfolio TEST 동일",
        rows == [(1,)] and ticker_rows == [("TEST",)],
        f"schema_version={rows} portfolio={ticker_rows}",
    )


def main() -> int:
    started = time.monotonic()
    _print("=" * 60)
    _print("Phase 4 백업/복원 smoke 테스트")
    _print("=" * 60)

    smoke_root = os.path.join(_PROJECT_ROOT, "data", ".smoke_workspace")
    os.makedirs(smoke_root, exist_ok=True)
    workspace = tempfile.mkdtemp(prefix="autostock_p4smoke_", dir=smoke_root)
    bare_path = os.path.join(workspace, "remote.git")
    bare_url = _ensure_local_bare_remote(bare_path)
    _print(f"  workspace: {workspace}")
    _print(f"  bare remote: {bare_url}")

    try:
        _step_register_disabled()
        _step_register_enabled()
        _step_backup_dry_run(workspace, bare_url)
        _step_backup_first_run(workspace, bare_url)
        _step_retention_rotate(workspace, bare_url)
        _step_restore_list(workspace, bare_url)
        _step_restore_dry_run(workspace, bare_url)
        _step_restore_real(workspace, bare_url)
    except Exception:
        _print("[FATAL] uncaught exception:")
        traceback.print_exc()
        return 2
    finally:
        try:
            shutil.rmtree(workspace, ignore_errors=True)
        except Exception:
            pass

    elapsed = time.monotonic() - started
    _print("=" * 60)
    _print(f"PASS: {len(_PASS_LIST)} | FAIL: {len(_FAIL_LIST)} | elapsed={elapsed:.2f}s")
    if _FAIL_LIST:
        _print("FAIL list:")
        for label in _FAIL_LIST:
            _print(f"  - {label}")
        return 1
    _print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
