"""SQLite -> LightSail 로컬 디렉터리 백업 스케줄러 진입점 (정책 SCP/Local).

봇 부팅 시 ``main.py`` 가 본 모듈의 ``register_backup_jobs(...)`` 를 1회
호출하여 ``schedule`` 라이브러리에 일간/주간/월간 백업 잡을 등록한다.
실제 백업 작업은 ``scripts/backup_sqlite_local.run_backup_cycle`` 가
수행하며, 본 모듈은 trigger 시각마다 daemon thread 를 띄워 비차단으로
호출한다. 운영자 PC 와의 동기화는 별도 SCP/rsync 채널 (본 모듈 책임 외부).

정책 변경 이력 (2026-06-07): 초기 v1.3 의 GitHub Private Repo 정책에서
LightSail 로컬 정책으로 전환됨. 외부 호스팅/PAT 의존 0.
사양: Doc/features/data_persistence/01_data_persistence_requirements.md §1.4

설계 지침 (Doc/features/data_persistence/03_data_persistence_state_logic.md
§13.1 / §13.3 참조):
    - ``BACKUP_ENABLED`` 환경변수 미활성 (기본값 ``false``) 시 schedule 등록 0건 →
      Phase 1~3 회귀 0 보장 (P4R1).
    - 외부 인증 키가 없으므로 필수 키 누락 분기 폐기 (정책 변경). 단, ``BACKUP_*_AT``
      형식 오류 시 schedule 등록 차단 + 슬랙 ERROR 1회 보고.
    - 트리거 시각마다 daemon thread 에서 ``_safe_run_backup`` 실행 →
      schedule 메인 thread 차단 0.
    - 예외는 thread 안에서 슬랙 1회 보고 후 흡수 (B-Type Pause 안내).
      thread 가 죽어도 봇 본체 영향 0 (P4E6).
"""
from __future__ import annotations

import os
import threading
import traceback
from typing import Callable, Optional


_VALID_WEEKDAY_SET = {
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
}


