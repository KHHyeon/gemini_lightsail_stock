# Data Persistence State & Logic

## 1. 모듈 의존 그래프 (Phase 1)
```
호출자 (orchestrator / risk_monitor / slack_interface / backtester / ai_logic / scalp_session_store / scalp_trainer)
       |
       v
src.storage.state_store
       |
       v (Phase 1)
src.utils.logger.{load,save}_json_from_gdrive
       |
       v
src.memory.drive_client.read_app_json / write_app_json
       |
       v
Google Drive API
```

Phase 2 부터:
```
src.storage.state_store
       |
       v (env STATE_STORE_BACKEND=sqlite)
src.storage.sqlite_backend
       |
       v
sqlite3 (stdlib)
```

## 2. 백엔드 선택 로직 (Phase 1)
- Phase 1 은 분기 없이 `_DriveBackend` 단일 인스턴스를 생성한다.
- Phase 2 에서 다음과 같은 분기 도입 예정:
  ```python
  _BACKEND_NAME = os.getenv("STATE_STORE_BACKEND", "drive").strip().lower()
  if _BACKEND_NAME == "sqlite":
      _backend = _SQLiteBackend(db_path=os.getenv("STATE_STORE_DB_PATH", "data/autostock.db"))
  else:
      _backend = _DriveBackend()
  ```

## 3. 데이터 도메인별 백엔드 매핑 (Phase 1)
| 도메인 | 백엔드 | 저장 경로 |
|---|---|---|
| portfolio | Drive | `app_data/paper_portfolio.json` |
| split_orders | Drive | `app_data/split_orders.json` |
| theme_context | Drive | `app_data/theme_context.json` |
| scalp_session | Drive | `app_data/scalp_session.json` |
| trades | Drive | `app_data/paper_trades.json` |

## 4. 호출자 마이그레이션 매트릭스 (Phase 1 PR 적용 범위, 실측)
| 파일 | 변경 호출 수 |
|---|---|
| `backtester.py` | 2 (import 갱신 + read portfolio×1) |
| `src/utils/slack_interface.py` | 9 (import 갱신 + read portfolio×3 + read split×2 + write split×1 + read trades×1 + reset_app_data×1) |
| `src/execution/orchestrator.py` | 15 (import 갱신 + read portfolio×5 + read split×4 + write portfolio×1 + write split×4) |
| `src/execution/risk_monitor.py` | 5 (import 갱신 + read portfolio×1 + read split×1 + write portfolio×1 + write split×1) |
| `src/strategy/ai_logic.py` | 3 (local import 갱신 + read theme×1 + write theme×1) |
| `src/memory/scalp_session_store.py` | 4 (import 갱신 + read scalp_session + write scalp_session + read portfolio) |
| `src/utils/logger.py` | 0 (self-call 유지) |

총 38 라인 변경 (import 6 + 호출 32).

## 5. 호환성 보장 흐름
- Phase 1 적용 후에도 다음 흐름이 정상 작동해야 한다:
  - 봇 기동 -> `state_store` 백엔드 초기화 -> 기존과 동일하게 Drive 호출
  - 거래 매수/매도 -> `state_store.get_portfolio` -> dict 반환 -> 갱신 -> `state_store.save_portfolio`
  - 단타 lifecycle 전이 -> `state_store.save_scalp_session`
  - 슬랙 `!초기화` -> `state_store.reset_app_data`
- 테스트 호환성:
  - `orchestrator.load_json_from_gdrive` import 는 유지 (monkeypatch 호환 보호)
  - 단, 실제 코드에서 사용하지 않으므로 `# noqa: F401` 처리

## 6. 스키마 진화 정책 (Phase 2~3 미리보기)
### 6.1 마이그레이션 러너 (Phase 2 신설)
- `src/storage/migrations/v00N_*.py` 파일별 `VERSION`/`DESCRIPTION`/`up(conn)`/`down(conn)`.
- 봇 기동 시 `runner.apply_pending(conn, notify_fn)` 자동 호출 + 슬랙 알림.
- `schema_version` 테이블이 적용 이력 추적.

