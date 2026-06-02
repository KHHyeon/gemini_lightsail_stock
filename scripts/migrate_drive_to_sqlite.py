# -*- coding: utf-8 -*-
"""Drive -> SQLite 1회성 이관 스크립트.

5 도메인(portfolio / split_orders / theme_context / scalp_session / trades)을
Google Drive 에서 로드하여 로컬 SQLite 데이터베이스에 INSERT 한다.

특징:
- ``STATE_STORE_BACKEND`` 환경변수의 영향을 받지 않는다.
  Drive 측은 ``logger.load_json_from_gdrive`` 를 직접 호출하고,
  SQLite 측은 ``_SQLiteBackend`` 를 직접 인스턴스화한다.
- ``--dry-run`` 모드는 Drive 로드 + 카운트만 출력하고 INSERT 를 수행하지 않는다.
- ``--no-slack`` 모드는 슬랙 보고를 생략한다 (로컬 검증용).

종료 코드:
    0 - 정상 (또는 dry-run 정상)
    1 - Drive 로드 실패 (인증 / 권한 / 네트워크 등)
    2 - SQLite 마이그레이션 실패
    3 - 카운트 불일치 (Drive vs SQLite, dry-run 은 비교 생략)

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md (Phase 2 이관 스크립트),
      Doc/features/data_persistence/03_data_persistence_state_logic.md §9.6
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from typing import Any, List, Optional, Tuple


# scripts/_common.py 경로 활성화 (sys.path 등록).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=True)


# 도메인 매트릭스: (이름, Drive 파일명, 예상 컨테이너 타입, SQLite 테이블, 카운트 방식)
# 카운트 방식:
#   - keyed:  dict 의 key 개수 (key->payload 매핑 도메인)
#   - list:   list 길이 (시계열 도메인)
#   - single: dict 가 비어있지 않으면 1, 비어있으면 0 (단일 row 도메인)
_DOMAIN_LIST: List[Tuple[str, str, type, str, str]] = [
    ("portfolio", "paper_portfolio.json", dict, "portfolio", "keyed"),
    ("split_orders", "split_orders.json", dict, "split_orders", "keyed"),
    ("theme_context", "theme_context.json", dict, "theme_context", "keyed"),
    ("scalp_session", "scalp_session.json", dict, "scalp_session", "single"),
    ("trades", "paper_trades.json", list, "trades", "list"),
]


def _domain_count(data: Any, count_mode: str) -> int:
    if count_mode == "keyed":
        return len(data) if isinstance(data, dict) else 0
    if count_mode == "list":
        return len(data) if isinstance(data, list) else 0
    if count_mode == "single":
        return 1 if isinstance(data, dict) and len(data) > 0 else 0
    return 0


def _load_drive_payload(filename: str, expected_type: type) -> Any:
    """Drive 에서 도메인 데이터 로드. 예외 발생 시 상위로 전파.

    None 반환 시 빈 컨테이너(``{}`` 또는 ``[]``) 로 정규화.
    """
    from src.utils import logger

    data = logger.load_json_from_gdrive(filename)
    if data is None:
        return expected_type()
    if not isinstance(data, expected_type):
        raise TypeError(
            f"{filename}: 예상 타입 {expected_type.__name__}, 실측 {type(data).__name__}"
        )
    return data


def _sqlite_count(backend, table: str) -> int:
    """_SQLiteBackend 내부 connection 으로 COUNT(*) 조회."""
    row = backend._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _format_count_row(name: str, drive_n: int, sqlite_n: int, ok_flag: bool) -> str:
    status = "OK" if ok_flag else "MISMATCH"
    return f"  {name:<16} Drive={drive_n:<6} SQLite={sqlite_n:<6} {status}"


def _send_slack(text: str, notify_fn) -> None:
    """슬랙 전송. notify_fn 가 None 이면 무동작. stdout 중복 출력 회피용."""
    if not callable(notify_fn):
        return
    try:
        notify_fn(text)
    except Exception:
        # 슬랙 실패는 이관 결과를 무효화하지 않는다.
        pass


def _resolve_slack_notifier(no_slack: bool):
    """슬랙 알림 callable 반환. ``--no-slack`` 또는 토큰 없으면 None."""
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Drive -> SQLite 1회성 이관")
    parser.add_argument(
        "--db-path",
        default=os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db"),
        help="SQLite DB 파일 경로 (기본: data/sqlite/autostock.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Drive 로드 + 카운트만 출력. INSERT 미실행.",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="슬랙 보고 생략 (로컬 검증용).",
    )
    args = parser.parse_args(argv)

    notify_fn = _resolve_slack_notifier(args.no_slack)
    started_at = time.monotonic()

    # ----- Step 1/5 Drive 로드 -----
    print_flush(f"[Step 1/5] Drive 5 도메인 로드")
    drive_payload_map: dict = {}
    drive_count_map: dict = {}
    try:
        for name, filename, expected_type, _table, count_mode in _DOMAIN_LIST:
            payload = _load_drive_payload(filename, expected_type)
            drive_payload_map[name] = payload
            drive_count_map[name] = _domain_count(payload, count_mode)
            print_flush(f"  - {name:<16} {filename:<24} entries={drive_count_map[name]}")
    except Exception as exc:
        print_flush(f"[ERROR] Drive 로드 실패: {exc}")
        traceback.print_exc()
        return 1

    # ----- Step 2/5 SQLite 스키마 부트스트랩 -----
    print_flush(f"[Step 2/5] SQLite 스키마 부트스트랩 ({args.db_path})")
    try:
        from src.storage.sqlite_backend import _SQLiteBackend

        backend = _SQLiteBackend(db_path=args.db_path, notify_fn=notify_fn)
    except Exception as exc:
        print_flush(f"[ERROR] SQLite 초기화 실패: {exc}")
        traceback.print_exc()
        return 2

    # ----- Step 3/5 dry-run? -----
    if args.dry_run:
        print_flush(f"[Step 3/5] dry-run 모드: INSERT 건너뜀")
        print_flush(f"[Step 4/5] INSERT 미실행 (--dry-run)")
        elapsed = time.monotonic() - started_at
        summary_lines = [
            "[Drive->SQLite 이관] dry-run 결과",
            *[
                f"  - {name:<16} Drive entries={drive_count_map[name]}"
                for name, _f, _t, _tbl, _cm in _DOMAIN_LIST
            ],
            f"  소요: {elapsed:.2f}s",
        ]
        summary = "\n".join(summary_lines)
        print_flush(f"[Step 5/5] {summary}")
        _send_slack(summary, notify_fn)
        backend.close()
        return 0

    # ----- Step 3/5 실제 INSERT -----
    print_flush(f"[Step 3/5] 도메인별 INSERT")
    try:
        for name, filename, _t, _tbl, _cm in _DOMAIN_LIST:
            payload = drive_payload_map[name]
            backend.write_json(filename, payload)
            print_flush(f"  - {name:<16} INSERT 완료")
    except Exception as exc:
        print_flush(f"[ERROR] INSERT 실패: {exc}")
        traceback.print_exc()
        backend.close()
        return 2

    # ----- Step 4/5 카운트 비교 -----
    print_flush(f"[Step 4/5] 카운트 비교")
    mismatch_list: List[str] = []
    report_lines: List[str] = []
    for name, _f, _t, table, _cm in _DOMAIN_LIST:
        drive_n = drive_count_map[name]
        sqlite_n = _sqlite_count(backend, table)
        ok_flag = drive_n == sqlite_n
        if not ok_flag:
            mismatch_list.append(name)
        report_lines.append(_format_count_row(name, drive_n, sqlite_n, ok_flag))
    print_flush("\n".join(report_lines))

    # ----- Step 5/5 결과 보고 -----
    elapsed = time.monotonic() - started_at
    if mismatch_list:
        summary = (
            f"[Drive->SQLite 이관] MISMATCH 발생 ({len(mismatch_list)} 도메인)\n"
            + "\n".join(report_lines)
            + f"\n  도메인 목록: {', '.join(mismatch_list)}"
            + f"\n  소요: {elapsed:.2f}s"
        )
        print_flush(f"[Step 5/5] {summary}")
        _send_slack(summary, notify_fn)
        backend.close()
        return 3

    summary = (
        "[Drive->SQLite 이관] 성공\n"
        + "\n".join(report_lines)
        + f"\n  소요: {elapsed:.2f}s"
    )
    print_flush(f"[Step 5/5] {summary}")
    _send_slack(summary, notify_fn)
    backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