def _is_truthy_env(value: Optional[str]) -> bool:
    """환경변수 문자열을 boolean 으로 정규화."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_weekly_at(raw: str) -> tuple:
    """``BACKUP_WEEKLY_AT`` 형식 ``"sunday 22:00"`` 파싱.

    Returns:
        (weekday_lower, hhmm) 튜플. 형식 오류 시 ValueError.
    """
    parts = raw.strip().split()
    if len(parts) != 2:
        raise ValueError(f"BACKUP_WEEKLY_AT 형식 오류: {raw!r} (예: 'sunday 22:00')")
    weekday = parts[0].strip().lower()
    hhmm = parts[1].strip()
    if weekday not in _VALID_WEEKDAY_SET:
        raise ValueError(f"BACKUP_WEEKLY_AT 요일 오류: {weekday!r}")
    return weekday, hhmm


def _split_monthly_at(raw: str) -> tuple:
    """``BACKUP_MONTHLY_AT`` 형식 ``"01 00:30"`` 파싱.

    Returns:
        (day_int, hhmm) 튜플. 형식 오류 시 ValueError.
    """
    parts = raw.strip().split()
    if len(parts) != 2:
        raise ValueError(f"BACKUP_MONTHLY_AT 형식 오류: {raw!r} (예: '01 00:30')")
    try:
        day_int = int(parts[0])
    except ValueError as exc:
        raise ValueError(f"BACKUP_MONTHLY_AT 일자 오류: {parts[0]!r}") from exc
    if not (1 <= day_int <= 28):
        raise ValueError(
            f"BACKUP_MONTHLY_AT 일자는 1~28 범위만 허용 (현재: {day_int}). "
            "월말 차이로 인한 누락 방지를 위함."
        )
    return day_int, parts[1].strip()


def _safe_run_backup(kind: str, notify_fn: Optional[Callable[[str], None]]) -> None:
    """예외 안전 래퍼. 모든 예외를 슬랙 1회 보고 후 흡수한다.

    thread 가 죽어도 봇 본체에는 영향이 없으며 (`daemon=True`),
    다음 schedule tick 에 자동 재시도된다.
    """
    try:
        from scripts.backup_sqlite_local import run_backup_cycle

        db_path = os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db")
        backup_dir = os.getenv("BACKUP_LOCAL_DIR", "data/backup_local")
        run_backup_cycle(
            kind=kind,
            db_path=db_path,
            backup_dir=backup_dir,
            notify_fn=notify_fn,
            dry_run=False,
        )
    except Exception as exc:
        message = (
            f"[Backup FAIL] kind={kind} | uncaught | err={type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc(limit=20)}\n"
            "운영자 조치: 로그 확인 후 .env / 디스크 여유 점검. "
            "다음 schedule tick 에 자동 재시도됩니다."
        )
        if callable(notify_fn):
            try:
                notify_fn(message)
            except Exception:
                pass
        print(message, flush=True)


def _run_in_thread(kind: str, notify_fn: Optional[Callable[[str], None]]) -> None:
    """schedule 메인 thread 를 차단하지 않도록 daemon thread 로 위임."""
    threading.Thread(
        target=_safe_run_backup,
        args=(kind, notify_fn),
        daemon=True,
        name=f"backup-{kind}",
    ).start()


def _run_in_thread_if_first_of_month(
    target_day: int,
    notify_fn: Optional[Callable[[str], None]],
) -> None:
    """매월 ``target_day`` 일에만 월간 백업을 트리거한다.

    schedule 라이브러리는 일자별 트리거를 직접 지원하지 않으므로,
    매일 등록된 잡 안에서 KST 기준 day-of-month 비교로 게이트한다.
    """
    try:
        from datetime import datetime
        from src.utils.timekit import KST

        today_day = datetime.now(KST).day
    except Exception:
        from datetime import datetime, timezone, timedelta

        kst = timezone(timedelta(hours=9))
        today_day = datetime.now(kst).day

    if today_day != target_day:
        return
    _run_in_thread("monthly", notify_fn)


def register_backup_jobs(
    scheduler,
    *,
    notify_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """봇 부팅 시 1회 호출. ``BACKUP_ENABLED=true`` 일 때만 schedule jobs 등록.

    Args:
        scheduler: ``schedule`` 모듈 (또는 ``schedule.Scheduler`` 인스턴스).
            ``main.py`` 가 ``import schedule`` 후 본 모듈로 그대로 전달.
        notify_fn: 슬랙 보고용 callable(text). None 이면 stdout 만.

    Returns:
        True: 백업 jobs 등록됨. False: 비활성 또는 필수 키 누락으로 skip.

    부수 효과:
        성공 시 ``schedule`` 에 다음 3 jobs 등록:
            - ``every().day.at(BACKUP_DAILY_AT)`` -> daily 백업
            - ``every().<weekday>.at(BACKUP_WEEKLY_AT)`` -> weekly 백업
            - ``every().day.at(BACKUP_MONTHLY_AT)`` -> day-of-month 게이트 후 monthly 백업
        부팅 stdout 1줄 보고 (M6 C05 와 유사한 양식).
    """
    if not _is_truthy_env(os.getenv("BACKUP_ENABLED")):
        print("[BACKUP] disabled (BACKUP_ENABLED=false)", flush=True)
        return False

    daily_at = os.getenv("BACKUP_DAILY_AT", "18:00").strip()
    weekly_raw = os.getenv("BACKUP_WEEKLY_AT", "sunday 22:00")
    monthly_raw = os.getenv("BACKUP_MONTHLY_AT", "01 00:30")

    try:
        weekly_day, weekly_at = _split_weekly_at(weekly_raw)
        monthly_day, monthly_at = _split_monthly_at(monthly_raw)
    except ValueError as exc:
        message = (
            f"[Backup FAIL] register_backup_jobs SKIP — 환경변수 파싱 오류: {exc}. "
            "운영자 조치: .env 의 BACKUP_*_AT 값 형식 점검."
        )
        print(message, flush=True)
        if callable(notify_fn):
            try:
                notify_fn(message)
            except Exception:
                pass
        return False

    try:
        scheduler.every().day.at(daily_at).do(
            _run_in_thread, kind="daily", notify_fn=notify_fn,
        )
        getattr(scheduler.every(), weekly_day).at(weekly_at).do(
            _run_in_thread, kind="weekly", notify_fn=notify_fn,
        )
        scheduler.every().day.at(monthly_at).do(
            _run_in_thread_if_first_of_month,
            target_day=monthly_day,
            notify_fn=notify_fn,
        )
    except Exception as exc:
        message = (
            f"[Backup FAIL] register_backup_jobs SKIP — schedule 등록 실패: "
            f"{type(exc).__name__}: {exc}"
        )
        print(message, flush=True)
        if callable(notify_fn):
            try:
                notify_fn(message)
            except Exception:
                pass
        return False

    boot_message = (
        f"[BACKUP] backup jobs registered: "
        f"daily={daily_at}, weekly={weekly_day} {weekly_at}, "
        f"monthly=day{monthly_day:02d} {monthly_at}"
    )
    print(boot_message, flush=True)
    return True


__all__ = ["register_backup_jobs"]
