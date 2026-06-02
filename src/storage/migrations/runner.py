# -*- coding: utf-8 -*-
"""마이그레이션 러너 — vNNN_*.py 파일을 버전 오름차순으로 적용.

상세: Doc/features/data_persistence/02_data_persistence_api_spec.md (apply_pending),
      Doc/features/data_persistence/03_data_persistence_state_logic.md §9.5
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple


_MIGRATION_PACKAGE = "src.storage.migrations"
_MIGRATION_FILE_PATTERN = re.compile(r"^v(\d{3})_[a-z0-9_]+$")


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """schema_version 테이블이 없는 빈 DB 에서 최초 1회 부트스트랩."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
        """
    )


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _discover_migration_module_list() -> List[Tuple[int, str]]:
    """src.storage.migrations 하위 vNNN_*.py 파일 목록 (버전 오름차순)."""
    package = importlib.import_module(_MIGRATION_PACKAGE)
    discovered_list: List[Tuple[int, str]] = []
    for _finder, mod_name, ispkg in pkgutil.iter_modules(package.__path__):
        if ispkg:
            continue
        match = _MIGRATION_FILE_PATTERN.match(mod_name)
        if not match:
            continue
        version_num = int(match.group(1))
        full_mod_name = f"{_MIGRATION_PACKAGE}.{mod_name}"
        discovered_list.append((version_num, full_mod_name))
    discovered_list.sort(key=lambda x: x[0])
    return discovered_list


def apply_pending(
    conn: sqlite3.Connection,
    notify_fn: Optional[Callable[[str], None]] = None,
) -> List[int]:
    """schema_version 보다 큰 버전의 마이그레이션 파일을 순서대로 적용.

    Args:
        conn: 적용 대상 sqlite3 connection.
        notify_fn: 적용 발생 시 호출되는 callable(text). 일반적으로 슬랙 전송.

    Returns:
        실제로 적용된 버전 번호 list. 적용 사항이 없으면 [].

    Raises:
        RuntimeError: 마이그레이션 모듈 import 실패.
        sqlite3.DatabaseError: up(conn) 실행 실패 (ROLLBACK 처리됨).
    """
    _ensure_schema_version_table(conn)
    current = _current_version(conn)
    applied_list: List[int] = []

    for version_num, full_mod_name in _discover_migration_module_list():
        if version_num <= current:
            continue
        try:
            mod = importlib.import_module(full_mod_name)
        except Exception as exc:
            raise RuntimeError(f"마이그레이션 모듈 import 실패: {full_mod_name}: {exc}") from exc

        description = getattr(mod, "DESCRIPTION", "")
        up_fn = getattr(mod, "up", None)
        if not callable(up_fn):
            raise RuntimeError(f"마이그레이션 {full_mod_name} 에 up(conn) 함수가 없습니다")

        try:
            with conn:  # 트랜잭션 (성공 시 COMMIT, 예외 시 ROLLBACK)
                up_fn(conn)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (
                        version_num,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        description,
                    ),
                )
        except Exception:
            raise

        applied_list.append(version_num)
        if callable(notify_fn):
            try:
                notify_fn(f"[Storage] v{version_num:03d} 마이그레이션 적용 ({description})")
            except Exception:
                # notify 실패는 마이그레이션 자체의 성공을 무효화하지 않는다.
                pass

    return applied_list
