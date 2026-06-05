# Data Persistence API Spec

## 모듈
- `src/storage/state_store.py` — 공개 도메인 API. 호출자는 본 모듈만 import 한다.
- `src/storage/__init__.py` — 빈 패키지.
- `src/storage/sqlite_backend.py` — A/B 도메인 SQLite 백엔드 (Phase 2).
- `src/storage/chronicle_repo.py` — C/D 도메인 Repository (Phase 3, 본 단계 신설).
- `src/storage/migrations/` — 버전별 마이그레이션 스크립트 (`v001_initial.py`, `v002_chronicle.py`).

## 1. 공개 함수 시그니처 (Phase 1)

### A. 운영 상태
| 함수 | 시그니처 | 반환 | 비고 |
|---|---|---|---|
| portfolio | `get_portfolio() -> dict` | 비어있으면 `{}` | 백엔드에서 None 반환 시 빈 dict |
| portfolio | `save_portfolio(portfolio_dict: dict) -> None` | — | dict 가 아니면 `TypeError` |
| split_orders | `get_split_orders() -> dict` | 비어있으면 `{}` | — |
| split_orders | `save_split_orders(split_orders_dict: dict) -> None` | — | — |
| theme_context | `get_theme_context() -> dict` | 비어있으면 `{}` | — |
| theme_context | `save_theme_context(theme_dict: dict) -> None` | — | — |
| scalp_session | `get_scalp_session() -> dict \| None` | 없으면 `None` | `scalp_session_store` 의 기존 None-체크 호환 |
| scalp_session | `save_scalp_session(session_dict: dict) -> None` | — | — |

### B. 거래 이력
| 함수 | 시그니처 | 반환 | 비고 |
|---|---|---|---|
| trades | `list_trades() -> list` | 비어있으면 `[]` | append-only |
| trades | `replace_trades(trades_list: list) -> None` | — | Phase 2 에서 `append_trade(...)` 추가 예정 |

### 일괄 초기화
| 함수 | 시그니처 | 비고 |
|---|---|---|
| reset | `reset_app_data() -> None` | 4 도메인(portfolio/split_orders/theme_context/trades) 비움. `slack_interface !초기화` 전용 |

## 2. 내부 백엔드 인터페이스 (Phase 1)
```python
class _StateStoreBackend(Protocol):
    def read_json(self, filename: str, default): ...
    def write_json(self, filename: str, data) -> None: ...
```

### `_DriveBackend` (Phase 1 기본)
- `read_json` -> `src.utils.logger.load_json_from_gdrive(filename)` 위임. None 시 default 반환.
- `write_json` -> `src.utils.logger.save_json_to_gdrive(data, filename)` 위임.

### Phase 2 백엔드: `_SQLiteBackend`
- 위치: `src/storage/sqlite_backend.py`.
- 인터페이스: `_StateStoreBackend` 동일 (`read_json`/`write_json`).
- 생성자: `_SQLiteBackend(db_path: str)`.
- 책임:
  1. DB 파일 디렉터리 자동 생성 (`os.makedirs(exist_ok=True)`).
  2. `sqlite3.connect(db_path)` + PRAGMA(WAL/synchronous=NORMAL/foreign_keys=ON) 적용.
  3. `migrations.runner.apply_pending(conn, notify_fn)` 호출하여 스키마 부트스트랩.
  4. 파일명을 도메인으로 매핑하여 적절한 테이블에 SELECT/INSERT.
- 파일명 → 테이블 매핑(`_FILENAME_TABLE_MAP`):
  | 파일명 | 테이블 | shape |
  |---|---|---|
  | `paper_portfolio.json` | `portfolio` | dict: ticker → payload |
  | `split_orders.json` | `split_orders` | dict: order_id → payload |
  | `theme_context.json` | `theme_context` | dict: ticker → payload |
  | `scalp_session.json` | `scalp_session` | dict (단일 row) |
  | `paper_trades.json` | `trades` | list: payload[] |

### Phase 2 환경변수 분기 (`state_store.py` 모듈 최상단 1회 결정)
```python
import os
_BACKEND_NAME = os.getenv("STATE_STORE_BACKEND", "drive").strip().lower()
_DB_PATH = os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db")

if _BACKEND_NAME == "sqlite":
    from src.storage.sqlite_backend import _SQLiteBackend
    _backend = _SQLiteBackend(db_path=_DB_PATH)
else:
    _backend = _DriveBackend()
```

- 기본값 `"drive"` → 환경변수 미설정 시 Phase 1 동작 100% 유지.
- 알 수 없는 값(`"sqlite3"` 같은 오타) → `_DriveBackend` fallback. 모듈 로드 시 1회 stderr 경고 출력.

