# -*- coding: utf-8 -*-
"""Phase 3 Step 3 smoke test — chronicle_repo 라운드트립 + 섹션 + FTS + UPSERT 보존.

본 스크립트는 자동 실행 회귀가 아닌 일회성 검증용이다. py_compile 의 lint 와
별개로, 모듈을 실제로 import 했을 때의 동작과 도메인 시나리오를 점검한다.

검증 항목:
    [1/7] 기본=Drive 백엔드 (_DriveChronicleBackend)
    [2/7] 알 수 없는 백엔드 값 -> Drive 폴백
    [3/7] SQLite 라운드트립: 인덱스 + 본문 + 섹션 + FTS
    [4/7] 섹션 5종 분류 정확도 (intraday_flow / event_and_cause / action_guideline /
          one_line_summary / unknown)
    [5/7] UPSERT 패턴: chronicle_index_replace_all 시 본문/섹션 보존
    [6/7] FK CASCADE: chronicle_delete_entry(delete_report=True) 시 본문 동기 삭제
    [7/7] schema_version v2 기록

실행:
    python tests/smoke_chronicle_repo.py
"""
from __future__ import annotations

import os
import sys
import tempfile


_SAMPLE_FULL_MD_KO = """# Market Chronicle 2026-06-02

트리거: KOSPI 급락

## Intraday Flow (장중 흐름)
- 09:00 외국인 대량 매도로 -2.5% 출발
- 11:30 추가 하락 지속 -3.2%
- 15:30 패닉셀 진정, -2.8% 마감

## 사건과 원인
- 미국 채권금리 급등 + 반도체 약세
- 외국인 1조 순매도

## 미래 행동 지침 (핵심)
- 신규 매수 중단
- 보유 비중 50% 이하 축소
- 안전자산(현금) 보유 확대

## 한 줄 요약
- 외국인발 패닉셀에서는 일단 멈춘다.
"""


def _purge_storage_modules() -> None:
    for name in list(sys.modules.keys()):
        if name.startswith("src.storage"):
            del sys.modules[name]


