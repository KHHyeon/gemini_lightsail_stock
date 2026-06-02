# -*- coding: utf-8 -*-
"""chronicle_repo — Market Chronicles (C/D 도메인 + backfill_state) Repository.

Phase 3 신설. chronicle_writer / backfill / context_retriever 의 Drive 직결
호출을 본 모듈로 우회시킨다. 백엔드는 ``STATE_STORE_BACKEND`` 환경변수로
모듈 로드 시 1회 결정한다 (Phase 1/2 와 동일 패턴).

  - 기본값/미설정: ``_DriveChronicleBackend`` (기존 ``drive_client.*`` 위임).
  - ``sqlite``: ``_SQLiteChronicleBackend`` (``data/sqlite/autostock.db``).
  - 알 수 없는 값: stderr 경고 1회 + Drive fallback.

호출자는 ``from src.storage import state_store`` 만 import 하고 state_store
가 re-export 하는 ``chronicle_*`` 함수를 사용한다. 본 모듈을 직접 import
하지 않는다 (Repository 패턴).

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md §7,
      Doc/features/data_persistence/03_data_persistence_state_logic.md §11
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


_DEFAULT_DB_PATH = "data/sqlite/autostock.db"


# ---------------------------------------------------------------------------
# Drive 백엔드 (Phase 3 호환 모드) — 기존 drive_client 호출에 위임
# ---------------------------------------------------------------------------
class _DriveChronicleBackend:
    """Phase 3 Drive 호환 백엔드.

    SQLite 모드가 활성되지 않은 환경에서 ``chronicle_repo.*`` 공개 API 가
    기존 ``drive_client.*`` 호출과 동일한 결과를 내도록 위임만 수행한다.
    행동은 Phase 1/2 시기와 완벽히 동일하다 (회귀 0).
    """

    # ---- Index R/W ----
    def list_entries(self) -> List[Dict[str, Any]]:
        from src.memory import drive_client

        try:
            index_dict = drive_client.read_master_index()
        except Exception:
            return []
        entries = index_dict.get("entries") or []
        return [e for e in entries if isinstance(e, dict)]

    def count_entries(self, *, source: Optional[str] = None) -> int:
        entries = self.list_entries()
        if source is None:
            return len(entries)
        return sum(1 for e in entries if e.get("source") == source)

    def find_entry_by_date(self, chronicle_date: str) -> Optional[Dict[str, Any]]:
        for entry in reversed(self.list_entries()):
            if entry.get("date") == chronicle_date:
                return entry
        return None

    def find_entry_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        for entry in self.list_entries():
            if entry.get("id") == entry_id:
                return entry
        return None

    def append_entry(
        self,
        entry_dict: Dict[str, Any],
        *,
        header_md: Optional[str] = None,
        body_md: Optional[str] = None,
        full_md: Optional[str] = None,
    ) -> None:
        """Drive 모드: 본문(.md) 먼저 저장 + master_index 에 append.

        체크 순서:
          1) full_md 가 있으면 ``report_rel_path`` 로 본문 저장.
          2) master_index 에 entry append.

        본 메서드는 Phase 3 이전의 ``write_text_relative`` + ``append_index_entry``
        조합과 동일한 결과를 낸다. 단, 단일 트랜잭션 보장은 없다 (Drive 한계).
        """
        from src.memory import drive_client

        rel_path = entry_dict.get("report_rel_path") or ""
        if full_md is not None and rel_path:
            drive_client.write_text_relative(rel_path, full_md, mime_type="text/markdown")

        drive_client.append_index_entry(entry_dict)

    def replace_entries(self, entries_list: List[Dict[str, Any]]) -> None:
        from src.memory import drive_client

        index_dict = drive_client.read_master_index()
        index_dict["entries"] = list(entries_list or [])
        drive_client.write_master_index(index_dict)

    def delete_entry(self, entry_id: str, *, delete_report: bool = True) -> bool:
        from src.memory import drive_client

        index_dict = drive_client.read_master_index()
        entries = index_dict.get("entries") or []
        target_entry = None
        new_entries = []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == entry_id:
                target_entry = entry
                continue
            new_entries.append(entry)
        if target_entry is None:
            return False

        if delete_report:
            rel = target_entry.get("report_rel_path")
            if rel:
                try:
                    drive_client.delete_file_relative(rel)
                except Exception:
                    pass

        index_dict["entries"] = new_entries
        drive_client.write_master_index(index_dict)
        return True

    # ---- Report R/W ----
    def save_report(
        self,
        entry_id: str,
        *,
        chronicle_date: str,
        header_md: str,
        body_md: str,
        full_md: str,
    ) -> None:
        """Drive 모드: entry_id 로 인덱스를 찾아 report_rel_path 에 본문 저장."""
        from src.memory import drive_client

        entry = self.find_entry_by_id(entry_id)
        rel_path = (entry or {}).get("report_rel_path")
        if not rel_path:
            # 인덱스 미존재 — 호출부가 chronicle_date 로 경로를 산출하도록 한다.
            from src.memory import chronicle_common
            rel_path = chronicle_common.report_rel_path(chronicle_date)
        drive_client.write_text_relative(rel_path, full_md, mime_type="text/markdown")

    def get_report(self, entry_id: str) -> Optional[Dict[str, Any]]:
        from src.memory import drive_client

        entry = self.find_entry_by_id(entry_id)
        rel = (entry or {}).get("report_rel_path")
        if not rel:
            return None
        try:
            full_md = drive_client.read_text_relative(rel) or ""
        except Exception:
            return None
        # 파싱은 SQLite 백엔드의 헬퍼를 재사용 (단순 분해 결과 제공).
        from src.storage.chronicle_sqlite_backend import parse_full_md

        parsed = parse_full_md(full_md)
        return {
            "entry_id": entry_id,
            "chronicle_date": (entry or {}).get("date", ""),
            "header_md": parsed["header_md"],
            "body_md": parsed["body_md"],
            "full_md": full_md,
            "written_at": (entry or {}).get("written_at", ""),
        }

    def report_exists(self, entry_id: str) -> bool:
        entry = self.find_entry_by_id(entry_id)
        return bool(entry and entry.get("report_rel_path"))

    def report_exists_by_date(self, chronicle_date: str) -> bool:
        from src.memory import drive_client, chronicle_common

        rel = chronicle_common.report_rel_path(chronicle_date)
        try:
            return drive_client.file_exists_relative(rel)
        except Exception:
            return False

    def list_sections(self, entry_id: str) -> List[Dict[str, Any]]:
        report = self.get_report(entry_id)
        if not report:
            return []
        from src.storage.chronicle_sqlite_backend import parse_full_md

        parsed = parse_full_md(report["full_md"])
        return parsed["sections"]

    def find_sections_by_key(self, section_key: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        """Drive 모드는 본문 N건 다운로드가 필요해 비용이 크다.

        호환성을 위해 entries 를 역순으로 훑으며 limit 만큼 채워 반환한다.
        실제 운영은 SQLite 모드를 권장.
        """
        result: List[Dict[str, Any]] = []
        for entry in reversed(self.list_entries()):
            entry_id = entry.get("id")
            chronicle_date = entry.get("date", "")
            for sec in self.list_sections(entry_id):
                if sec.get("section_key") == section_key:
                    result.append({
                        "entry_id": entry_id,
                        "chronicle_date": chronicle_date,
                        "section_index": sec.get("section_index"),
                        "section_key": sec.get("section_key"),
                        "section_title": sec.get("section_title"),
                        "body_md": sec.get("body_md"),
                    })
                    if len(result) >= limit:
                        return result
        return result

    def list_md_files(self) -> List[Dict[str, Any]]:
        """Drive 의 reports/**/*.md 재귀 스캔 결과를 통일 포맷으로 반환.

        ``backfill.diagnose_reports / purge_leftover_*`` 호환용.
        SQLite 백엔드와는 의미가 약간 다르다 — Drive 측은 인덱스 미등록 .md
        도 함께 노출한다 (leftover 탐지 가능).
        """
        from src.memory import drive_client

        reports_root = f"{drive_client.CHRONICLES_ROOT}/reports"
        try:
            return self._collect_md_recursive(reports_root)
        except Exception:
            return []

    def _collect_md_recursive(self, rel_folder: str) -> List[Dict[str, Any]]:
        from src.memory import drive_client

        results: List[Dict[str, Any]] = []
        try:
            items = drive_client.list_files_under(rel_folder)
        except Exception:
            return results
        for item in items:
            name = item.get("name", "")
            mime = item.get("mimeType", "")
            if mime == "application/vnd.google-apps.folder":
                results.extend(self._collect_md_recursive(f"{rel_folder}/{name}"))
            elif name.lower().endswith(".md"):
                results.append({
                    "id": item.get("id"),
                    "name": name,
                    "rel_path": f"{rel_folder}/{name}",
                })
        return results

    # ---- FTS ----
    def search_fulltext(
        self,
        query: str,
        *,
        limit: int = 10,
        section_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Drive 모드는 정규식 폴백만 제공 (모든 .md 다운로드 필요 — 비권장).

        실제 운영은 SQLite 모드에서 FTS5 사용 권장. Drive 모드에선 사용 자제.
        """
        import re

        if not query or not query.strip():
            return []
        pattern_text = re.escape(query.strip())
        if not pattern_text:
            return []
        regex = re.compile(pattern_text, re.IGNORECASE)
        result: List[Dict[str, Any]] = []
        for entry in reversed(self.list_entries()):
            entry_id = entry.get("id")
            chronicle_date = entry.get("date", "")
            for sec in self.list_sections(entry_id):
                if section_key and sec.get("section_key") != section_key:
                    continue
                body = sec.get("body_md") or ""
                m = regex.search(body)
                if not m:
                    continue
                start = max(0, m.start() - 16)
                end = min(len(body), m.end() + 16)
                snippet = body[start:end].replace("\n", " ")
                result.append({
                    "entry_id": entry_id,
                    "chronicle_date": chronicle_date,
                    "section_key": sec.get("section_key"),
                    "snippet": snippet,
                })
                if len(result) >= limit:
                    return result
        return result

    def is_fts_available(self) -> bool:
        return False  # Drive 모드는 항상 정규식 폴백.

    # ---- backfill state ----
    def get_backfill_state(self) -> Dict[str, Any]:
        from src.memory import drive_client

        rel = f"{drive_client.CHRONICLES_ROOT}/_system/backfill_state.json"
        try:
            data = drive_client.read_json_relative(rel)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def save_backfill_state(self, state_dict: Dict[str, Any]) -> None:
        from src.memory import drive_client

        if not isinstance(state_dict, dict):
            raise TypeError("backfill_state 는 dict 만 허용")
        rel = f"{drive_client.CHRONICLES_ROOT}/_system/backfill_state.json"
        drive_client.write_json_relative(rel, state_dict)