### 6.2 컬럼 진화 패턴
| 패턴 | 사례 | 안전 절차 |
|---|---|---|
| 단순 ADD COLUMN | 새 분석 점수 추가 | 1단계 마이그레이션 |
| JSON payload 흡수 | A 도메인의 부수 필드 | `payload_json` 컬럼 활용 |
| 통폐합 (4컬럼→1JSON) | regime/regime_label/main_actor/sentiment | 2단계: 신규 컬럼 + 기존 공존 -> 1~4주 후 DROP |
| 정형 분리 (JSON→컬럼) | 자주 검색되는 키 | 신규 컬럼 + backfill + 인덱스 |
| 테이블 재생성 | SQLite ALTER 제한 우회 | rename + insert + drop |

### 6.3 도메인 API 가 흡수하는 메커니즘
호출자는 `dict` 만 다루고, 백엔드는 정형/JSON 혼합 스키마를 흡수. 스키마 진화 시 호출자 0건 변경.

## 7. Phase 1 검증 체크리스트
- [x] `python -m py_compile src/storage/state_store.py` OK
- [x] `python -c "from src.storage import state_store; ..."` 심볼 노출 확인
- [x] 호출자별 lint 0건
- [x] grep 로 `load_json_from_gdrive`/`save_json_to_gdrive` 의 외부 사용 0 (logger 내부 + 테스트 monkeypatch + orchestrator noqa 만 잔존)

## 8. Post-Update 동기화 (Phase 1 적용 후)
- 본 §4 매트릭스의 실제 변경 라인 수와 일치 여부 재확인.
- `src/storage/state_store.py` 의 공개 시그니처가 §02 API Spec 과 일치 여부 재확인.
- 변동 시 본 문서를 갱신한다.

## 9. Phase 2 — SQLite 백엔드 동작 흐름
### 9.1 모듈 의존 그래프 (sqlite 백엔드 선택 시)
```
호출자 (orchestrator / risk_monitor / slack_interface / backtester / ai_logic / scalp_session_store)
       |
       v
src.storage.state_store  (모듈 로드 시 1회 분기)
       |
       v  (STATE_STORE_BACKEND=sqlite)
src.storage.sqlite_backend._SQLiteBackend
       |
       v
sqlite3 (stdlib) ← src.storage.migrations.runner.apply_pending(conn)
       |
       v
data/sqlite/autostock.db
```

### 9.2 SQLite 스키마 v1 (A/B 도메인만)
```sql
-- 메타
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT
);

-- A. 운영 상태
CREATE TABLE IF NOT EXISTS portfolio (
    ticker TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS split_orders (
    order_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS theme_context (
    ticker TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scalp_session (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- B. 거래 이력 (append-only 의미)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_uuid TEXT UNIQUE,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    extra_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
```

설계 의도:
- Phase 1 dict 인터페이스를 100% 통과시키기 위해 `payload_json` 단일 컬럼.
- 자주 검색되는 키(예: `mode_type`, `strategy_tag`) 는 Phase 3+ 에서 점진적 외부화. **2-phase migration** 패턴 사용.
- `trades.trade_uuid` 는 UNIQUE 이나 기존 데이터에 없을 수 있어 NULL 허용. Phase 2.5 에서 강제화 검토.

### 9.3 read_json 동작
- `paper_portfolio.json` → `SELECT ticker, payload_json FROM portfolio` → `{ticker: json.loads(payload), ...}` 재구성.
- `split_orders.json` → 동일 패턴 (key=order_id).
- `theme_context.json` → 동일 패턴 (key=ticker).
- `scalp_session.json` → `SELECT payload_json FROM scalp_session WHERE id=1` → dict 또는 default.
- `paper_trades.json` → `SELECT payload_json FROM trades ORDER BY ts, id` → `[json.loads(p), ...]`.