### Phase 2 마이그레이션 러너 (`src/storage/migrations/runner.py`)
```python
def apply_pending(conn: sqlite3.Connection, notify_fn=None) -> list[int]:
    """schema_version 에 기록되지 않은 v0NN_*.py 파일을 버전 오름차순으로 적용.

    Args:
        conn: sqlite3 connection.
        notify_fn: 적용 발생 시 호출되는 callable(text). 일반적으로 slack 전송.

    Returns:
        실제로 적용된 버전 번호 list (예: [1] 또는 []).

    예외:
        - 파일 import 실패 시 RuntimeError 로 변환.
        - up(conn) 실행 중 예외 → ROLLBACK + 예외 전파.
    """
```

각 마이그레이션 파일(`v001_initial.py`):
```python
VERSION = 1
DESCRIPTION = "A/B 도메인 5 테이블 + schema_version"

def up(conn: sqlite3.Connection) -> None:
    """스키마 생성 + 초기 schema_version row INSERT."""
```

### Phase 2 이관 스크립트 (`scripts/migrate_drive_to_sqlite.py`)
```
$ python scripts/migrate_drive_to_sqlite.py [--db-path PATH] [--dry-run] [--no-slack]
```

- `--db-path`: 기본 `data/sqlite/autostock.db`.
- `--dry-run`: SELECT 만 수행. INSERT/스키마 변경 미실행. 카운트만 출력.
- `--no-slack`: 슬랙 보고 생략 (로컬 검증용).

흐름:
1. Drive 5 도메인을 `logger.load_json_from_gdrive` 로 로드 (인증 실패 시 즉시 중단).
2. SQLite connect + `apply_pending` 으로 스키마 보장.
3. dry-run 이 아니면: 도메인별로 DELETE FROM + bulk INSERT.
4. SELECT COUNT(*) 비교 → 표 형식 출력.
5. 슬랙 보고: 도메인별 row 수 + 적용 버전 + 소요 시간.

종료 코드:
- 0: 정상 (또는 dry-run 정상).
- 1: Drive 로드 실패.
- 2: SQLite 마이그레이션 실패.
- 3: 카운트 불일치 (Drive vs SQLite, 단 dry-run 은 비교 생략).

## 3. 파일명 매핑 (Phase 1 내부 상수)
| 도메인 | 파일명 |
|---|---|
| portfolio | `paper_portfolio.json` |
| split_orders | `split_orders.json` |
| theme_context | `theme_context.json` |
| scalp_session | `scalp_session.json` |
| trades | `paper_trades.json` |

Phase 2 부터는 SQLite 테이블 매핑으로 치환되며 호출자에게는 노출되지 않는다.

## 4. 예외 정책
- 백엔드 예외(Drive 401/Pause/타임아웃 등) 는 그대로 전파한다. 호출자는 try/except 로 자체 폴백.
- 단, Drive `invalid_grant` 의 자동 Pause 진입은 기존 `drive_client._handle_oauth_expiry_if_needed` 가 처리하므로 별도 처리 불필요.
- `save_*` 함수는 dict/list 타입 검증을 수행. 타입 불일치 시 `TypeError`.

## 5. 호출 예시 (호출자 코드 차이)
### Before (Drive 직결)
```python
from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive
portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
save_json_to_gdrive(portfolio, "paper_portfolio.json")
```

### After (도메인 API)
```python
from src.storage import state_store
portfolio = state_store.get_portfolio()
state_store.save_portfolio(portfolio)
```

## 6. 호환성 보장
- 본 PR 이후에도 `src/utils/logger.py` 의 `load_json_from_gdrive` / `save_json_to_gdrive` 는 그대로 유지된다.
- 테스트 monkeypatch (`orch_mod.load_json_from_gdrive = ...`) 호환을 위해 **`orchestrator.py` 의 logger 함수 import 는 유지**한다 (사용 위치 0 이라도 보존).
- `logger.record_trade` 의 self-call 도 변경하지 않는다.

## 7. Phase 3 — Chronicle Repository API

### 7.1 chronicle_repo 공개 함수 시그니처