# ---------------------------------------------------------------------------
# 백엔드 선택 (모듈 로드 시 1회)
# ---------------------------------------------------------------------------
def _resolve_backend():
    """환경변수에 따라 chronicle_repo 의 백엔드 인스턴스를 1회 결정.

    state_store._resolve_backend 와 동일한 규약을 따른다 (값/폴백/경고).
    """
    backend_name = os.getenv("STATE_STORE_BACKEND", "drive").strip().lower()
    if backend_name == "sqlite":
        db_path = os.getenv("STATE_STORE_DB_PATH", _DEFAULT_DB_PATH).strip() or _DEFAULT_DB_PATH
        from src.storage.chronicle_sqlite_backend import _SQLiteChronicleBackend

        print(f"[CHRONICLE_REPO] backend=sqlite db_path={db_path}", flush=True)
        return _SQLiteChronicleBackend(db_path=db_path)
    if backend_name not in ("drive", ""):
        print(
            f"[chronicle_repo] 알 수 없는 STATE_STORE_BACKEND='{backend_name}' "
            f"-> Drive 백엔드로 폴백",
            file=sys.stderr,
        )
    print("[CHRONICLE_REPO] backend=drive", flush=True)
    return _DriveChronicleBackend()


_backend = _resolve_backend()


# ---------------------------------------------------------------------------
# 공개 API (16 함수). state_store 가 본 모듈을 re-export 한다.
# ---------------------------------------------------------------------------

