# Data Persistence API Spec

## 모듈
- `src/storage/state_store.py` — 공개 도메인 API. 호출자는 본 모듈만 import 한다.
- `src/storage/__init__.py` — 빈 패키지.
- `src/storage/sqlite_backend.py` — A/B 도메인 SQLite 백엔드 (Phase 2).
- `src/storage/chronicle_repo.py` — C/D 도메인 Repository (Phase 3, 본 단계 신설).
- `src/storage/chronicle_sqlite_backend.py` — C/D SQLite 백엔드 (Phase 3).
- `src/storage/migrations/` — 버전별 마이그레이션 스크립트 (`v001_initial.py`, `v002_chronicle.py`).
- `src/storage/backup_scheduler.py` — 봇 내부 백업 스케줄러 진입점 (Phase 4).
- `scripts/backup_sqlite_local.py` — 백업 사이클 실행 스크립트 + 모듈(공개 함수 `run_backup_cycle`) (Phase 4 SCP/Local 정책, 본 단계 신설).
- `scripts/restore_sqlite_from_local.py` — 수동 복원 스크립트 (Phase 4 SCP/Local 정책, 본 단계 신설).
- `scripts/verify_backup_e2e.py` — Phase 4 서버 종단(E2E) 검증 스크립트 (Phase 4).
- `tests/smoke_backup_local.py` — Phase 4 SCP/Local 백업/복원 smoke 테스트 (본 단계 신설).
- (폐기) `scripts/backup_sqlite_to_github.py` / `scripts/restore_sqlite_from_github.py` / `tests/smoke_backup_to_github.py` — 초기 v1.3 GitHub 정책 시 사용. 본 PR 에서 삭제 (commit history 보존).

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

## 9. Phase 4 — 백업 / 복원 API (정책 SCP/Local, 2026-06-07 갱신)

> **정책 변경 이력**: 초기 v1.3 의 GitHub Private Repo 정책에서 사용하던 5개 키 (`BACKUP_REPO_URL` / `BACKUP_GITHUB_TOKEN` / `BACKUP_BRANCH` / `BACKUP_REPO_DIR` / `BACKUP_GIT_USER_NAME` / `BACKUP_GIT_USER_EMAIL`) 는 **모두 폐기**됨. 외부 호스팅/PAT 의존 0. 본 PR(2026-06-07) 에서 8개 키로 단순화.

### 9.1 환경변수 (Phase 4 SCP/Local 정책)
| 키 | 기본값 | 효과 |
|---|---|---|
| `BACKUP_ENABLED` | `false` | `true`/`1`/`yes` 시 봇 부팅 시 백업 스케줄러 활성. 미설정 시 백업 미실행 (Phase 1~3 회귀 0 보장) |
| `BACKUP_LOCAL_DIR` | `data/backup_local` | 백업 파일 누적 디렉터리. LightSail 로컬 경로. `.gitignore` 자동 차단 (`data/backup_local/` 패턴). |
| `BACKUP_DAILY_AT` | `18:00` | 일간 백업 시각 (KST). `HH:MM` 형식 |
| `BACKUP_WEEKLY_AT` | `sunday 22:00` | 주간 백업 요일+시각 (KST). `<weekday> HH:MM` 형식 |
| `BACKUP_MONTHLY_AT` | `01 00:30` | 월간 백업 일+시각 (KST). `DD HH:MM` 형식. 매월 해당 일자에 일간 백업을 monthly/ 로 승격 |
| `BACKUP_RETENTION_DAILY` | `30` | 일간 백업 보존 일수 |
| `BACKUP_RETENTION_WEEKLY` | `12` | 주간 백업 보존 주차 |
| `BACKUP_RETENTION_MONTHLY` | `12` | 월간 백업 보존 개월 |

총 8 키. 외부 통신/인증 키 0개.

### 9.2 봇 내부 스케줄러 진입점 (`src/storage/backup_scheduler.py`)
```python
def register_backup_jobs(scheduler, *, notify_fn=None) -> bool:
    """main.py 가 부팅 시 1회 호출. BACKUP_ENABLED=true 일 때만 jobs 등록.

    Args:
        scheduler: schedule 모듈 (또는 schedule.Scheduler 인스턴스).
        notify_fn: 슬랙 보고용 callable(text). None 이면 stdout 만.

    Returns:
        True: 백업 jobs 등록됨. False: BACKUP_ENABLED 미활성으로 skip.

    부수 효과:
        - schedule.every().day.at(BACKUP_DAILY_AT).do(_run_in_thread, kind='daily')
        - schedule.every().<weekday>.at(BACKUP_WEEKLY_AT).do(_run_in_thread, kind='weekly')
        - schedule.every().day.at(BACKUP_MONTHLY_AT).do(_run_in_thread_if_first_of_month, kind='monthly')
    """
```