#### C. Chronicle 인덱스
| 함수 | 시그니처 | 반환 | 비고 |
|---|---|---|---|
| 전체 조회 | `chronicle_index_list() -> list[dict]` | v2 entries 리스트 (호환 dict 형식) | 빈 인덱스면 `[]` |
| 추가 | `chronicle_index_append(entry_dict: dict, *, full_md: str, header_md: str, body_md: str) -> None` | — | 엔트리 + 본문 + 섹션 + FTS 를 1 트랜잭션으로 atomic 저장. 호출부 단순화 |
| 일괄 교체 | `chronicle_index_replace_all(entries: list[dict]) -> None` | — | UPSERT 패턴: 사라진 entry 만 FK CASCADE 삭제, 나머지는 인덱스 row 만 갱신(본문/섹션/FTS 보존). 본문까지 정리하려면 `chronicle_delete_entry` 명시 사용 |
| 카운트 | `chronicle_index_count(*, source: Optional[str] = None) -> int` | int | `source='backfill'` 등 필터 |
| 일자 조회 | `chronicle_find_entry_by_date(chronicle_date: str) -> Optional[dict]` | dict 또는 None | 중복 작성 가드 |
| 삭제 | `chronicle_delete_entry(entry_id: str, *, delete_report: bool = True) -> bool` | True/False | FK CASCADE 로 reports/sections/search 동기 삭제 |

#### D. Chronicle 본문
| 함수 | 시그니처 | 반환 | 비고 |
|---|---|---|---|
| 본문 조회 | `chronicle_get_report(entry_id: str) -> Optional[dict]` | `{header_md, body_md, full_md, chronicle_date, written_at}` 또는 None | — |
| 본문 존재 (일자) | `chronicle_report_exists_by_date(chronicle_date: str) -> bool` | True/False | `file_exists_relative` 대체 |
| 본문 존재 (entry_id) | `chronicle_report_exists(entry_id: str) -> bool` | True/False | — |
| 섹션 조회 | `chronicle_list_sections(entry_id: str) -> list[dict]` | `[{section_index, section_key, section_title, body_md}, ...]` | 작성 순서 유지 |
| 섹션 검색 | `chronicle_find_sections_by_key(section_key: str, *, limit=10) -> list[dict]` | — | "최근 action_guideline 10개" 같은 쿼리 |
| MD 파일 목록 (호환) | `chronicle_list_md_files() -> list[dict]` | `[{entry_id, chronicle_date, full_md_size}, ...]` | `backfill.diagnose_reports / purge_leftover_*` 호환용 |

#### FTS5 풀텍스트 검색
| 함수 | 시그니처 | 반환 | 비고 |
|---|---|---|---|
| 검색 | `chronicle_search_fulltext(query: str, *, limit=10, section_key: Optional[str] = None) -> list[dict]` | `[{entry_id, chronicle_date, section_key, snippet}, ...]` | sqlite FTS5 `MATCH` + `snippet()` 활용 |
| 가용성 | `chronicle_fts_available() -> bool` | True/False | FTS5 빌드 없을 시 False (정규식 폴백 동작) |

#### Backfill 상태
| 함수 | 시그니처 | 반환 | 비고 |
|---|---|---|---|
| 조회 | `chronicle_get_backfill_state() -> dict` | 비어있으면 `{}` | `backfill._load_state` 대체 |
| 저장 | `chronicle_save_backfill_state(state: dict) -> None` | — | `backfill._save_state` 대체 |

### 7.2 state_store 의 re-export 패턴
```python
# src/storage/state_store.py 끝부분 (Phase 3 추가)
from src.storage.chronicle_repo import (
    chronicle_index_list, chronicle_index_append, chronicle_index_replace_all,
    chronicle_index_count, chronicle_find_entry_by_date, chronicle_delete_entry,
    chronicle_get_report, chronicle_report_exists_by_date, chronicle_report_exists,
    chronicle_list_sections, chronicle_find_sections_by_key, chronicle_list_md_files,
    chronicle_search_fulltext, chronicle_fts_available,
    chronicle_get_backfill_state, chronicle_save_backfill_state,
)
```

호출자는 `from src.storage import state_store` 하나만 import 하면 A/B/C/D 모두 사용 가능.

### 7.3 백엔드 분기 (chronicle_repo 내부)
```python
# src/storage/chronicle_repo.py 상단
import os
_BACKEND_NAME = os.getenv("STATE_STORE_BACKEND", "drive").strip().lower()
_DB_PATH = os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db")

if _BACKEND_NAME == "sqlite":
    from src.storage.chronicle_repo_sqlite import _SQLiteChronicleBackend
    _backend = _SQLiteChronicleBackend(db_path=_DB_PATH)
else:
    from src.storage.chronicle_repo_drive import _DriveChronicleBackend
    _backend = _DriveChronicleBackend()
```

분기 정책은 Phase 2 의 `state_store._resolve_backend()` 와 동일 (unknown 값 → Drive fallback + stderr 경고 1회).