# ---- C. Chronicle 인덱스 ----
def chronicle_index_list() -> List[Dict[str, Any]]:
    return _backend.list_entries()


def chronicle_index_append(
    entry_dict: Dict[str, Any],
    *,
    header_md: Optional[str] = None,
    body_md: Optional[str] = None,
    full_md: Optional[str] = None,
) -> None:
    _backend.append_entry(entry_dict, header_md=header_md, body_md=body_md, full_md=full_md)


def chronicle_index_replace_all(entries_list: List[Dict[str, Any]]) -> None:
    _backend.replace_entries(entries_list)


def chronicle_index_count(*, source: Optional[str] = None) -> int:
    return _backend.count_entries(source=source)


def chronicle_find_entry_by_date(chronicle_date: str) -> Optional[Dict[str, Any]]:
    return _backend.find_entry_by_date(chronicle_date)


def chronicle_delete_entry(entry_id: str, *, delete_report: bool = True) -> bool:
    return _backend.delete_entry(entry_id, delete_report=delete_report)


# ---- D. Chronicle 본문 ----
def chronicle_get_report(entry_id: str) -> Optional[Dict[str, Any]]:
    return _backend.get_report(entry_id)


def chronicle_save_report(
    entry_id: str,
    *,
    chronicle_date: str,
    header_md: str,
    body_md: str,
    full_md: str,
) -> None:
    _backend.save_report(
        entry_id,
        chronicle_date=chronicle_date,
        header_md=header_md,
        body_md=body_md,
        full_md=full_md,
    )


def chronicle_report_exists(entry_id: str) -> bool:
    return _backend.report_exists(entry_id)


def chronicle_report_exists_by_date(chronicle_date: str) -> bool:
    return _backend.report_exists_by_date(chronicle_date)


def chronicle_list_sections(entry_id: str) -> List[Dict[str, Any]]:
    return _backend.list_sections(entry_id)


def chronicle_find_sections_by_key(section_key: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    return _backend.find_sections_by_key(section_key, limit=limit)


def chronicle_list_md_files() -> List[Dict[str, Any]]:
    return _backend.list_md_files()


# ---- FTS5 ----
def chronicle_search_fulltext(
    query: str,
    *,
    limit: int = 10,
    section_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return _backend.search_fulltext(query, limit=limit, section_key=section_key)


def chronicle_fts_available() -> bool:
    return _backend.is_fts_available()


# ---- backfill state ----
def chronicle_get_backfill_state() -> Dict[str, Any]:
    return _backend.get_backfill_state()


def chronicle_save_backfill_state(state_dict: Dict[str, Any]) -> None:
    _backend.save_backfill_state(state_dict)
