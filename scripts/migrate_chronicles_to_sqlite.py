# -*- coding: utf-8 -*-
"""Chronicle (C/D 도메인 + backfill_state) Drive -> SQLite 1회성 이관 스크립트.

대상:
- C 도메인: ``MarketChronicles/index/master_index.json`` (v2 가드)
- D 도메인: 각 entry 의 ``report_rel_path`` (.md 본문) + 5 섹션 정규화 + FTS5
- 운영 상태: ``MarketChronicles/_system/backfill_state.json`` (단일 row)

특징:
- ``STATE_STORE_BACKEND`` 환경변수의 영향을 받지 않는다 (Phase 2 스크립트와 동일).
  Drive 측은 ``drive_client.*`` 직접 호출, SQLite 측은 ``_SQLiteChronicleBackend``
  를 직접 인스턴스화한다.
- **Idempotent**: 재실행 시 동일 결과 (시작 시 chronicle_entries 전체 비우기 +
  FK CASCADE 로 자식 동기 정리 -> 각 entry 의 UPSERT + 본문 INSERT).
- ``--dry-run`` 모드는 Drive 로드 + 카운트만 출력하고 INSERT 미실행.
- ``--no-slack`` 모드는 슬랙 보고를 생략한다 (로컬 검증용).
- ``--no-reports`` 모드는 본문/섹션/FTS 갱신을 생략하고 chronicle_entries 만
  적재한다 (인덱스 신속 동기화 + 본문은 차후 재실행). 거의 사용 안 함.

종료 코드:
    0 - 정상 (또는 dry-run 정상). skipped 가 있어도 인덱스가 일치하면 0.
    1 - Drive 로드 실패 (인증/권한/네트워크/스키마 불일치)
    2 - SQLite 마이그레이션 실패
    3 - 카운트 불일치 (entries 또는 reports)

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md §7.4 (Phase 3 이관 스크립트),
      Doc/features/data_persistence/03_data_persistence_state_logic.md §11.9
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=True)


def _load_drive_master_index() -> List[Dict[str, Any]]:
    """master_index.json 을 v2 가드 통과 후 entries list 만 반환."""
    from src.memory import drive_client

    # 마이그레이션 스크립트는 v1->v2 자동 변환 진입점이 아니므로 allow_auto_migrate=False.
    # v1 인 경우 DriveSchemaMismatchError 가 발생 → 호출부에서 운영자에게 안내.
    index_dict = drive_client.read_master_index(allow_auto_migrate=False)
    entries_list = index_dict.get("entries") or []
    return [e for e in entries_list if isinstance(e, dict)]


def _load_drive_backfill_state() -> Optional[Dict[str, Any]]:
    """backfill_state.json (선택). 부재 시 None."""
    from src.memory import drive_client

    rel = f"{drive_client.CHRONICLES_ROOT}/_system/backfill_state.json"
    try:
        data = drive_client.read_json_relative(rel)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _load_drive_report_md(rel_path: str) -> Optional[str]:
    """entry.report_rel_path 의 .md 본문 다운로드. 실패 시 None."""
    from src.memory import drive_client

    if not rel_path:
        return None
    try:
        text = drive_client.read_text_relative(rel_path)
    except Exception:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _count_sqlite(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _format_count_row(label: str, drive_n: int, sqlite_n: int, ok_flag: bool) -> str:
    status = "OK" if ok_flag else "MISMATCH"
    return f"  {label:<28} Drive={drive_n:<6} SQLite={sqlite_n:<6} {status}"


def _send_slack(text: str, notify_fn) -> None:
    if not callable(notify_fn):
        return
    try:
        notify_fn(text)
    except Exception:
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


def _instantiate_sqlite_backend(db_path: str, notify_fn):
    """`_SQLiteChronicleBackend` 직접 인스턴스화 (STATE_STORE_BACKEND 영향 무시).

    apply_pending(v001 + v002) 가 자동 실행되어 5 테이블 + FTS5 가 부트스트랩된다.
    """
    from src.storage.chronicle_sqlite_backend import _SQLiteChronicleBackend

    return _SQLiteChronicleBackend(db_path=db_path, notify_fn=notify_fn)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicle Drive -> SQLite 1회성 이관")
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
    parser.add_argument(
        "--no-reports",
        action="store_true",
        help="본문/섹션/FTS 갱신 생략. chronicle_entries 만 이관 (인덱스 동기화 전용).",
    )
    args = parser.parse_args(argv)

    notify_fn = _resolve_slack_notifier(args.no_slack)
    started_at = time.monotonic()

    # ----- Step 1/8 Drive 로드 (master_index + backfill_state) -----
    print_flush("[Step 1/8] Drive 로드 (master_index + backfill_state)")
    try:
        entries_list = _load_drive_master_index()
        backfill_state = _load_drive_backfill_state()
    except Exception as exc:
        print_flush(f"[ERROR] Drive 로드 실패: {exc}")
        traceback.print_exc()
        return 1
    drive_entries_n = len(entries_list)
    drive_backfill_present = backfill_state is not None
    print_flush(f"  - master_index.entries  : {drive_entries_n}건")
    print_flush(f"  - backfill_state.json   : {'있음' if drive_backfill_present else '없음'}")

    # ----- Step 2/8 SQLite 스키마 부트스트랩 -----
    print_flush(f"[Step 2/8] SQLite 스키마 부트스트랩 ({args.db_path})")
    try:
        backend = _instantiate_sqlite_backend(args.db_path, notify_fn)
    except Exception as exc:
        print_flush(f"[ERROR] SQLite 초기화 실패: {exc}")
        traceback.print_exc()
        return 2

    fts_available = backend.is_fts_available()
    print_flush(f"  - FTS5 가용성           : {'활성' if fts_available else '비활성 (정규식 폴백)'}")

    # ----- Step 3/8 dry-run? → INSERT 건너뛰고 카운트만 -----
    if args.dry_run:
        print_flush("[Step 3/8] dry-run 모드: INSERT 건너뜀")
        elapsed = time.monotonic() - started_at
        summary_lines = [
            "[Chronicle Drive->SQLite 이관] dry-run 결과",
            f"  - master_index.entries  : {drive_entries_n}건",
            f"  - backfill_state.json   : {'있음' if drive_backfill_present else '없음'}",
            f"  - FTS5 가용성           : {'활성' if fts_available else '비활성 (정규식 폴백)'}",
            f"  소요: {elapsed:.2f}s",
        ]
        summary = "\n".join(summary_lines)
        print_flush(f"[Step 8/8] {summary}")
        _send_slack(summary, notify_fn)
        backend.close()
        return 0

    # ----- Step 4/8 chronicle_entries 초기화 (CASCADE) + bulk INSERT -----
    # idempotent 보장을 위해 시작 시점에 전체 비우기.
    # FK CASCADE 로 chronicle_reports / chronicle_report_sections / chronicle_search 도 자동 정리.
    print_flush("[Step 4/8] chronicle_entries 초기화 + entries INSERT")
    try:
        backend.replace_entries([])  # 전체 비우기 (FK CASCADE)
        # FTS 는 FK CASCADE 대상이 아니지만 replace_entries 가 명시 DELETE 도 수행.
        for entry_dict in entries_list:
            # 본문 없이 인덱스만 먼저 적재 (UPSERT).
            backend.append_entry(entry_dict)
        sqlite_entries_n = _count_sqlite(backend._conn, "chronicle_entries")
        print_flush(f"  - chronicle_entries     : {sqlite_entries_n}건 INSERT 완료")
    except Exception as exc:
        print_flush(f"[ERROR] chronicle_entries INSERT 실패: {exc}")
        traceback.print_exc()
        backend.close()
        return 2

    # ----- Step 5/8 각 entry .md 본문 다운로드 + 파싱 + 저장 -----
    skipped_list: List[str] = []
    inserted_reports_n = 0
    if args.no_reports:
        print_flush("[Step 5/8] --no-reports 옵션: 본문/섹션/FTS 갱신 생략")
    else:
        print_flush(f"[Step 5/8] entry 본문 다운로드 + 파싱 + 저장 ({drive_entries_n}건)")
        for n, entry_dict in enumerate(entries_list, 1):
            entry_id = entry_dict.get("id") or ""
            chronicle_date = entry_dict.get("date") or ""
            rel_path = entry_dict.get("report_rel_path") or ""
            if not entry_id or not rel_path:
                skipped_list.append(f"{chronicle_date or entry_id} (필드 누락)")
                continue

            full_md = _load_drive_report_md(rel_path)
            if full_md is None:
                skipped_list.append(f"{chronicle_date} ({entry_id}) .md 누락/공백")
                continue

            try:
                backend.save_report(
                    entry_id,
                    chronicle_date=chronicle_date,
                    header_md="",       # parse_full_md 가 자동 분리
                    body_md="",
                    full_md=full_md,
                )
                inserted_reports_n += 1
            except Exception as exc:
                skipped_list.append(f"{chronicle_date} ({entry_id}) save_report 실패: {exc}")
                continue

            if n % 20 == 0:
                print_flush(f"  - 진행: {n}/{drive_entries_n}")

        sqlite_reports_n = _count_sqlite(backend._conn, "chronicle_reports")
        sqlite_sections_n = _count_sqlite(backend._conn, "chronicle_report_sections")
        sqlite_search_n = _count_sqlite(backend._conn, "chronicle_search") if fts_available else 0
        print_flush(f"  - chronicle_reports     : {sqlite_reports_n}건")
        print_flush(f"  - chronicle_report_sections : {sqlite_sections_n}건")
        if fts_available:
            print_flush(f"  - chronicle_search (FTS5)  : {sqlite_search_n}건")
        print_flush(f"  - skipped (본문 누락 등) : {len(skipped_list)}건")

    # ----- Step 6/8 backfill_state INSERT (단일 row) -----
    print_flush("[Step 6/8] backfill_state INSERT")
    if drive_backfill_present:
        try:
            backend.save_backfill_state(backfill_state)
            print_flush("  - chronicle_backfill_state : 1건 (UPSERT)")
        except Exception as exc:
            print_flush(f"[WARN] backfill_state 저장 실패 (인덱스/본문은 OK): {exc}")
    else:
        print_flush("  - Drive 측 backfill_state 부재 -> 스킵")

    # ----- Step 7/8 카운트 비교 -----
    print_flush("[Step 7/8] 카운트 비교")
    sqlite_entries_n = _count_sqlite(backend._conn, "chronicle_entries")
    sqlite_reports_n = _count_sqlite(backend._conn, "chronicle_reports") if not args.no_reports else 0
    sqlite_sections_n = _count_sqlite(backend._conn, "chronicle_report_sections") if not args.no_reports else 0
    sqlite_search_n = _count_sqlite(backend._conn, "chronicle_search") if (fts_available and not args.no_reports) else 0
    sqlite_backfill_n = _count_sqlite(backend._conn, "chronicle_backfill_state")

    drive_reports_expected = (drive_entries_n - len(skipped_list)) if not args.no_reports else 0

    report_lines: List[str] = []
    mismatch_list: List[str] = []

    ok_entries = (drive_entries_n == sqlite_entries_n)
    if not ok_entries:
        mismatch_list.append("chronicle_entries")
    report_lines.append(_format_count_row("chronicle_entries", drive_entries_n, sqlite_entries_n, ok_entries))

    if not args.no_reports:
        ok_reports = (drive_reports_expected == sqlite_reports_n)
        if not ok_reports:
            mismatch_list.append("chronicle_reports")
        report_lines.append(_format_count_row("chronicle_reports", drive_reports_expected, sqlite_reports_n, ok_reports))
        # sections / search 는 N:M 관계라 카운트 비교 대상이 아니다. 정보로만 출력.
        report_lines.append(f"  chronicle_report_sections   = {sqlite_sections_n}건 (참조)")
        if fts_available:
            report_lines.append(f"  chronicle_search (FTS5)      = {sqlite_search_n}건 (참조)")

    drive_backfill_n = 1 if drive_backfill_present else 0
    ok_backfill = (drive_backfill_n == sqlite_backfill_n)
    report_lines.append(_format_count_row("chronicle_backfill_state", drive_backfill_n, sqlite_backfill_n, ok_backfill))
    if not ok_backfill:
        mismatch_list.append("chronicle_backfill_state")

    print_flush("\n".join(report_lines))

    # ----- Step 8/8 결과 보고 -----
    elapsed = time.monotonic() - started_at
    if mismatch_list:
        summary = (
            f"[Chronicle Drive->SQLite 이관] MISMATCH 발생 ({len(mismatch_list)} 항목)\n"
            + "\n".join(report_lines)
            + f"\n  도메인 목록: {', '.join(mismatch_list)}"
            + (f"\n  skipped: {len(skipped_list)}건" if skipped_list else "")
            + f"\n  소요: {elapsed:.2f}s"
        )
        print_flush(f"[Step 8/8] {summary}")
        _send_slack(summary, notify_fn)
        backend.close()
        return 3

    summary_extra = ""
    if skipped_list:
        sample = "\n    ".join(skipped_list[:5])
        summary_extra = f"\n  skipped: {len(skipped_list)}건 (인덱스는 정상)\n    {sample}"
        if len(skipped_list) > 5:
            summary_extra += f"\n    ... 외 {len(skipped_list) - 5}건"

    summary = (
        "[Chronicle Drive->SQLite 이관] 성공\n"
        + "\n".join(report_lines)
        + summary_extra
        + f"\n  소요: {elapsed:.2f}s"
    )
    print_flush(f"[Step 8/8] {summary}")
    _send_slack(summary, notify_fn)
    backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
