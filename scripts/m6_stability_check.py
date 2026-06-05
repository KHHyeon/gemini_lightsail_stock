# -*- coding: utf-8 -*-
"""M6 운영 안정성 자동 점검 도구.

SQLite 백엔드(Phase 2) 활성화 직후 1~3일간 봇이 정상 동작하는지
별도 agent 가 1일 1회 ssh 로 호출하여 자동 점검한다.

상세 사양: Doc/features/data_persistence/03_data_persistence_state_logic.md §11

사용 예:
    python3 scripts/m6_stability_check.py                 # 사람용 텍스트 출력
    python3 scripts/m6_stability_check.py --json          # agent 파싱용 JSON
    python3 scripts/m6_stability_check.py --slack         # 슬랙 1회 보고
    python3 scripts/m6_stability_check.py --day 1         # Day 1 점검만
    python3 scripts/m6_stability_check.py --day 3 --json  # Day 3 점검 JSON

종료 코드:
    0 - PASS (FAIL/WARN 0건)
    1 - WARN (FAIL 0건, WARN 1+건)
    2 - FAIL (FAIL 1+건. 롤백 트리거 후보)
    3 - 점검 도구 자체의 치명적 실행 실패
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple


# scripts/_common.py 경로 활성화.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=False)


# ---------------------------------------------------------------------------
# 상수 / 데이터 구조
# ---------------------------------------------------------------------------
_STATUS_PASS = "PASS"
_STATUS_WARN = "WARN"
_STATUS_FAIL = "FAIL"
_STATUS_SKIP = "SKIP"

_EXIT_PASS = 0
_EXIT_WARN = 1
_EXIT_FAIL = 2
_EXIT_TOOL_ERROR = 3

# 운영 도메인 (SQLite 활성화 후 Drive 폴백이 일어나면 안 되는 도메인).
# C07 점검에서 [Drive Read Fallback] 메시지에 본 도메인이 등장하면 회귀로 본다.
_OPERATIONAL_FILENAME_LIST = [
    "paper_portfolio.json",
    "paper_trades.json",
    "split_orders.json",
    "theme_context.json",
    "scalp_session.json",
]


@dataclass
class CheckResult:
    """단일 점검 결과."""

    check_id: str
    category: str
    day_scope: List[int]
    label: str
    status: str
    detail: str = ""
    elapsed_ms: int = 0


@dataclass
class RunContext:
    """점검 전반에 걸쳐 공유되는 환경 컨텍스트."""

    db_path: str
    wal_path: str
    service_name: str
    day_filter: Optional[int]
    now_utc: datetime
    sqlite_activation_ts: Optional[datetime] = field(default=None)
    sqlite_cutover_ts: Optional[datetime] = field(default=None)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _run_shell(cmd_list: List[str], timeout_sec: int = 10) -> Tuple[int, str, str]:
    """서브프로세스 실행. (returncode, stdout, stderr) 반환. 실패 시 returncode=-1."""
    try:
        proc = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError as exc:
        return -1, "", f"command not found: {exc}"
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout {timeout_sec}s: {' '.join(cmd_list)}"
    except Exception as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def _parse_iso_to_utc(s: Optional[str]) -> Optional[datetime]:
    """다양한 ISO 형식을 UTC datetime 으로. 실패 시 None."""
    if not s or not isinstance(s, str):
        return None
    cleaned = s.strip()
    if not cleaned:
        return None
    # Drop trailing 'Z' (Python 3.10 fromisoformat 미지원).
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        # 일부 trades.ts 는 "YYYY-MM-DD HH:MM:SS" (TZ 없음). KST 가정 후 UTC 변환.
        try:
            dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
            kst = timezone(timedelta(hours=9))
            dt = dt.replace(tzinfo=kst)
        except ValueError:
            return None
    if dt.tzinfo is None:
        # naive 면 UTC 로 가정.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hours_since(dt: Optional[datetime], now: datetime) -> Optional[float]:
    if dt is None:
        return None
    delta = now - dt
    return delta.total_seconds() / 3600.0


def _open_db(db_path: str) -> sqlite3.Connection:
    """read-only 연결. WAL 모드 호환을 위해 일반 connection 으로 열되, write 는 하지 않는다."""
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _is_trading_day(now: datetime) -> bool:
    """간단 거래일 판정 — market_calendar 모듈을 best-effort 로 사용. 실패 시 weekday() 기반 fallback."""
    try:
        from src.utils import market_calendar

        return bool(market_calendar.is_trading_day(now))
    except Exception:
        # KST 변환 후 평일이면 잠정 거래일.
        kst = now.astimezone(timezone(timedelta(hours=9)))
        return kst.weekday() < 5


# ---------------------------------------------------------------------------
# 점검 함수 (사양 §11.3 매트릭스 1:1 대응)
# ---------------------------------------------------------------------------
def _c01_service_active(ctx: RunContext) -> Tuple[str, str]:
    rc, out, err = _run_shell(["systemctl", "is-active", ctx.service_name])
    state = (out or err).strip().splitlines()[0] if (out or err) else "(no output)"
    if rc == 0 and state == "active":
        return _STATUS_PASS, f"{ctx.service_name} = {state}"
    return _STATUS_FAIL, f"{ctx.service_name} = {state} (rc={rc})"


def _c02_main_pid_alive(ctx: RunContext) -> Tuple[str, str]:
    rc, out, _err = _run_shell(["systemctl", "show", "-p", "MainPID", "--value", ctx.service_name])
    pid_str = (out or "").strip()
    if rc != 0 or not pid_str.isdigit():
        return _STATUS_FAIL, f"MainPID 조회 실패 (rc={rc}, out='{pid_str}')"
    pid = int(pid_str)
    if pid <= 0:
        return _STATUS_FAIL, f"MainPID={pid} (서비스 미가동)"
    if not os.path.isdir(f"/proc/{pid}"):
        return _STATUS_FAIL, f"MainPID={pid} 이지만 /proc/{pid} 없음"
    return _STATUS_PASS, f"MainPID={pid} alive"


def _c03_db_file_present(ctx: RunContext) -> Tuple[str, str]:
    if not os.path.exists(ctx.db_path):
        return _STATUS_FAIL, f"DB 파일 없음: {ctx.db_path}"
    size = os.path.getsize(ctx.db_path)
    if size <= 0:
        return _STATUS_FAIL, f"DB 파일 크기 0: {ctx.db_path}"
    return _STATUS_PASS, f"{ctx.db_path} size={size:,} bytes"


def _c04_wal_file_present(ctx: RunContext) -> Tuple[str, str]:
    if not os.path.exists(ctx.wal_path):
        return _STATUS_FAIL, f"WAL 파일 없음: {ctx.wal_path} (WAL 모드 미동작 의심)"
    size = os.path.getsize(ctx.wal_path)
    return _STATUS_PASS, f"{ctx.wal_path} size={size:,} bytes"


def _c05_boot_log_backend(ctx: RunContext) -> Tuple[str, str]:
    """journalctl 에서 [STATE_STORE] backend=sqlite 부팅 로그 매칭.

    사이클 1 (즉시) 검증용. 최근 10분 범위 우선, 못 찾으면 1시간으로 확장.
    """
    for since in ("10 min ago", "1 hour ago", "today"):
        rc, out, _err = _run_shell(
            ["journalctl", "-u", ctx.service_name, "--since", since, "--no-pager"],
            timeout_sec=15,
        )
        if rc != 0:
            continue
        for line in out.splitlines():
            if "[STATE_STORE]" in line and "backend=sqlite" in line:
                return _STATUS_PASS, f"매칭: {line.strip()[-180:]}"
        if "[STATE_STORE] backend=drive" in out:
            return _STATUS_FAIL, "backend=drive 로 폴백된 부팅 로그 발견 (SQLite 활성화 실패 의심)"
    return _STATUS_WARN, "journalctl 에서 backend 부팅 로그를 찾지 못함 (서비스 미재시작 또는 권한 부족)"


def _c06_runtime_error_absent(ctx: RunContext) -> Tuple[str, str]:
    rc, out, _err = _run_shell(
        ["journalctl", "-u", ctx.service_name, "--since", "1 hour ago", "--no-pager"],
        timeout_sec=15,
    )
    if rc != 0:
        return _STATUS_WARN, f"journalctl 호출 실패 (rc={rc})"
    pattern = re.compile(r"(sqlite3\.OperationalError|STATE_STORE.*ERROR)", re.IGNORECASE)
    hits = [ln for ln in out.splitlines() if pattern.search(ln)]
    if not hits:
        return _STATUS_PASS, "최근 1시간 매칭 0건"
    sample = hits[-1].strip()[-200:]
    return _STATUS_FAIL, f"매칭 {len(hits)}건 (마지막: {sample})"


def _c07_drive_fallback_scope(ctx: RunContext) -> Tuple[str, str]:
    """[Drive Read Fallback] 메시지가 떠도 Chronicle 만 — 운영 도메인이 등장하면 회귀."""
    rc, out, _err = _run_shell(
        ["journalctl", "-u", ctx.service_name, "--since", "24 hour ago", "--no-pager"],
        timeout_sec=15,
    )
    if rc != 0:
        return _STATUS_WARN, f"journalctl 호출 실패 (rc={rc})"
    fallback_lines = [ln for ln in out.splitlines() if "Drive Read Fallback" in ln]
    if not fallback_lines:
        return _STATUS_PASS, "최근 24h Drive Read Fallback 0건"
    leaked = []
    for ln in fallback_lines:
        for fname in _OPERATIONAL_FILENAME_LIST:
            if fname in ln:
                leaked.append((fname, ln.strip()[-160:]))
                break
    if leaked:
        sample_msg = leaked[-1][1]
        return (
            _STATUS_FAIL,
            f"운영 도메인 폴백 누출 {len(leaked)}건 / 전체 {len(fallback_lines)}건. 예: {sample_msg}",
        )
    return _STATUS_PASS, f"Fallback {len(fallback_lines)}건 (모두 Chronicle 범위)"


def _c08_orchestrator_cycle(ctx: RunContext) -> Tuple[str, str]:
    """봇의 정기 사이클 활동 로그 매칭.

    sparse 동작(시간 단위로만 로그 출력)을 수용하기 위해 4시간 윈도우.
    실제 로그 키워드(`[Screener]`, `[News Crawler]`) 도 포함.
    상세: Doc/features/data_persistence/03_*.md §11.8.4 S1.
    """
    rc, out, _err = _run_shell(
        ["journalctl", "-u", ctx.service_name, "--since", "4 hour ago", "--no-pager"],
        timeout_sec=15,
    )
    if rc != 0:
        return _STATUS_WARN, f"journalctl 호출 실패 (rc={rc})"
    pattern = re.compile(
        r"(Screener|News Crawler|Orchestrator|orchestrator|이상종목|발굴|시간대|정기 사이클|MarketOrchestrator)"
    )
    hits = [ln for ln in out.splitlines() if pattern.search(ln)]
    if not hits:
        return _STATUS_WARN, "최근 4시간 봇 사이클 로그 0건 (장 외 시간 또는 hang 가능성)"
    return _STATUS_PASS, f"매칭 {len(hits)}건 (최근: ...{hits[-1].strip()[-120:]})"


def _c09_market_open_log(ctx: RunContext) -> Tuple[str, str]:
    """09:00 자동 시장 진입 로그 매칭.

    `--since` 는 KST today 의 ISO 형식으로 명시한다 (`today` 자연어는 일부 systemd 가 거부).
    상세: Doc/features/data_persistence/03_*.md §11.8.4 S2.
    """
    if not _is_trading_day(ctx.now_utc):
        return _STATUS_SKIP, "비거래일"
    kst = ctx.now_utc.astimezone(timezone(timedelta(hours=9)))
    # 09:00 이전이면 아직 SKIP (시장 진입 전).
    if kst.hour < 9:
        return _STATUS_SKIP, f"09:00 KST 이전 (현재 {kst.strftime('%H:%M')} KST)"
    since_iso = kst.strftime("%Y-%m-%d 08:55:00")
    rc, out, _err = _run_shell(
        ["journalctl", "-u", ctx.service_name, "--since", since_iso, "--no-pager"],
        timeout_sec=15,
    )
    if rc != 0:
        return _STATUS_WARN, f"journalctl 호출 실패 (rc={rc}, since='{since_iso}')"
    pattern = re.compile(r"(Market.*Open|장 시작|09:00|시장 진입|Screener.*탐색 시작)")
    hits = [ln for ln in out.splitlines() if pattern.search(ln)]
    if hits:
        return _STATUS_PASS, f"매칭 {len(hits)}건 (since={since_iso})"
    return _STATUS_FAIL, f"09:00 자동 시장 진입 로그 누락 (since={since_iso})"


def _query_max_updated_at(conn: sqlite3.Connection, table: str) -> Optional[str]:
    try:
        row = conn.execute(f"SELECT MAX(updated_at) FROM {table}").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _query_row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.Error:
        return -1


def _check_updated_freshness(
    conn: sqlite3.Connection,
    table: str,
    ctx: RunContext,
    allow_empty: bool = True,
    fresh_hours: float = 24.0,
) -> Tuple[str, str]:
    row_count = _query_row_count(conn, table)
    if row_count <= 0:
        if allow_empty:
            return _STATUS_SKIP, f"{table} rows=0 (해당 활동 없음)"
        return _STATUS_FAIL, f"{table} rows=0"
    max_updated = _query_max_updated_at(conn, table)
    parsed = _parse_iso_to_utc(max_updated)
    hours = _hours_since(parsed, ctx.now_utc)
    if hours is None:
        return _STATUS_WARN, f"{table} rows={row_count} but updated_at parse 실패 ({max_updated!r})"
    if not _is_trading_day(ctx.now_utc):
        # 비거래일에는 정체가 정상. 통과.
        return _STATUS_PASS, f"{table} rows={row_count} updated={hours:.1f}h ago (비거래일)"
    if hours <= fresh_hours:
        return _STATUS_PASS, f"{table} rows={row_count} updated={hours:.1f}h ago"
    return _STATUS_WARN, f"{table} rows={row_count} updated={hours:.1f}h ago > {fresh_hours}h"


def _c10_portfolio_freshness(conn: sqlite3.Connection, ctx: RunContext) -> Tuple[str, str]:
    return _check_updated_freshness(conn, "portfolio", ctx, allow_empty=True)


def _c11_split_orders_freshness(conn: sqlite3.Connection, ctx: RunContext) -> Tuple[str, str]:
    return _check_updated_freshness(conn, "split_orders", ctx, allow_empty=True)


def _c12_trades_recent(conn: sqlite3.Connection, ctx: RunContext) -> Tuple[str, str]:
    row_count = _query_row_count(conn, "trades")
    if row_count <= 0:
        return _STATUS_SKIP, "trades rows=0 (거래 발생 없음)"
    try:
        rows = conn.execute("SELECT ts FROM trades ORDER BY id DESC LIMIT 1").fetchall()
    except sqlite3.Error as exc:
        return _STATUS_FAIL, f"trades 조회 실패: {exc}"
    if not rows:
        return _STATUS_SKIP, "trades 최근 row 없음"
    last_ts = rows[0][0]
    parsed = _parse_iso_to_utc(last_ts)
    hours = _hours_since(parsed, ctx.now_utc)
    if hours is None:
        return _STATUS_WARN, f"trades 최근 ts 파싱 실패 ({last_ts!r})"
    if not _is_trading_day(ctx.now_utc):
        return _STATUS_PASS, f"trades rows={row_count} last_ts={hours:.1f}h ago (비거래일)"
    # 거래가 매일 발생한다고 단정할 수 없으므로 fresh 기준을 24h 가 아닌 72h 로 완화.
    if hours <= 72.0:
        return _STATUS_PASS, f"trades rows={row_count} last_ts={hours:.1f}h ago"
    return _STATUS_WARN, f"trades 최근 거래 {hours:.1f}h 전 (72h 초과)"


def _c13_theme_scalp_freshness(conn: sqlite3.Connection, ctx: RunContext) -> Tuple[str, str]:
    """theme_context / scalp_session 합산 점검 (둘 다 갱신될 필요는 없으므로 OR 시맨틱)."""
    details: List[str] = []
    statuses: List[str] = []
    for table in ("theme_context", "scalp_session"):
        st, dt = _check_updated_freshness(conn, table, ctx, allow_empty=True)
        statuses.append(st)
        details.append(f"{table}={st}")
    if _STATUS_FAIL in statuses:
        return _STATUS_FAIL, " / ".join(details)
    if all(s == _STATUS_SKIP for s in statuses):
        return _STATUS_SKIP, " / ".join(details)
    if _STATUS_WARN in statuses:
        return _STATUS_WARN, " / ".join(details)
    return _STATUS_PASS, " / ".join(details)


def _c14_integrity_check(conn: sqlite3.Connection, ctx: RunContext) -> Tuple[str, str]:
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        return _STATUS_FAIL, f"integrity_check 실행 실패: {exc}"
    flat = [r[0] for r in rows]
    if flat == ["ok"]:
        return _STATUS_PASS, "integrity_check = ok"
    return _STATUS_FAIL, f"integrity_check 비정상: {flat}"


def _c15_wal_size_bound(ctx: RunContext) -> Tuple[str, str]:
    if not os.path.exists(ctx.wal_path):
        return _STATUS_WARN, f"WAL 파일 없음 (C04 와 함께 확인): {ctx.wal_path}"
    size = os.path.getsize(ctx.wal_path)
    limit = 10 * 1024 * 1024
    if size < limit:
        return _STATUS_PASS, f"WAL size={size:,} bytes < 10MiB"
    return _STATUS_WARN, f"WAL size={size:,} bytes >= 10MiB (체크포인트 동작 확인 필요)"


def _c16_disk_free(ctx: RunContext) -> Tuple[str, str]:
    try:
        usage = shutil.disk_usage("/")
    except OSError as exc:
        return _STATUS_WARN, f"disk_usage 실패: {exc}"
    free_gib = usage.free / (1024 ** 3)
    if free_gib >= 1.0:
        return _STATUS_PASS, f"/ free={free_gib:.2f} GiB"
    return _STATUS_FAIL, f"/ free={free_gib:.2f} GiB < 1 GiB"


def _drive_modified_time(filename: str, *, rel_path: bool = False) -> Optional[datetime]:
    """Drive modifiedTime 조회. 실패 시 None.

    상세: Doc/features/data_persistence/03_*.md §11.8.4 S3.
    """
    try:
        from src.memory import drive_client
    except Exception:
        return None

    getter_name = "get_relative_file_modified_time" if rel_path else "get_app_file_modified_time"
    getter = getattr(drive_client, getter_name, None)
    if not callable(getter):
        return None
    try:
        iso = getter(filename)
    except Exception:
        return None
    return _parse_iso_to_utc(iso)


def _c17_chronicle_drive_rw(ctx: RunContext) -> Tuple[str, str]:
    mtime = _drive_modified_time("MarketChronicles/index/master_index.json", rel_path=True)
    if mtime is None:
        return _STATUS_WARN, "Drive 메타데이터 조회 API 없음/실패 (수동 확인 필요)"
    hours = _hours_since(mtime, ctx.now_utc)
    if hours is None:
        return _STATUS_WARN, "mtime 파싱 실패"
    if hours <= 24.0:
        return _STATUS_PASS, f"master_index.json mtime {hours:.1f}h ago"
    return _STATUS_WARN, f"master_index.json mtime {hours:.1f}h ago > 24h (Chronicle 갱신 정체)"


def _c18_drive_portfolio_stale(ctx: RunContext) -> Tuple[str, str]:
    return _drive_stale_check("paper_portfolio.json", ctx)


def _c19_drive_trades_stale(ctx: RunContext) -> Tuple[str, str]:
    return _drive_stale_check("paper_trades.json", ctx)


def _drive_stale_check(filename: str, ctx: RunContext) -> Tuple[str, str]:
    mtime = _drive_modified_time(filename)
    if mtime is None:
        return _STATUS_WARN, f"{filename} Drive 메타데이터 조회 실패 (수동 확인 필요)"
    # cutover(실제 sqlite 부팅 전환 시각) 우선. 없으면 schema 기반 활성화 시각으로 폴백.
    cutover = ctx.sqlite_cutover_ts or ctx.sqlite_activation_ts
    if cutover is None:
        return _STATUS_WARN, f"{filename} mtime={mtime.isoformat()} (SQLite 활성화 시각 미상)"
    # cutover 직후 잔여 write 오탐 방지를 위한 유예창 24시간.
    grace_deadline = cutover + timedelta(hours=24)
    if mtime <= cutover:
        return _STATUS_PASS, f"{filename} mtime={mtime.isoformat()} <= cutover 시각 (정상 정체)"
    if mtime <= grace_deadline:
        delta_h = (mtime - cutover).total_seconds() / 3600.0
        return _STATUS_PASS, (
            f"{filename} mtime={mtime.isoformat()} (cutover +{delta_h:.1f}h, 유예창 24h 내)"
        )
    delta_h = (mtime - cutover).total_seconds() / 3600.0
    return _STATUS_FAIL, (
        f"{filename} mtime={mtime.isoformat()} > cutover+24h (cutover +{delta_h:.1f}h 이후 갱신)"
    )


def _c20_oauth_pause_pattern(ctx: RunContext) -> Tuple[str, str]:
    rc, out, _err = _run_shell(
        ["journalctl", "-u", ctx.service_name, "--since", "24 hour ago", "--no-pager"],
        timeout_sec=15,
    )
    if rc != 0:
        return _STATUS_WARN, f"journalctl 호출 실패 (rc={rc})"
    hits = [
        ln
        for ln in out.splitlines()
        if "invalid_grant" in ln or "OAuth" in ln or "Pause" in ln
    ]
    if not hits:
        return _STATUS_WARN, "OAuth 만료 시나리오 자동 검증 불가 (이벤트 없음 → 수동 확인)"
    return _STATUS_WARN, f"OAuth/Pause 관련 로그 {len(hits)}건 감지 (수동 확인 권장)"


# ---------------------------------------------------------------------------
# 점검 매트릭스 (사양 §11.3 그대로)
# 각 항목: (id, category, day_scope, label, runner_kind, runner)
#   runner_kind: 'ctx' | 'conn' (DB 연결 필요)
# ---------------------------------------------------------------------------
_CHECK_LIST: List[Tuple[str, str, List[int], str, str, Callable]] = [
    ("C01", "boot", [1, 2, 3], "서비스 active", "ctx", _c01_service_active),
    ("C02", "boot", [1, 2, 3], "메인 PID 살아있음", "ctx", _c02_main_pid_alive),
    ("C03", "boot", [1, 2, 3], "DB 파일 존재 + 크기>0", "ctx", _c03_db_file_present),
    ("C04", "boot", [1, 2, 3], "WAL 파일 존재", "ctx", _c04_wal_file_present),
    ("C05", "boot", [1], "부팅 로그 backend=sqlite", "ctx", _c05_boot_log_backend),
    ("C06", "runtime", [1, 2, 3], "OperationalError/STATE_STORE 에러 0건", "ctx", _c06_runtime_error_absent),
    ("C07", "runtime", [1, 2, 3], "Drive Read Fallback 범위 (Chronicle 한정)", "ctx", _c07_drive_fallback_scope),
    ("C08", "runtime", [1, 2, 3], "오케스트레이터 사이클", "ctx", _c08_orchestrator_cycle),
    ("C09", "trading", [2, 3], "09:00 자동 시장 진입 로그", "ctx", _c09_market_open_log),
    ("C10", "trading", [2, 3], "portfolio 갱신 시각", "conn", _c10_portfolio_freshness),
    ("C11", "trading", [2, 3], "split_orders 갱신 시각", "conn", _c11_split_orders_freshness),
    ("C12", "trading", [2, 3], "trades 최근 append", "conn", _c12_trades_recent),
    ("C13", "trading", [2, 3], "theme_context / scalp_session 갱신", "conn", _c13_theme_scalp_freshness),
    ("C14", "backup", [2, 3], "PRAGMA integrity_check", "conn", _c14_integrity_check),
    ("C15", "backup", [1, 2, 3], "WAL 파일 < 10MiB", "ctx", _c15_wal_size_bound),
    ("C16", "backup", [1, 2, 3], "디스크 여유 공간", "ctx", _c16_disk_free),
    ("C17", "regression", [3], "Chronicle master_index 갱신", "ctx", _c17_chronicle_drive_rw),
    ("C18", "regression", [3], "Drive paper_portfolio 더 이상 갱신 X", "ctx", _c18_drive_portfolio_stale),
    ("C19", "regression", [3], "Drive paper_trades 더 이상 갱신 X", "ctx", _c19_drive_trades_stale),
    ("C20", "regression", [1, 2, 3], "OAuth 만료 Pause 트리거", "ctx", _c20_oauth_pause_pattern),
]


# ---------------------------------------------------------------------------
# 보조 통계 (사양 §11.5)
# ---------------------------------------------------------------------------
def _collect_stats(ctx: RunContext) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "db_path": ctx.db_path,
        "service": ctx.service_name,
        "now_utc": ctx.now_utc.isoformat(timespec="seconds"),
    }

    # 파일 크기
    try:
        stats["db_size_bytes"] = os.path.getsize(ctx.db_path) if os.path.exists(ctx.db_path) else 0
    except OSError:
        stats["db_size_bytes"] = None
    try:
        stats["wal_size_bytes"] = os.path.getsize(ctx.wal_path) if os.path.exists(ctx.wal_path) else 0
    except OSError:
        stats["wal_size_bytes"] = None

    # 디스크
    try:
        usage = shutil.disk_usage("/")
        stats["disk_free_gib"] = round(usage.free / (1024 ** 3), 2)
        stats["disk_total_gib"] = round(usage.total / (1024 ** 3), 2)
    except OSError:
        stats["disk_free_gib"] = None
        stats["disk_total_gib"] = None

    if not os.path.exists(ctx.db_path):
        return stats

    try:
        conn = _open_db(ctx.db_path)
    except sqlite3.Error as exc:
        stats["db_open_error"] = str(exc)
        return stats

    try:
        # schema_version
        try:
            sv_rows = conn.execute(
                "SELECT version, applied_at, description FROM schema_version ORDER BY version"
            ).fetchall()
            stats["schema_version"] = [
                {"version": r[0], "applied_at": r[1], "description": r[2]} for r in sv_rows
            ]
        except sqlite3.Error as exc:
            stats["schema_version_error"] = str(exc)

        # row 수 + MAX(updated_at)
        domain_table_list = [
            ("portfolio", True),
            ("split_orders", True),
            ("theme_context", True),
            ("scalp_session", True),
            ("trades", False),
        ]
        domain_stats: Dict[str, Dict[str, Any]] = {}
        for table, has_updated in domain_table_list:
            entry: Dict[str, Any] = {"rows": _query_row_count(conn, table)}
            if has_updated:
                entry["max_updated_at"] = _query_max_updated_at(conn, table)
            domain_stats[table] = entry
        stats["domains"] = domain_stats

        # trades 최근 5건
        try:
            recent_rows = conn.execute(
                "SELECT ts, ticker FROM trades ORDER BY id DESC LIMIT 5"
            ).fetchall()
            stats["recent_trades"] = [
                {"ts": r[0], "ticker": r[1]} for r in recent_rows
            ]
        except sqlite3.Error:
            stats["recent_trades"] = []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return stats


# ---------------------------------------------------------------------------
# 실행 엔진
# ---------------------------------------------------------------------------
def _resolve_sqlite_activation_ts(ctx: RunContext) -> Optional[datetime]:
    """SQLite 활성화 시각 추정.

    우선순위:
      1. schema_version 의 v1 row 의 applied_at (백엔드 첫 부팅 시점).
      2. DB 파일의 mtime.
    """
    try:
        conn = _open_db(ctx.db_path)
    except sqlite3.Error:
        return None
    try:
        try:
            row = conn.execute(
                "SELECT applied_at FROM schema_version ORDER BY version LIMIT 1"
            ).fetchone()
            if row and row[0]:
                parsed = _parse_iso_to_utc(row[0])
                if parsed:
                    return parsed
        except sqlite3.Error:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        ts = os.path.getmtime(ctx.db_path)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except OSError:
        return None


def _resolve_sqlite_cutover_ts(ctx: RunContext) -> Optional[datetime]:
    """journalctl 에서 sqlite 백엔드 최초 부팅 로그 시각(UTC) 추정.

    출력 포맷은 `-o short-unix` 를 사용해 locale 영향 없이 epoch 초를 파싱한다.
    """
    rc, out, _err = _run_shell(
        [
            "journalctl",
            "-u",
            ctx.service_name,
            "--since",
            "30 day ago",
            "--no-pager",
            "-o",
            "short-unix",
        ],
        timeout_sec=20,
    )
    if rc != 0 or not out:
        return None
    epoch_list: List[float] = []
    for line in out.splitlines():
        if "[STATE_STORE]" not in line or "backend=sqlite" not in line:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)\s", line.strip())
        if not m:
            continue
        try:
            epoch_list.append(float(m.group(1)))
        except ValueError:
            continue
    if not epoch_list:
        return None
    return datetime.fromtimestamp(min(epoch_list), tz=timezone.utc)


def _run_all_checks(ctx: RunContext) -> List[CheckResult]:
    results: List[CheckResult] = []

    # DB 연결은 일부 점검에서만 사용. 첫 사용 시 lazy open + 끝나면 close.
    conn: Optional[sqlite3.Connection] = None

    def _ensure_conn() -> Optional[sqlite3.Connection]:
        nonlocal conn
        if conn is not None:
            return conn
        if not os.path.exists(ctx.db_path):
            return None
        try:
            conn = _open_db(ctx.db_path)
            return conn
        except sqlite3.Error:
            return None

    try:
        for check_id, category, day_scope, label, runner_kind, runner in _CHECK_LIST:
            if ctx.day_filter is not None and ctx.day_filter not in day_scope:
                continue
            start_ts = time.monotonic()
            try:
                if runner_kind == "conn":
                    conn_obj = _ensure_conn()
                    if conn_obj is None:
                        status, detail = (
                            _STATUS_FAIL,
                            f"DB 연결 불가 ({ctx.db_path})",
                        )
                    else:
                        status, detail = runner(conn_obj, ctx)
                else:
                    status, detail = runner(ctx)
            except Exception as exc:
                status = _STATUS_FAIL
                detail = f"점검 함수 예외: {type(exc).__name__}: {exc}"
            elapsed_ms = int((time.monotonic() - start_ts) * 1000)
            results.append(
                CheckResult(
                    check_id=check_id,
                    category=category,
                    day_scope=day_scope,
                    label=label,
                    status=status,
                    detail=detail,
                    elapsed_ms=elapsed_ms,
                )
            )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return results


def _aggregate_status(results: List[CheckResult]) -> str:
    statuses = {r.status for r in results}
    if _STATUS_FAIL in statuses:
        return _STATUS_FAIL
    if _STATUS_WARN in statuses:
        return _STATUS_WARN
    return _STATUS_PASS


def _exit_code_for(status: str) -> int:
    if status == _STATUS_FAIL:
        return _EXIT_FAIL
    if status == _STATUS_WARN:
        return _EXIT_WARN
    return _EXIT_PASS


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def _render_text(
    results: List[CheckResult],
    stats: Dict[str, Any],
    overall: str,
    ctx: RunContext,
) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("[M6 운영 안정성 점검] " + ctx.now_utc.isoformat(timespec="seconds"))
    day_label = f"Day {ctx.day_filter}" if ctx.day_filter else "Day 전체"
    lines.append(f"  서비스: {ctx.service_name}  /  DB: {ctx.db_path}  /  범위: {day_label}")
    lines.append("=" * 72)

    by_cat: Dict[str, List[CheckResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    for cat in ("boot", "runtime", "trading", "backup", "regression"):
        cat_results = by_cat.get(cat)
        if not cat_results:
            continue
        lines.append(f"\n[{cat.upper()}]")
        for r in cat_results:
            lines.append(f"  {r.check_id} {r.status:<4} {r.label}")
            if r.detail:
                lines.append(f"       └─ {r.detail}")

    lines.append("")
    lines.append("-" * 72)
    lines.append("[보조 통계]")
    if "schema_version" in stats:
        for sv in stats["schema_version"]:
            lines.append(
                f"  schema v{sv['version']} | {sv['applied_at']} | {sv['description']}"
            )
    if "domains" in stats:
        for table, info in stats["domains"].items():
            base = f"  {table:<16} rows={info['rows']}"
            if "max_updated_at" in info:
                base += f"  updated={info['max_updated_at']}"
            lines.append(base)
    if stats.get("recent_trades"):
        lines.append("  최근 trades:")
        for tr in stats["recent_trades"]:
            lines.append(f"    - {tr['ts']}  {tr['ticker']}")
    lines.append(
        f"  DB={stats.get('db_size_bytes')} bytes  WAL={stats.get('wal_size_bytes')} bytes"
    )
    lines.append(
        f"  / free={stats.get('disk_free_gib')} GiB / total={stats.get('disk_total_gib')} GiB"
    )

    lines.append("")
    lines.append("=" * 72)
    counts = {
        _STATUS_PASS: 0,
        _STATUS_WARN: 0,
        _STATUS_FAIL: 0,
        _STATUS_SKIP: 0,
    }
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    lines.append(
        f"[종합] {overall}  "
        f"PASS={counts[_STATUS_PASS]} WARN={counts[_STATUS_WARN]} "
        f"FAIL={counts[_STATUS_FAIL]} SKIP={counts[_STATUS_SKIP]}"
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def _render_json(
    results: List[CheckResult],
    stats: Dict[str, Any],
    overall: str,
    ctx: RunContext,
) -> str:
    payload = {
        "overall": overall,
        "now_utc": ctx.now_utc.isoformat(timespec="seconds"),
        "day_filter": ctx.day_filter,
        "service": ctx.service_name,
        "db_path": ctx.db_path,
        "results": [asdict(r) for r in results],
        "stats": stats,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_slack(
    results: List[CheckResult],
    stats: Dict[str, Any],
    overall: str,
    ctx: RunContext,
) -> str:
    """슬랙용 요약 텍스트. 비-PASS 만 상세 라인. 보조 통계 핵심만."""
    lines: List[str] = []
    day_label = f"Day {ctx.day_filter}" if ctx.day_filter else "Day 전체"
    icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(overall, f"[{overall}]")
    lines.append(f"{icon} M6 운영 안정성 점검 — 종합 {overall} ({day_label})")
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    lines.append(
        f"  PASS={counts['PASS']}  WARN={counts['WARN']}  "
        f"FAIL={counts['FAIL']}  SKIP={counts['SKIP']}"
    )

    non_pass = [r for r in results if r.status in (_STATUS_WARN, _STATUS_FAIL)]
    if non_pass:
        lines.append("  -- 비-PASS 상세 --")
        for r in non_pass:
            lines.append(f"  {r.check_id} {r.status} {r.label}: {r.detail}")
    domains = stats.get("domains") or {}
    if domains:
        domain_summary = ", ".join(
            f"{t}={info['rows']}" for t, info in domains.items()
        )
        lines.append(f"  rows: {domain_summary}")
    lines.append(
        f"  DB={stats.get('db_size_bytes')}B  WAL={stats.get('wal_size_bytes')}B  "
        f"free={stats.get('disk_free_gib')}GiB"
    )
    return "\n".join(lines)


def _resolve_slack_notifier(no_slack: bool) -> Optional[Callable[[str], None]]:
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
        try:
            client.chat_postMessage(channel=channel, text=text)
        except Exception:
            pass

    return _notify


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="M6 운영 안정성 자동 점검")
    parser.add_argument(
        "--db-path",
        default=os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db"),
        help="SQLite DB 파일 경로 (기본: STATE_STORE_DB_PATH → data/sqlite/autostock.db)",
    )
    parser.add_argument(
        "--service",
        default="stockbots.service",
        help="systemd unit 이름 (기본: stockbots.service)",
    )
    parser.add_argument(
        "--day",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Day 1/2/3 점검만 실행. 생략 시 전체.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 출력 (별도 agent 파싱용)",
    )
    parser.add_argument(
        "--slack",
        action="store_true",
        help="결과 요약을 슬랙에 1회 게시 (SLACK_TOKEN/SLACK_CHANNEL 필요)",
    )
    args = parser.parse_args(argv)

    try:
        ctx = RunContext(
            db_path=args.db_path,
            wal_path=args.db_path + "-wal",
            service_name=args.service,
            day_filter=args.day,
            now_utc=_utcnow(),
        )
        ctx.sqlite_activation_ts = _resolve_sqlite_activation_ts(ctx)
        ctx.sqlite_cutover_ts = _resolve_sqlite_cutover_ts(ctx) or ctx.sqlite_activation_ts

        results = _run_all_checks(ctx)
        stats = _collect_stats(ctx)
        overall = _aggregate_status(results)

        if args.json:
            print_flush(_render_json(results, stats, overall, ctx))
        else:
            print_flush(_render_text(results, stats, overall, ctx))

        if args.slack:
            notifier = _resolve_slack_notifier(no_slack=False)
            if notifier is None:
                print_flush("[WARN] 슬랙 미설정 (SLACK_TOKEN/SLACK_CHANNEL). 보고 생략.")
            else:
                notifier(_render_slack(results, stats, overall, ctx))

        return _exit_code_for(overall)
    except Exception as exc:
        print_flush(f"[TOOL ERROR] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return _EXIT_TOOL_ERROR


if __name__ == "__main__":
    sys.exit(main())