### 9.4 write_json 동작 (트랜잭션 1건)
- A 도메인(dict): `DELETE FROM <table>` → bulk `INSERT INTO <table>` → COMMIT.
- B 도메인(trades): `DELETE FROM trades` → bulk `INSERT INTO trades` → COMMIT.
- 트랜잭션 실패 시 ROLLBACK 자동.

### 9.5 마이그레이션 러너 흐름
```
1. SELECT MAX(version) FROM schema_version  (또는 0)
2. src/storage/migrations/ 하위 v0NN_*.py 파일 수집, 버전 오름차순 정렬
3. current < version 인 파일들을 순서대로:
   a. BEGIN
   b. mod.up(conn)
   c. INSERT INTO schema_version VALUES (version, NOW, mod.DESCRIPTION)
   d. COMMIT
   e. notify_fn(f"[Storage] v{version} 마이그레이션 적용") 호출
4. 반환: 적용된 version list
```

### 9.6 Drive→SQLite 이관 스크립트 동작
```
[Step 1/5] Drive 로드
  - paper_portfolio.json (예: 7 entries)
  - split_orders.json (예: 3 entries)
  - theme_context.json (예: 0 entries)
  - scalp_session.json (예: 1 entry)
  - paper_trades.json (예: 142 entries)

[Step 2/5] SQLite 스키마 부트스트랩
  - data/sqlite/autostock.db 디렉터리/파일 생성
  - apply_pending → [1] (v001_initial)

[Step 3/5] dry-run? → INSERT 건너뜀

[Step 4/5] INSERT
  - portfolio: DELETE + 7 INSERT
  - split_orders: DELETE + 3 INSERT
  - theme_context: DELETE + 0 INSERT
  - scalp_session: DELETE + 1 INSERT
  - trades: DELETE + 142 INSERT

[Step 5/5] 카운트 검증
  - portfolio:        Drive=7   SQLite=7   OK
  - split_orders:     Drive=3   SQLite=3   OK
  - theme_context:    Drive=0   SQLite=0   OK
  - scalp_session:    Drive=1   SQLite=1   OK
  - trades:           Drive=142 SQLite=142 OK

[결과] OK. 0.42s. 슬랙 보고 완료.
```

### 9.7 폴백/에러 정책 (Phase 2)
- E1. **SQLite IO 실패** (`sqlite3.OperationalError` 등): 예외 전파. 상위 호출자가 try/except 하거나 `drive_client` Pause 라인과 동일 수준에서 B-Type 처리.
- E2. **DB 파일 잠금 (locked)**: WAL 모드 + 재시도 없이 즉시 전파. 운영 중 동일 프로세스이므로 발생 확률 매우 낮음.
- E3. **마이그레이션 실패**: ROLLBACK + 예외 전파. `schema_version` 미기록 → 다음 기동 시 재시도 가능. 단 dirty state 가능성 알림.
- E4. **스키마 누락 row** (예: scalp_session 빈 테이블): `get_scalp_session()` → None 반환 (Phase 1 의미 보존).
- E5. **`STATE_STORE_BACKEND` 알 수 없는 값**: stderr 경고 1회 + Drive fallback. 의도적 misconfiguration 방어.

### 9.8 Phase 2 Step 2 회귀 검증 결과
#### 9.8.1 `tests/smoke_state_store_sqlite.py` (셸 env 주입)
- [x] `STATE_STORE_BACKEND` 미설정 → 백엔드 = `_DriveBackend` 확인. (1/4 PASS)
- [x] 알 수 없는 백엔드 값(`postgres`) → stderr 경고 + `_DriveBackend` 폴백. (2/4 PASS)
- [x] `STATE_STORE_BACKEND=sqlite` + 빈 DB → 자동 스키마 생성 + 5 도메인 read/write 라운드트립 + scalp_session UPSERT + `reset_app_data`. (3/4 PASS)
- [x] `schema_version` v1 row 가 1개 기록됨. (4/4 PASS)