def _close_chronicle_backends() -> None:
    """Windows 환경의 WAL/SHM 잠금이 임시 디렉터리 cleanup 을 막는 것 회피."""
    for mod_name in ("src.storage.state_store", "src.storage.chronicle_repo"):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            backend = getattr(mod, "_backend", None)
            close_fn = getattr(backend, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass


def _check_drive_default() -> None:
    """환경변수 미설정 시 _DriveChronicleBackend 가 선택되어야 한다."""
    os.environ.pop("STATE_STORE_BACKEND", None)
    os.environ.pop("STATE_STORE_DB_PATH", None)
    _purge_storage_modules()
    from src.storage import chronicle_repo

    assert type(chronicle_repo._backend).__name__ == "_DriveChronicleBackend", (
        f"기본 백엔드는 _DriveChronicleBackend 여야 합니다 "
        f"(실측: {type(chronicle_repo._backend).__name__})"
    )
    assert chronicle_repo.chronicle_fts_available() is False, "Drive 모드는 FTS 비활성"
    print("[1/7] 기본=Drive(_DriveChronicleBackend) 보존 OK")


def _check_unknown_fallback() -> None:
    """알 수 없는 백엔드 값은 _DriveChronicleBackend 로 폴백."""
    os.environ["STATE_STORE_BACKEND"] = "postgres"
    _purge_storage_modules()
    from src.storage import chronicle_repo

    assert type(chronicle_repo._backend).__name__ == "_DriveChronicleBackend"
    os.environ.pop("STATE_STORE_BACKEND", None)
    print("[2/7] 알 수 없는 값 -> Drive 폴백 OK")


def _check_sqlite_roundtrip(tmpdir: str) -> None:
    """SQLite 백엔드의 인덱스/본문/섹션/FTS 라운드트립."""
    db_path = os.path.join(tmpdir, "smoke.db")
    os.environ["STATE_STORE_BACKEND"] = "sqlite"
    os.environ["STATE_STORE_DB_PATH"] = db_path
    _purge_storage_modules()
    from src.storage import state_store

    assert type(state_store._backend).__name__ == "_SQLiteBackend"
    # chronicle_repo 의 백엔드도 따로 결정됨
    from src.storage import chronicle_repo
    assert type(chronicle_repo._backend).__name__ == "_SQLiteChronicleBackend"

    # 빈 상태
    assert state_store.chronicle_index_list() == []
    assert state_store.chronicle_index_count() == 0
    assert state_store.chronicle_get_backfill_state() == {}

    entry_dict = {
        "id": "abc12345",
        "date": "2026-06-02",
        "trigger": "KOSPI 급락",
        "market_state": {
            "regime": "PANIC_SELL",
            "regime_label": "강한 하락장 (Panic)",
            "main_actor": "외국인",
            "sentiment": "위험 회피",
        },
        "context_tags_list": ["외국인_매도", "패닉셀_확산"],
        "action_preview": "신규 매수 중단, 비중 축소",
        "phrases_list": [
            {"phrase": "외국인 매도 확대", "subject": "외국인", "action": "매도", "tone": "negative"}
        ],
        "embedding_vector": None,
        "report_rel_path": "MarketChronicles/reports/2026/06/2026-06-02_chronicle.md",
        "source": "chronicle",
    }

    state_store.chronicle_index_append(entry_dict, full_md=_SAMPLE_FULL_MD_KO)
    assert state_store.chronicle_index_count() == 1
    assert state_store.chronicle_report_exists("abc12345") is True
    assert state_store.chronicle_report_exists_by_date("2026-06-02") is True

    found_by_date = state_store.chronicle_find_entry_by_date("2026-06-02")
    assert found_by_date is not None
    assert found_by_date["id"] == "abc12345"
    assert found_by_date["market_state"]["regime"] == "PANIC_SELL"
    assert "외국인_매도" in found_by_date["context_tags_list"]

    report = state_store.chronicle_get_report("abc12345")
    assert report is not None
    assert len(report["full_md"]) > 100
    assert "패닉셀" in report["full_md"]

    # backfill_state 라운드트립
    state_dict = {"queue": ["2026-05-30", "2026-05-31"], "lookback_days": 7}
    state_store.chronicle_save_backfill_state(state_dict)
    restored = state_store.chronicle_get_backfill_state()
    assert restored["lookback_days"] == 7
    assert restored["queue"] == ["2026-05-30", "2026-05-31"]

    print("[3/7] SQLite 인덱스/본문/backfill_state 라운드트립 OK")


def _check_section_classification() -> None:
    """5종 섹션 분류 정확도 (한국어 + 영문)."""
    from src.storage import state_store
    sections = state_store.chronicle_list_sections("abc12345")
    section_keys = {s["section_key"] for s in sections}
    expected_keys = {"intraday_flow", "event_and_cause", "action_guideline", "one_line_summary"}
    missing = expected_keys - section_keys
    assert not missing, f"섹션 누락: {missing} (실측: {section_keys})"

    # 섹션 index 순서 보존
    indices = [s["section_index"] for s in sections]
    assert indices == sorted(indices), f"section_index 순서 어긋남: {indices}"

    # find_sections_by_key
    action_hits = state_store.chronicle_find_sections_by_key("action_guideline", limit=5)
    assert len(action_hits) == 1
    assert "매수 중단" in action_hits[0]["body_md"]

    # FTS 검색 — 영문/숫자 토큰은 unicode61 으로 정확 매칭
    fts_hits = state_store.chronicle_search_fulltext("패닉셀", limit=5)
    # 한국어 단일 토큰은 unicode61 토크나이저에서 매칭 안 될 수 있음 (Phase 3.5 보완)
    # 따라서 단순 검색은 성공/실패 모두 허용 — fts_available 만 보장.
    assert state_store.chronicle_fts_available() is True
    print(f"[4/7] 섹션 분류 4/4 + 검색 OK (fts hits='패닉셀'={len(fts_hits)})")


def _check_upsert_preserves_report() -> None:
    """chronicle_index_replace_all 시 본문/섹션이 보존되어야 한다 (UPSERT 패턴)."""
    from src.storage import state_store

    before_sections = len(state_store.chronicle_list_sections("abc12345"))
    before_report = state_store.chronicle_get_report("abc12345")
    assert before_report is not None
    before_md_len = len(before_report["full_md"])

    entries_keep = state_store.chronicle_index_list()
    state_store.chronicle_index_replace_all(entries_keep)

    after_sections = len(state_store.chronicle_list_sections("abc12345"))
    after_report = state_store.chronicle_get_report("abc12345")
    assert after_report is not None, "replace_all 후 본문이 손실됨 — UPSERT 패턴 회귀!"
    assert len(after_report["full_md"]) == before_md_len
    assert after_sections == before_sections == 4

    print(f"[5/7] UPSERT 본문 보존 OK (md_len={before_md_len}, sections={before_sections})")


def _check_delete_cascade() -> None:
    """delete_entry(delete_report=True) -> 본문/섹션/FTS 동기 삭제."""
    from src.storage import state_store

    deleted = state_store.chronicle_delete_entry("abc12345", delete_report=True)
    assert deleted is True
    assert state_store.chronicle_index_count() == 0
    assert state_store.chronicle_report_exists("abc12345") is False
    assert state_store.chronicle_list_sections("abc12345") == []
    print("[6/7] FK CASCADE delete_entry OK")


def _check_schema_version(tmpdir: str) -> None:
    """schema_version 테이블에 v1 + v2 가 모두 기록되어야 한다."""
    import sqlite3

    db_path = os.path.join(tmpdir, "smoke.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    conn.close()
    versions = [r[0] for r in rows]
    assert versions == [1, 2], f"schema_version 기록 어긋남: {versions}"
    print("[7/7] schema_version v1 + v2 기록 OK")


def main() -> None:
    sys.path.insert(0, ".")
    tmpdir_obj = tempfile.TemporaryDirectory()
    try:
        _check_drive_default()
        _check_unknown_fallback()
        _check_sqlite_roundtrip(tmpdir_obj.name)
        _check_section_classification()
        _check_upsert_preserves_report()
        _check_delete_cascade()
        _check_schema_version(tmpdir_obj.name)
        print("\nALL OK")
    finally:
        _close_chronicle_backends()
        try:
            tmpdir_obj.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