스레드 래퍼:
```python
def _run_in_thread(kind: str) -> None:
    """schedule 의 메인 thread 를 차단하지 않도록 daemon thread 에서 run_backup_cycle 호출."""
    threading.Thread(
        target=_safe_run_backup,
        args=(kind,),
        daemon=True,
        name=f"backup-{kind}",
    ).start()


def _safe_run_backup(kind: str) -> None:
    """예외 안전 래퍼. 모든 예외를 슬랙 1회 보고 후 흡수 (thread 죽어도 봇 본체 영향 0)."""
    try:
        from scripts.backup_sqlite_local import run_backup_cycle
        backup_dir = os.getenv("BACKUP_LOCAL_DIR", "data/backup_local")
        result = run_backup_cycle(kind=kind, db_path=..., backup_dir=backup_dir, notify_fn=...)
    except Exception as exc:
        # B-Type Pause 알림 + traceback 전송
        ...
```

`main.py` 통합 위치 (예시):
```python
# main.py, schedule 등록 영역
from src.storage.backup_scheduler import register_backup_jobs
register_backup_jobs(schedule, notify_fn=slack_notifier.send)
```

### 9.3 백업 스크립트 (`scripts/backup_sqlite_local.py`)

#### CLI 진입점
```
$ python scripts/backup_sqlite_local.py --kind {daily,weekly,monthly} [--db-path PATH] [--backup-dir PATH] [--no-slack] [--dry-run]
```

옵션:
- `--kind`: 필수. `daily` / `weekly` / `monthly` 중 하나.
- `--db-path`: 백업 대상 DB 경로. 기본 `STATE_STORE_DB_PATH` → `data/sqlite/autostock.db`.
- `--backup-dir`: 백업 누적 디렉터리. 기본 `BACKUP_LOCAL_DIR`.
- `--no-slack`: 슬랙 보고 생략 (로컬 검증용).
- `--dry-run`: VACUUM INTO + gzip + 보관 정책 회전 시뮬레이션. 결과 .db.gz 생성 후 즉시 폐기.

#### 공개 함수 시그니처
```python
def run_backup_cycle(
    *,
    kind: Literal["daily", "weekly", "monthly"],
    db_path: str,
    backup_dir: str,
    notify_fn: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
) -> dict:
    """단일 백업 사이클을 수행한다.

    Returns:
        {
          "kind": "daily",
          "stamp": "20260606-1800",
          "src_db_path": "data/sqlite/autostock.db",
          "src_db_size": 65536,
          "vacuum_db_size": 32768,
          "gz_size": 4096,
          "gz_file_rel": "daily/autostock-20260606-1800.db.gz",
          "rotated_files_list": ["daily/autostock-20260507-1800.db.gz", ...],
          "elapsed_ms": 8432,
          "status": "ok"  # or "preflight_failed" / "vacuum_failed" / "gzip_failed" / "skip_no_daily"
        }
    """
```

흐름 (7 단계, 본 사양 §03 §13.4 와 일치 — git 의존 0):
1. **Step 1/7**: 환경변수/인자 로드. `kind` 검증. `backup_dir` 절대경로 정규화. `db_path` 존재 점검 (미존재 시 `[Backup FAIL] step=preflight` 슬랙 + early return).
2. **Step 2/7**: `BACKUP_LOCAL_DIR/{daily,weekly,monthly,staging}/` 디렉터리 보장 (`os.makedirs(exist_ok=True)`).
3. **Step 3/7**: `kind=='monthly'` 분기 → daily/ 최신 1개를 monthly/ 로 복사. 일간 미존재 시 skip + INFO. 그 외 kind 는 Step 4~5 진행.
4. **Step 4/7**: `staging/autostock-{stamp}.db` 정리 → `sqlite3 db_path "VACUUM INTO 'staging/autostock-{stamp}.db'"`. KST 타임스탬프 + 60s 1회 재시도 (P4E1).
5. **Step 5/7**: gzip 압축 → `{backup_dir}/{kind}/autostock-{stamp}.db.gz` 이동. staging 정리. dry-run 모드면 직후 결과 .gz 도 삭제.
6. **Step 6/7**: 보관 정책 회전 — `daily/` mtime 기준 30일 초과 / `weekly/` 12주 초과 / `monthly/` 12개월 초과 파일 `os.remove` (P4E4 — 회전 실패는 WARN, 백업 자체 성공으로 간주).
7. **Step 7/7**: 슬랙 보고 + 결과 dict 반환.