#### 9.8.2 `tests/smoke_state_store_env.py` (.env 경유 + 영속성)
- [x] `.env` 의 `STATE_STORE_BACKEND=sqlite` 가 별도 프로세스에서 `_SQLiteBackend` 로 라우팅 + DB 파일 자동 생성. (1/3 PASS)
- [x] `.env` 의 `STATE_STORE_BACKEND=drive` 일 때 `_DriveBackend` 보존 + DB 파일 미생성. (2/3 PASS)
- [x] 한 프로세스에서 write → 새 프로세스에서 read → 동일 데이터 반환 (영속성). (3/3 PASS)

#### 9.8.3 Step 3 이후 검증 대상
- [ ] dry-run 이관 → INSERT 미실행 + 카운트만 출력.
- [ ] 실제 이관 → Drive 와 row count 일치.
- [ ] 봇 기동(sqlite 모드) → orchestrator/risk_monitor/slack 모든 흐름 무오류.

## 10. Post-Update 동기화 (Phase 2 Step 2 적용 후, commit 동시 갱신)
### 10.1 실제 시그니처 (Step 2 신설 코드)
- `src/storage/state_store.py`:
  - `_resolve_backend() -> _DriveBackend | _SQLiteBackend` — 환경변수 기반 1회 결정.
  - 기본 DB 경로: `_DEFAULT_DB_PATH = "data/sqlite/autostock.db"`.
- `src/storage/sqlite_backend.py:_SQLiteBackend`:
  - `__init__(db_path: str, notify_fn: Optional[Callable[[str], None]] = None)`.
  - `read_json(filename: str, default: Any) -> Any` / `write_json(filename: str, data: Any) -> None`.
  - `close() -> None` (테스트 정리용. 운영 중 호출 불필요).
  - PRAGMA: `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`.
  - `isolation_level=None`(autocommit) + 수동 `BEGIN`/`COMMIT`/`ROLLBACK` 트랜잭션 제어.
- `src/storage/migrations/runner.py`:
  - `apply_pending(conn: sqlite3.Connection, notify_fn: Optional[Callable[[str], None]] = None) -> List[int]`.
  - 파일 패턴: `v(\d{3})_[a-z0-9_]+\.py`. 버전 오름차순 적용.
  - `with conn:` 컨텍스트로 트랜잭션 자동 관리.
- `src/storage/migrations/v001_initial.py`:
  - `VERSION = 1`, `DESCRIPTION = "A/B 도메인 5 테이블 + schema_version 메타 (Phase 2 v1)"`.

### 10.2 알려진 한계 (Step 3 또는 후속 단계에서 다룸)
- `_SQLiteBackend` 의 connection 은 모듈 단일 인스턴스. 다중 프로세스 환경에서는 추가 검토 필요(현재 봇은 단일 프로세스).
- `trades` 의 `replace_trades` 는 전체 교체 시맨틱. `append_trade(...)` 는 Phase 2.5 검토.
- `logger.record_trade` 의 self-call 은 Phase 2.5 별도 PR.

### 10.3 부트스트랩 순서 (중요)
- `state_store.py` 는 **import 시점**에 `os.getenv("STATE_STORE_BACKEND")` 를 읽어 백엔드를 결정한다.
- 따라서 `main.py` 의 `load_dotenv()` 는 **다른 모든 `from src.* import ...` 보다 먼저** 호출되어야 한다. 그렇지 않으면 `.env` 의 `STATE_STORE_BACKEND` 가 무시되고 기본값 `drive` 로 폴백된다.
- 본 Step 2 PR 에서 `main.py` 의 import 순서를 다음과 같이 정정했다:
  ```python
  from dotenv import load_dotenv
  load_dotenv()                                    # ← src.* import 보다 먼저
  import os, time, threading, schedule
  from slack_bolt import App
  ...
  from src.execution.orchestrator import MarketOrchestrator
  ```
- 별도 진단/테스트 스크립트에서도 동일 원칙. 검증은 `tests/smoke_state_store_env.py` 참조.
