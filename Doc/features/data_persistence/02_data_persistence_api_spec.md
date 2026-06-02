# Data Persistence API Spec

## 모듈
- `src/storage/state_store.py` — 공개 도메인 API. 호출자는 본 모듈만 import 한다.
- `src/storage/__init__.py` — 빈 패키지.

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