종료 코드:
- 0: 정상 (회전 실패는 WARN 으로 분류, exit 0 유지). `kind=='monthly'` 의 `skip_no_daily` 도 0.
- 1: VACUUM INTO 실패 (P4E1).
- 2: gzip 실패 (P4E2).
- 3: 사전 점검 실패 (P4F3-1, DB 미존재 등).

### 9.4 복원 스크립트 (`scripts/restore_sqlite_from_local.py`)

#### CLI 진입점
```
$ python scripts/restore_sqlite_from_local.py --list [--backup-dir PATH]
$ python scripts/restore_sqlite_from_local.py --latest [--kind {daily,weekly,monthly}] [--target-path PATH] [--backup-dir PATH] [--dry-run]
$ python scripts/restore_sqlite_from_local.py --stamp YYYYMMDD-HHMM --kind {daily,weekly,monthly} [--target-path PATH] [--backup-dir PATH] [--dry-run]
```

옵션:
- `--list`: 사용 가능한 백업 파일 나열 (`kind/stamp/size` 표). 다른 옵션과 배타.
- `--latest`: 가장 최신 백업으로 복원. `--kind` 미지정 시 `daily`.
- `--stamp` + `--kind`: 특정 시점 복원.
- `--target-path`: 복원 대상 DB 경로. 기본 `STATE_STORE_DB_PATH`.
- `--backup-dir`: 백업 소스 디렉터리. 기본 `BACKUP_LOCAL_DIR`.
- `--dry-run`: 압축 풀이 + integrity_check 까지만. INSTALL (`{db_path}` 덮어쓰기) 미실행.
- `--force`: 봇이 실행 중이어도 진행 (위험. 운영자 명시 책임).

#### 공개 함수 시그니처
```python
def run_restore(
    *,
    kind: Literal["daily", "weekly", "monthly"],
    stamp: Optional[str] = None,  # None 이면 latest
    target_path: str,
    backup_dir: str,
    notify_fn: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """단일 복원 사이클.

    Returns:
        {
          "kind": "daily",
          "stamp": "20260606-1800",
          "gz_size": 4096,
          "restored_db_size": 65536,
          "integrity_check": "ok",
          "backup_of_target": "data/sqlite/autostock.db.bak-20260607-0900",
          "elapsed_ms": 4231,
          "status": "ok"
        }
    """
```

흐름 (6 단계 — git fetch 단계 삭제):
1. `--list` 분기 → `BACKUP_LOCAL_DIR/{daily,weekly,monthly}/` 파일 나열 후 종료.
2. `--latest` 분기 → 해당 kind 디렉터리에서 가장 최신 stamp 자동 선택. `--stamp` 분기 → 해당 파일 존재 확인. 미존재 시 exit 1.
3. **봇 실행 점검** — `lsof` / `fuser` 또는 `wal/shm` 파일 존재. 사용 중이면 `--force` 없을 시 중단 + 안내 (P4F7-1).
4. 대상 .db.gz 압축 풀이 → `BACKUP_LOCAL_DIR/staging/restored.db`.
5. `sqlite3 staging/restored.db "PRAGMA integrity_check"` → 결과 ≠ `ok` 면 즉시 중단 (P4E5). dry-run 분기 → 검증 결과만 보고 후 종료.
6. 실제 모드: `os.rename({target_path}, {target_path}.bak-{stamp})` → `os.replace(staging/restored.db, {target_path})` (atomic). 슬랙 보고 + 결과 dict 반환.

종료 코드:
- 0: 정상 (또는 `--list` / `--dry-run` 정상).
- 1: 백업 파일 미발견.
- 2: 봇 실행 중이어서 차단 (P4F7-1).
- 3: 압축 풀이/원자적 교체 실패.
- 4: integrity_check 실패 (P4E5).

### 9.5 외부 동기화 (SCP/rsync — 운영자 PC, 본 봇 책임 외부)

본 봇은 LightSail 의 `BACKUP_LOCAL_DIR` 에 .db.gz 를 누적·회전만 수행한다. 운영자 PC 와의 동기화는 운영자가 별도 채널로 수행한다 (스케줄링/실행은 봇 책임 외부).

