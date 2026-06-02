# -*- coding: utf-8 -*-
"""_SQLiteChronicleBackend — Chronicle Repository 의 SQLite 백엔드.

chronicle_entries / chronicle_reports / chronicle_report_sections /
chronicle_search (FTS5) / chronicle_backfill_state 5 테이블을 캡슐화한다.

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md §7,
      Doc/features/data_persistence/03_data_persistence_state_logic.md §11
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# INSERT ... ON CONFLICT DO UPDATE 패턴.
# 주의: ``INSERT OR REPLACE`` 는 PK 충돌 시 내부적으로 DELETE + INSERT 로 동작하여
# FK ON DELETE CASCADE 를 트리거 -> 자식 테이블(chronicle_reports / sections / search)
# row 가 의도치 않게 삭제된다. UPSERT 패턴은 PK 충돌 시 UPDATE 만 수행하므로 안전.
_INSERT_ENTRY_UPSERT_SQL = """
INSERT INTO chronicle_entries (
    entry_id, chronicle_date, source, trigger_reason,
    regime, regime_label, main_actor, sentiment,
    action_preview, context_tags_json, phrases_json, embedding_vector,
    report_rel_path, written_at, reindexed_at, migrated_at,
    schema_version, extra_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(entry_id) DO UPDATE SET
    chronicle_date    = excluded.chronicle_date,
    source            = excluded.source,
    trigger_reason    = excluded.trigger_reason,
    regime            = excluded.regime,
    regime_label      = excluded.regime_label,
    main_actor        = excluded.main_actor,
    sentiment         = excluded.sentiment,
    action_preview    = excluded.action_preview,
    context_tags_json = excluded.context_tags_json,
    phrases_json      = excluded.phrases_json,
    embedding_vector  = excluded.embedding_vector,
    report_rel_path   = excluded.report_rel_path,
    written_at        = excluded.written_at,
    reindexed_at      = excluded.reindexed_at,
    migrated_at       = excluded.migrated_at,
    schema_version    = excluded.schema_version,
    extra_json        = excluded.extra_json
"""


# ---------------------------------------------------------------------------
# .md 본문 파싱 헬퍼 (P3F5 / §11.5)
# ---------------------------------------------------------------------------
_SECTION_HEADING_REGEX = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _normalize_heading_key(heading_text: str) -> str:
    """헤딩 텍스트를 section_key 매핑용 정규형으로 변환 (공백/괄호 제거 + 소문자)."""
    cleaned = re.sub(r"[\s()\[\]·.,!?]", "", heading_text or "").lower()
    return cleaned


def _classify_section_key(heading_text: str) -> str:
    """헤딩 텍스트 -> section_key 5종 분류.

    한국어 표기를 우선 매칭하고, robustness 를 위해 영문 표기도 함께 인식한다.
    """
    norm = _normalize_heading_key(heading_text)
    if "intradayflow" in norm or "장중흐름" in norm:
        return "intraday_flow"
    if "eventandcause" in norm or "사건과원인" in norm:
        return "event_and_cause"
    if (
        "actionguideline" in norm
        or "미래행동지침" in norm
        or "행동지침" in norm
        or "최종행동" in norm
    ):
        return "action_guideline"
    if "onelinesummary" in norm or "한줄요약" in norm:
        return "one_line_summary"
    return "unknown"


def parse_full_md(full_md: str) -> Dict[str, Any]:
    """.md 본문을 (header_md, body_md, sections_list) 로 분해.

    헤딩 매칭 실패 시에도 본문은 손실 없이 ``unknown`` 으로 1 섹션 보존한다 (P3E1).

    Returns:
        {
            "header_md": str,                        # "# Market Chronicle ..." 까지 (첫 빈줄 직전)
            "body_md": str,                          # 나머지 전체
            "sections": [
                {"section_index": 0, "section_key": "intraday_flow", "section_title": "Intraday Flow (장중 흐름)", "body_md": "..."},
                ...
            ]
        }
    """
    if not isinstance(full_md, str):
        full_md = "" if full_md is None else str(full_md)

    # 1) 헤더/본문 분리: 첫 "## " 또는 첫 빈줄 두 개 (\n\n) 직전까지를 헤더로.
    first_h2_match = re.search(r"^##\s", full_md, re.MULTILINE)
    if first_h2_match:
        header_md = full_md[: first_h2_match.start()].rstrip() + "\n\n"
        body_md = full_md[first_h2_match.start():]
    else:
        # ## 헤딩이 전혀 없으면 전체를 body 로 (이 경우 unknown 1섹션).
        header_md = ""
        body_md = full_md

    # 2) ## 단위로 분할 + 분류.
    sections_list: List[Dict[str, Any]] = []
    heading_match_list = list(_SECTION_HEADING_REGEX.finditer(body_md))
    if not heading_match_list:
        # 헤딩 없음 -> 전체 본문을 unknown 1섹션으로 보존.
        if body_md.strip():
            sections_list.append({
                "section_index": 0,
                "section_key": "unknown",
                "section_title": "",
                "body_md": body_md.strip(),
            })
    else:
        for idx, match in enumerate(heading_match_list):
            heading_text = match.group(1).strip()
            start_pos = match.end()
            end_pos = (
                heading_match_list[idx + 1].start()
                if idx + 1 < len(heading_match_list)
                else len(body_md)
            )
            section_body = body_md[start_pos:end_pos].strip("\n")
            sections_list.append({
                "section_index": idx,
                "section_key": _classify_section_key(heading_text),
                "section_title": heading_text,
                "body_md": section_body,
            })

    return {
        "header_md": header_md,
        "body_md": body_md,
        "sections": sections_list,
    }


def _entry_dict_to_row_tuple(entry_dict: Dict[str, Any]) -> tuple:
    """v2 entry_dict -> chronicle_entries row tuple 변환."""
    market_state_dict = entry_dict.get("market_state") or {}
    context_tags_list = entry_dict.get("context_tags_list") or []
    phrases_list = entry_dict.get("phrases_list")
    embedding_vector = entry_dict.get("embedding_vector")

    embedding_blob: Optional[bytes] = None
    if isinstance(embedding_vector, (bytes, bytearray)):
        embedding_blob = bytes(embedding_vector)
    # 그 외 (list[float] 등) 는 v3.5 활성 시 별도 직렬화. 현재는 None.

    written_at = entry_dict.get("written_at") or entry_dict.get("reindexed_at") or _now_iso()

    return (
        str(entry_dict.get("id") or ""),
        str(entry_dict.get("date") or ""),
        str(entry_dict.get("source") or "chronicle"),
        str(entry_dict.get("trigger") or ""),
        str(market_state_dict.get("regime") or ""),
        market_state_dict.get("regime_label"),
        market_state_dict.get("main_actor"),
        market_state_dict.get("sentiment"),
        str(entry_dict.get("action_preview") or ""),
        json.dumps(context_tags_list, ensure_ascii=False),
        json.dumps(phrases_list, ensure_ascii=False) if phrases_list is not None else None,
        embedding_blob,
        str(entry_dict.get("report_rel_path") or ""),
        written_at,
        entry_dict.get("reindexed_at"),
        entry_dict.get("migrated_at"),
        2,
        None,
    )


def _row_to_entry_dict(row: tuple) -> Dict[str, Any]:
    """chronicle_entries row -> v2 entry_dict 복원 (호출부 호환 형식)."""
    (
        entry_id, chronicle_date, source, trigger_reason,
        regime, regime_label, main_actor, sentiment,
        action_preview, context_tags_json, phrases_json, embedding_vector,
        report_rel_path, written_at, reindexed_at, migrated_at,
        _schema_version, _extra_json,
    ) = row

    try:
        context_tags_list = json.loads(context_tags_json) if context_tags_json else []
    except (TypeError, ValueError):
        context_tags_list = []

    if phrases_json:
        try:
            phrases_list = json.loads(phrases_json)
        except (TypeError, ValueError):
            phrases_list = []
    else:
        phrases_list = []

    entry_dict: Dict[str, Any] = {
        "id": entry_id,
        "date": chronicle_date,
        "trigger": trigger_reason,
        "market_state": {
            "regime": regime,
            "regime_label": regime_label or "",
            "main_actor": main_actor or "",
            "sentiment": sentiment or "",
        },
        "context_tags_list": context_tags_list,
        "action_preview": action_preview,
        "phrases_list": phrases_list,
        "embedding_vector": embedding_vector,  # bytes 또는 None
        "report_rel_path": report_rel_path,
        "source": source,
    }
    if reindexed_at:
        entry_dict["reindexed_at"] = reindexed_at
    if migrated_at:
        entry_dict["migrated_at"] = migrated_at
    return entry_dict


class _SQLiteChronicleBackend:
    """chronicle_repo 의 SQLite 백엔드 구현.

    state_store 의 ``_SQLiteBackend`` 와 동일한 connection 자원 사용을 위해
    필요 시 모듈 외부에서 connection 을 주입받을 수 있도록 구성한다.
    Phase 3 에서는 단순화를 위해 단일 인스턴스/단일 connection 으로 운영한다.
    """

    def __init__(
        self,
        db_path: str,
        notify_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._db_path = db_path
        directory = os.path.dirname(os.path.abspath(db_path))
        if directory:
            os.makedirs(directory, exist_ok=True)

        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        from src.storage.migrations.runner import apply_pending

        apply_pending(self._conn, notify_fn=notify_fn)
        self._fts_available = self._check_fts_table_exists()

    def close(self) -> None:
        """테스트 정리용. 운영 중 호출 불필요."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # FTS 가용성
    # ------------------------------------------------------------------
    def _check_fts_table_exists(self) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name='chronicle_search'"
        ).fetchone()
        return row is not None

    def is_fts_available(self) -> bool:
        return self._fts_available

    # ------------------------------------------------------------------
    # Index R/W
    # ------------------------------------------------------------------
    def list_entries(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT entry_id, chronicle_date, source, trigger_reason, "
            "regime, regime_label, main_actor, sentiment, "
            "action_preview, context_tags_json, phrases_json, embedding_vector, "
            "report_rel_path, written_at, reindexed_at, migrated_at, "
            "schema_version, extra_json "
            "FROM chronicle_entries ORDER BY chronicle_date ASC, written_at ASC"
        ).fetchall()
        return [_row_to_entry_dict(r) for r in rows]

    def count_entries(self, *, source: Optional[str] = None) -> int:
        if source is None:
            row = self._conn.execute("SELECT COUNT(*) FROM chronicle_entries").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM chronicle_entries WHERE source = ?", (source,)
            ).fetchone()
        return int(row[0]) if row else 0

    def find_entry_by_date(self, chronicle_date: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT entry_id, chronicle_date, source, trigger_reason, "
            "regime, regime_label, main_actor, sentiment, "
            "action_preview, context_tags_json, phrases_json, embedding_vector, "
            "report_rel_path, written_at, reindexed_at, migrated_at, "
            "schema_version, extra_json "
            "FROM chronicle_entries WHERE chronicle_date = ? "
            "ORDER BY written_at DESC LIMIT 1",
            (chronicle_date,),
        ).fetchone()
        return _row_to_entry_dict(row) if row else None

    def find_entry_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT entry_id, chronicle_date, source, trigger_reason, "
            "regime, regime_label, main_actor, sentiment, "
            "action_preview, context_tags_json, phrases_json, embedding_vector, "
            "report_rel_path, written_at, reindexed_at, migrated_at, "
            "schema_version, extra_json "
            "FROM chronicle_entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        return _row_to_entry_dict(row) if row else None

    def append_entry(
        self,
        entry_dict: Dict[str, Any],
        *,
        header_md: Optional[str] = None,
        body_md: Optional[str] = None,
        full_md: Optional[str] = None,
    ) -> None:
        """C 인덱스 1 row + (있다면) D 본문 1 row + 섹션 N row + FTS N row 를 단일 트랜잭션으로 저장.

        full_md/body_md 가 모두 None 이면 인덱스 row 만 INSERT OR REPLACE 로 갱신하고
        기존 본문/섹션/FTS 는 **보존**한다 (reindex 용도). 본문 갱신을 원하면 full_md
        또는 body_md 를 명시한다.
        """
        entry_id = str(entry_dict.get("id") or "")
        if not entry_id:
            raise ValueError("chronicle_repo.append_entry: entry_dict['id'] 필수")
        chronicle_date = str(entry_dict.get("date") or "")
        row_tuple = _entry_dict_to_row_tuple(entry_dict)

        try:
            self._conn.execute("BEGIN")
            self._conn.execute(_INSERT_ENTRY_UPSERT_SQL, row_tuple)
            if full_md is not None or body_md is not None:
                self._delete_report_children(entry_id)
                self._insert_report_and_sections(
                    entry_id=entry_id,
                    chronicle_date=chronicle_date,
                    header_md=header_md,
                    body_md=body_md,
                    full_md=full_md,
                    written_at=row_tuple[13],
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def replace_entries(self, entries_list: List[Dict[str, Any]]) -> None:
        """전체 entries 교체. 본문/섹션/FTS 는 보존된다 (UPSERT 패턴).

        - 새 set 에서 사라진 entry_id 만 DELETE (FK CASCADE 로 본문도 함께 정리).
        - 새 set 의 entry 는 INSERT OR REPLACE 로 인덱스 row 만 갱신.

        본문까지 정리하려면 ``delete_entry(entry_id, delete_report=True)`` 를
        명시적으로 사용한다. backfill.reset 의 SQLite 분기가 그렇게 동작한다.
        reindex_keyphrases 는 인덱스만 갱신하므로 본 메서드 사용 시 본문 안전.
        """
        new_ids = {str(e.get("id") or "") for e in (entries_list or []) if e}
        try:
            self._conn.execute("BEGIN")
            existing_rows = self._conn.execute(
                "SELECT entry_id FROM chronicle_entries"
            ).fetchall()
            existing_ids = {row[0] for row in existing_rows}
            removed_ids = existing_ids - new_ids
            for removed_id in removed_ids:
                self._conn.execute(
                    "DELETE FROM chronicle_entries WHERE entry_id = ?", (removed_id,)
                )
                # FTS5 는 FK CASCADE 대상이 아니므로 명시 DELETE 필요.
                if self._fts_available:
                    self._conn.execute(
                        "DELETE FROM chronicle_search WHERE entry_id = ?", (removed_id,)
                    )
            for entry_dict in entries_list or []:
                row_tuple = _entry_dict_to_row_tuple(entry_dict)
                self._conn.execute(_INSERT_ENTRY_UPSERT_SQL, row_tuple)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def delete_entry(self, entry_id: str, *, delete_report: bool = True) -> bool:
        """entry 1건 삭제. delete_report=True 면 FK CASCADE 동작.

        delete_report=False 는 향후 인덱스만 교체하고 본문은 유지하고 싶은 경우용
        (예약 옵션). 본 메서드는 FK 가 켜진 상태이므로 chronicle_entries 삭제
        시 reports/sections/search 가 동기 삭제된다. delete_report=False 옵션은
        SQLite 모드에서는 의미상 무시되며 호환 인터페이스로만 제공한다.
        """
        try:
            self._conn.execute("BEGIN")
            cursor = self._conn.execute(
                "DELETE FROM chronicle_entries WHERE entry_id = ?", (entry_id,)
            )
            deleted = cursor.rowcount > 0
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return deleted

    # ------------------------------------------------------------------
    # Report (.md 본문) R/W
    # ------------------------------------------------------------------
    def save_report(
        self,
        entry_id: str,
        *,
        chronicle_date: str,
        header_md: str,
        body_md: str,
        full_md: str,
    ) -> None:
        """본문/섹션/FTS 만 단독 갱신 (인덱스 row 가 이미 존재한다는 전제).

        이관 스크립트의 ``--reports-only`` 옵션에서 사용. 일반 운영 흐름은
        ``append_entry`` 가 인덱스+본문을 1 트랜잭션으로 처리한다.
        """
        if not entry_id:
            raise ValueError("save_report: entry_id 필수")
        try:
            self._conn.execute("BEGIN")
            self._delete_report_children(entry_id)
            self._insert_report_and_sections(
                entry_id=entry_id,
                chronicle_date=chronicle_date,
                header_md=header_md,
                body_md=body_md,
                full_md=full_md,
                written_at=_now_iso(),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def get_report(self, entry_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT entry_id, chronicle_date, header_md, body_md, full_md, written_at "
            "FROM chronicle_reports WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "entry_id": row[0],
            "chronicle_date": row[1],
            "header_md": row[2],
            "body_md": row[3],
            "full_md": row[4],
            "written_at": row[5],
        }

    def report_exists(self, entry_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM chronicle_reports WHERE entry_id = ? LIMIT 1",
            (entry_id,),
        ).fetchone()
        return row is not None

    def report_exists_by_date(self, chronicle_date: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM chronicle_reports WHERE chronicle_date = ? LIMIT 1",
            (chronicle_date,),
        ).fetchone()
        return row is not None

    def list_sections(self, entry_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT section_index, section_key, section_title, body_md "
            "FROM chronicle_report_sections WHERE entry_id = ? "
            "ORDER BY section_index ASC",
            (entry_id,),
        ).fetchall()
        return [
            {
                "section_index": r[0],
                "section_key": r[1],
                "section_title": r[2],
                "body_md": r[3],
            }
            for r in rows
        ]

    def find_sections_by_key(self, section_key: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT s.entry_id, e.chronicle_date, s.section_index, s.section_key, "
            "       s.section_title, s.body_md "
            "FROM chronicle_report_sections AS s "
            "INNER JOIN chronicle_entries AS e ON e.entry_id = s.entry_id "
            "WHERE s.section_key = ? "
            "ORDER BY e.chronicle_date DESC, s.section_index ASC "
            "LIMIT ?",
            (section_key, int(limit)),
        ).fetchall()
        return [
            {
                "entry_id": r[0],
                "chronicle_date": r[1],
                "section_index": r[2],
                "section_key": r[3],
                "section_title": r[4],
                "body_md": r[5],
            }
            for r in rows
        ]

    def list_md_files(self) -> List[Dict[str, Any]]:
        """`backfill.diagnose_reports / purge_leftover_*` 호환을 위한 메타 목록.

        chronicle_reports 의 row 만 반환 (Drive 시절의 모든 .md 파일과 1:1).
        SQLite 모드에선 인덱스 미등록 .md 가 존재할 수 없으므로 leftover 개념이
        자동 소거된다 (FK CASCADE).
        """
        rows = self._conn.execute(
            "SELECT entry_id, chronicle_date, length(full_md) FROM chronicle_reports "
            "ORDER BY chronicle_date ASC"
        ).fetchall()
        return [
            {
                "entry_id": r[0],
                "chronicle_date": r[1],
                "full_md_size": int(r[2] or 0),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # FTS5 검색
    # ------------------------------------------------------------------
    def search_fulltext(
        self,
        query: str,
        *,
        limit: int = 10,
        section_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []
        if not self._fts_available:
            return self._search_regex_fallback(query, limit=limit, section_key=section_key)
        try:
            if section_key:
                rows = self._conn.execute(
                    "SELECT entry_id, chronicle_date, section_key, "
                    "       snippet(chronicle_search, 3, '<<', '>>', '...', 16) "
                    "FROM chronicle_search "
                    "WHERE body_md MATCH ? AND section_key = ? "
                    "LIMIT ?",
                    (query, section_key, int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT entry_id, chronicle_date, section_key, "
                    "       snippet(chronicle_search, 3, '<<', '>>', '...', 16) "
                    "FROM chronicle_search "
                    "WHERE body_md MATCH ? "
                    "LIMIT ?",
                    (query, int(limit)),
                ).fetchall()
        except sqlite3.OperationalError:
            return self._search_regex_fallback(query, limit=limit, section_key=section_key)
        return [
            {
                "entry_id": r[0],
                "chronicle_date": r[1],
                "section_key": r[2],
                "snippet": r[3],
            }
            for r in rows
        ]

    def _search_regex_fallback(
        self,
        query: str,
        *,
        limit: int = 10,
        section_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """FTS5 미가용 / 구문 오류 시 정규식 폴백 (P3E2)."""
        pattern_text = re.escape(query.strip())
        if not pattern_text:
            return []
        if section_key:
            rows = self._conn.execute(
                "SELECT s.entry_id, e.chronicle_date, s.section_key, s.body_md "
                "FROM chronicle_report_sections AS s "
                "INNER JOIN chronicle_entries AS e ON e.entry_id = s.entry_id "
                "WHERE s.section_key = ? "
                "ORDER BY e.chronicle_date DESC",
                (section_key,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT s.entry_id, e.chronicle_date, s.section_key, s.body_md "
                "FROM chronicle_report_sections AS s "
                "INNER JOIN chronicle_entries AS e ON e.entry_id = s.entry_id "
                "ORDER BY e.chronicle_date DESC"
            ).fetchall()
        matched: List[Dict[str, Any]] = []
        regex = re.compile(pattern_text, re.IGNORECASE)
        for entry_id, chronicle_date, sec_key, body_md in rows:
            m = regex.search(body_md or "")
            if not m:
                continue
            start = max(0, m.start() - 16)
            end = min(len(body_md), m.end() + 16)
            snippet = body_md[start:end].replace("\n", " ")
            matched.append({
                "entry_id": entry_id,
                "chronicle_date": chronicle_date,
                "section_key": sec_key,
                "snippet": snippet,
            })
            if len(matched) >= limit:
                break
        return matched

    # ------------------------------------------------------------------
    # backfill state
    # ------------------------------------------------------------------
    def get_backfill_state(self) -> Dict[str, Any]:
        row = self._conn.execute(
            "SELECT payload_json FROM chronicle_backfill_state WHERE id = 1"
        ).fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_backfill_state(self, state_dict: Dict[str, Any]) -> None:
        if not isinstance(state_dict, dict):
            raise TypeError("backfill_state 는 dict 만 허용")
        payload_json = json.dumps(state_dict, ensure_ascii=False)
        now = _now_iso()
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                INSERT INTO chronicle_backfill_state (id, payload_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (payload_json, now),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------
    # 내부 헬퍼: 본문+섹션+FTS 동시 갱신
    # ------------------------------------------------------------------
    def _delete_report_children(self, entry_id: str) -> None:
        """FK CASCADE 가 있어도 명시적으로 호출하여 idempotency 강화 + FTS 정리."""
        # FTS5 는 FK CASCADE 대상이 아니므로 명시 DELETE 필요.
        if self._fts_available:
            self._conn.execute(
                "DELETE FROM chronicle_search WHERE entry_id = ?", (entry_id,)
            )
        self._conn.execute(
            "DELETE FROM chronicle_report_sections WHERE entry_id = ?", (entry_id,)
        )
        self._conn.execute(
            "DELETE FROM chronicle_reports WHERE entry_id = ?", (entry_id,)
        )

    def _insert_report_and_sections(
        self,
        *,
        entry_id: str,
        chronicle_date: str,
        header_md: Optional[str],
        body_md: Optional[str],
        full_md: Optional[str],
        written_at: str,
    ) -> None:
        """body/sections/FTS 동시 INSERT.

        full_md 만 주어지면 parse_full_md 로 분해. body_md 가 명시되면 그대로 사용.
        """
        if full_md is None and body_md is None:
            return
        if full_md is None:
            # body_md 만 주어진 경우 — header_md 기본값 생성 후 full_md 재구성.
            header_md = header_md or f"# Market Chronicle {chronicle_date}\n\n"
            full_md = header_md + body_md
        parsed = parse_full_md(full_md)
        final_header_md = header_md if header_md is not None else parsed["header_md"]
        final_body_md = body_md if body_md is not None else parsed["body_md"]
        sections_list = parsed["sections"]

        self._conn.execute(
            """
            INSERT INTO chronicle_reports (
                entry_id, chronicle_date, header_md, body_md, full_md,
                written_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, 2)
            """,
            (entry_id, chronicle_date, final_header_md, final_body_md, full_md, written_at),
        )
        if not sections_list:
            return
        self._conn.executemany(
            """
            INSERT INTO chronicle_report_sections (
                entry_id, section_index, section_key, section_title, body_md
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    entry_id,
                    s["section_index"],
                    s["section_key"],
                    s["section_title"],
                    s["body_md"],
                )
                for s in sections_list
            ],
        )
        if self._fts_available:
            self._conn.executemany(
                """
                INSERT INTO chronicle_search (entry_id, chronicle_date, section_key, body_md)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (entry_id, chronicle_date, s["section_key"], s["body_md"])
                    for s in sections_list
                ],
            )