### 7.4 v002 마이그레이션 스크립트 (스키마)
```python
# src/storage/migrations/v002_chronicle.py
VERSION = 2
DESCRIPTION = "Phase 3: chronicle C/D + FTS5 + sections + backfill_state"

def up(conn: sqlite3.Connection) -> None:
    """chronicle_entries / chronicle_reports / chronicle_report_sections /
    chronicle_search (FTS5) / chronicle_backfill_state 5 테이블 생성."""
```

`apply_pending` 이 자동 발견·적용. v001 적용된 DB 에 add-on 으로만 동작.

### 7.5 이관 스크립트 `scripts/migrate_chronicles_to_sqlite.py` (Phase 3 Step 3 신설, 실측 갱신)
```
$ python scripts/migrate_chronicles_to_sqlite.py [--db-path PATH] [--dry-run] [--no-slack] [--no-reports]
```

옵션 (실측):
- `--db-path`: 기본 `data/sqlite/autostock.db` (`STATE_STORE_DB_PATH` env 우선).
- `--dry-run`: Drive 로드 + 카운트만 출력. INSERT 미실행.
- `--no-slack`: 슬랙 보고 생략 (로컬 검증).
- `--no-reports`: 본문/섹션/FTS 갱신 생략. `chronicle_entries` 만 이관 (인덱스 신속 동기화 용).

흐름 (8 단계, 실측):
1. **Step 1/8**: `drive_client.read_master_index(allow_auto_migrate=False)` + `_system/backfill_state.json` 로드. v1 인덱스는 `DriveSchemaMismatchError` (`migrate_master_index_v2.py` 선행 실행 안내).
2. **Step 2/8**: `_SQLiteChronicleBackend` 직접 인스턴스화 (`STATE_STORE_BACKEND` 환경변수 무시) → `apply_pending` 가 v001 + v002 자동 적용 → FTS5 가용성 보고.
3. **Step 3/8**: `--dry-run` 분기 → entries / backfill_state / FTS 가용성 카운트만 출력하고 종료 (8 단계로 점프).
4. **Step 4/8**: `backend.replace_entries([])` 로 chronicle_entries 전체 비우기 (FK CASCADE → reports/sections/search 동기 정리) → entry 별 `append_entry(entry)` UPSERT (본문 없이 인덱스만 먼저 적재).
5. **Step 5/8**: entry 별 `read_text_relative(rel_path)` 로 .md 본문 다운로드 → `backend.save_report(... full_md=...)` 호출 → `parse_full_md` 가 헤더/본문/섹션 자동 분해 → `chronicle_reports / chronicle_report_sections / chronicle_search` 동기 INSERT. 본문 누락은 `skipped_list` 격리 후 계속 진행 (P3E3). 20건마다 진행 보고.
6. **Step 6/8**: `backend.save_backfill_state(state_dict)` (단일 row UPSERT). Drive 측 부재 시 스킵.
7. **Step 7/8**: 카운트 비교 표 출력:
   - `chronicle_entries`: Drive entries vs SQLite row 수 (OK/MISMATCH).
   - `chronicle_reports`: Drive entries − skipped vs SQLite row 수 (OK/MISMATCH).
   - `chronicle_report_sections` / `chronicle_search`: N:M 관계로 정보 출력만 (비교 대상 아님).
   - `chronicle_backfill_state`: Drive 1 또는 0 vs SQLite row 수.
8. **Step 8/8**: 결과 요약 + 슬랙 전송 + 종료 코드 반환.

종료 코드 (실측):
- 0: 정상 (skipped 가 있어도 카운트 일치하면 0). dry-run 정상 종료.
- 1: Drive 로드 실패 (인증/권한/네트워크/스키마 불일치).
- 2: SQLite 초기화/INSERT 실패.
- 3: 카운트 불일치 (entries 또는 reports).

**Idempotency**: 시작 시 `replace_entries([])` + UPSERT 패턴으로 N회 재실행 시 동일 최종 상태 보장.

## 8. Phase 3 예외 정책 (Phase 2 §4 보강)
- chronicle_repo 의 백엔드 예외는 그대로 전파한다.
- Drive 모드: `drive_client._handle_oauth_expiry_if_needed` 가 invalid_grant 시 자동 Pause 진입 (Phase 1/2 와 동일).
- SQLite 모드: `sqlite3.OperationalError` / FTS5 구문 오류 등은 상위로 전파.
- 본문 헤딩 매칭 실패는 예외가 아니라 `section_key=unknown` 으로 보존 (P3F5 / P3E1 정책).