권장 명령 (운영자 PC, macOS/Linux):
```bash
# 1) 증분 동기화 (권장)
rsync -avz --delete ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/ \
      ~/autostock_backup/

# 2) 단순 일괄 복사 (디렉터리 통째)
scp -r ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/ ~/autostock_backup/

# 3) 단일 파일 (특정 stamp 만 가져오기)
scp ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/daily/autostock-20260606-1800.db.gz \
    ~/autostock_backup/daily/
```

옵션:
- `rsync -avz --delete`: 로컬에 LightSail 의 회전 결과(삭제) 까지 그대로 반영. 보관 정책 일관성 유지.
- 자동화: macOS `launchd` plist 또는 운영자 cron 으로 등록 가능 (본 봇 미관여).

### 9.6 슬랙 메시지 규약
백업/복원 결과는 다음 포맷으로 슬랙 채널에 전송한다 (이모지 사용 가능 — 슬랙 메시지 한정). `notify_fn` 가 None 또는 토큰/채널 미설정 시 stdout 출력만.

#### 9.6.1 백업 성공 (1줄, INFO)
```
[Backup OK] {kind} {stamp} | gz={N}KB | rotated={M} | elapsed={E}s
```
예: `[Backup OK] daily 20260606-1800 | gz=12KB | rotated=1 | elapsed=8s`

#### 9.6.2 백업 실패 (B-Type Pause, ERROR)
```
[Backup FAIL] {kind} {stamp} | step={step_name} | err={short_msg}
{traceback (최대 50줄)}
운영자 조치: {복구 안내 1줄}
```
가능한 `step_name`: `preflight` / `vacuum_into` / `gzip` (git step 분기 삭제).

#### 9.6.3 회전 WARN (P4E4)
```
[Backup WARN] {kind} {stamp} OK / rotate FAIL: {short_msg}
```
백업 자체는 성공이므로 봇 흐름 영향 없음. 다음 회차에 재시도.

#### 9.6.4 월간 승격 skip (P4T3)
```
[Backup INFO] monthly {stamp} skip — daily 백업 미존재. 다음 월간 트리거 시 재시도.
```

#### 9.6.5 복원 결과
```
[Restore OK] {kind} {stamp} -> {target_path} | size={N}KB | integrity=ok | elapsed={E}s
[Restore FAIL] step={preflight|resolve_source|gunzip|integrity_check|backup_target|install} | err={short_msg}
```

### 9.7 Phase 4 의존성 그래프 (Phase 1~3 체인 보강)
```
main.py (부팅 1회)
  └─> src.storage.backup_scheduler.register_backup_jobs(schedule, notify_fn)
         └─> schedule.every().day.at("18:00").do(_run_in_thread, kind='daily')
                └─> threading.Thread(target=_safe_run_backup) [daemon]
                       └─> scripts.backup_sqlite_local.run_backup_cycle(kind=...)
                              ├─> sqlite3 (VACUUM INTO)
                              ├─> gzip (stdlib)
                              ├─> shutil.copy / os.replace / os.remove (회전)
                              └─> notify_fn(text) [슬랙]
```

복원 경로:
```
운영자 CLI
  └─> scripts.restore_sqlite_from_local.run_restore(kind=..., stamp=..., target_path=...)
         ├─> os.path.* (파일 listing)
         ├─> subprocess (lsof/fuser 봇 실행 점검)
         ├─> gzip (stdlib)
         ├─> sqlite3 (PRAGMA integrity_check)
         └─> os.rename / os.replace (atomic)
```

외부 동기화 경로 (본 봇 외부):
```
운영자 PC (macOS)
  └─> rsync/scp ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/ \
           ~/autostock_backup/
```

### 9.8 Phase 4 호환성 보장
- 본 PR (Phase 4 SCP/Local 정책 변경) 적용 후에도 `BACKUP_ENABLED=false` 가 기본이므로 봇 운영자가 명시적으로 활성화하기 전까지 회귀 0.
- 백업 스크립트는 `STATE_STORE_BACKEND=sqlite` 일 때만 의미 있음. `drive` 모드에서는 라이브 DB 미존재로 `[Backup FAIL] step=preflight | err=DB 파일 미존재` 슬랙 + early return.
- **외부 의존 0**: PAT/외부 호스팅 의존 없음. 외부 네트워크 장애로 인한 백업 실패 분기 0.
- 정책 변경 이력: §1.4 (사양 01) + §13.12 (사양 03) + 본 §9.0 박스 + HANDOVER §1/§9 에서 소급 추적 가능.
