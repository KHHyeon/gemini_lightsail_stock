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

#### 9.8.3 Step 3 (이관 스크립트) 회귀 검증 (`scripts/migrate_drive_to_sqlite.py`, mock 기반 로컬 시뮬레이션)
- [x] `--help` 정상 출력 + argparse 인자(--db-path/--dry-run/--no-slack) 인식.
- [x] `--dry-run` → Drive 로드 + SQLite 스키마 부트스트랩 + 카운트만 출력 + exit 0. INSERT 미실행 확인.
- [x] 실제 모드(`--no-slack`) → 5 도메인 INSERT + 카운트 일치 + exit 0.
- [x] mock 데이터(`portfolio=2`, `split_orders=1`, `theme_context=0`, `scalp_session=1`, `trades=3`) 가 SQLite 에 정확히 반영됨.
- [x] `scalp_session` 의 single-row 카운트 시맨틱이 정확 (dict 의 key 수가 아닌 row 존재 여부로 1/0).
- [x] dry-run 결과의 stdout 중복 출력 제거 (Step 5/5 라벨로 1회만 출력).

#### 9.8.4 실 서버 검증 (운영자 수행 예정, Step 3 PR 적용 후)
- [ ] 운영 Drive 의 5 도메인이 실제로 로드되는지 (`--dry-run`) 확인.
- [ ] 실제 INSERT 수행 후 Drive 와 SQLite row count 일치.
- [ ] `.env` 에 `STATE_STORE_BACKEND=sqlite` 추가 후 봇 기동.
- [ ] orchestrator/risk_monitor/slack 모든 흐름 무오류 (스모크 확인 1회).

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

### 10.3 이관 스크립트의 실제 동작 (Step 3 신설)
- 파일: `scripts/migrate_drive_to_sqlite.py`.
- `STATE_STORE_BACKEND` 환경변수의 영향을 받지 않는다 (Drive 측은 `logger.load_json_from_gdrive` 직접 호출, SQLite 측은 `_SQLiteBackend` 직접 인스턴스화).
- 도메인 매트릭스에 카운트 방식(`keyed`/`list`/`single`) 정보가 포함되어, `scalp_session` 같은 single-row 도메인도 정확히 비교 가능.
- 슬랙 전송은 `_send_slack(text, notify_fn)` 단일 함수로 일원화 — `notify_fn` 가 없거나 토큰/채널 미설정 시 무동작 (stdout 출력은 별도로 `print_flush` 가 수행).

### 10.4 부트스트랩 순서 (중요)
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

## 11. Phase 3 — Chronicle SQLite 전환 동작 흐름

### 11.1 모듈 의존 그래프 (Phase 3, sqlite 백엔드 선택 시)
```
호출자 (chronicle_writer / backfill / context_retriever)
       |
       v
src.storage.state_store  (Phase 1/2 re-export)
       |
       v
src.storage.chronicle_repo  (Phase 3 신설, import 시점 분기)
       |
       +--- (STATE_STORE_BACKEND=drive) ---> _DriveChronicleBackend
       |                                            |
       |                                            v
       |                                     src.memory.drive_client.*
       |
       +--- (STATE_STORE_BACKEND=sqlite) --> _SQLiteChronicleBackend
                                                    |
                                                    v
                                             sqlite3 (stdlib, FTS5 포함)
                                                    |
                                                    v
                                             data/sqlite/autostock.db
                                             (schema v2 적용)
```

### 11.2 데이터 도메인별 백엔드 매핑 (Phase 3, sqlite 모드)
| 도메인 | 백엔드 | 저장 위치 |
|---|---|---|
| C. chronicle_entries | SQLite | `chronicle_entries` (1 row/entry) |
| D. chronicle_reports | SQLite | `chronicle_reports` (1 row/.md) |
| D-2. chronicle_report_sections | SQLite | `chronicle_report_sections` (1 row/섹션) |
| D-3. chronicle_search (FTS5) | SQLite | `chronicle_search` (1 row/섹션, body_md MATCH) |
| chronicle_backfill_state | SQLite | `chronicle_backfill_state` (단일 row) |
| Drive 임시 폴더 TTL | Drive | `MarketChronicles/temp/tech/*` (lifecycle.py, Phase 5 까지 유지) |
| OAuth 토큰 | Drive | `gdrive_oauth_token.json` (인증 인프라, Phase 5 까지 유지) |

### 11.3 SQLite 스키마 v2 (Phase 3, v002_chronicle.py)
```sql
-- C 도메인: Chronicle 인덱스
CREATE TABLE IF NOT EXISTS chronicle_entries (
    entry_id        TEXT    PRIMARY KEY,
    chronicle_date  TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    trigger_reason  TEXT    NOT NULL,
    regime          TEXT    NOT NULL,
    regime_label    TEXT,
    main_actor      TEXT,
    sentiment       TEXT,
    action_preview  TEXT    NOT NULL,
    context_tags_json  TEXT NOT NULL,
    phrases_json       TEXT,
    embedding_vector   BLOB,
    report_rel_path TEXT    NOT NULL,
    written_at      TEXT    NOT NULL,
    reindexed_at    TEXT,
    migrated_at     TEXT,
    schema_version  INTEGER NOT NULL DEFAULT 2,
    extra_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_chr_entries_date    ON chronicle_entries(chronicle_date DESC);
CREATE INDEX IF NOT EXISTS idx_chr_entries_regime  ON chronicle_entries(regime);
CREATE INDEX IF NOT EXISTS idx_chr_entries_source  ON chronicle_entries(source);

-- D 도메인: Chronicle 본문
CREATE TABLE IF NOT EXISTS chronicle_reports (
    entry_id        TEXT    PRIMARY KEY,
    chronicle_date  TEXT    NOT NULL,
    header_md       TEXT    NOT NULL,
    body_md         TEXT    NOT NULL,
    full_md         TEXT    NOT NULL,
    written_at      TEXT    NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 2,
    FOREIGN KEY (entry_id) REFERENCES chronicle_entries(entry_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chr_reports_date ON chronicle_reports(chronicle_date DESC);

-- D-2: 본문 5섹션 정규화
CREATE TABLE IF NOT EXISTS chronicle_report_sections (
    entry_id        TEXT    NOT NULL,
    section_index   INTEGER NOT NULL,
    section_key     TEXT    NOT NULL,
    section_title   TEXT    NOT NULL,
    body_md         TEXT    NOT NULL,
    PRIMARY KEY (entry_id, section_index),
    FOREIGN KEY (entry_id) REFERENCES chronicle_entries(entry_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chr_sections_key ON chronicle_report_sections(section_key);

-- D-3: 풀텍스트 검색
CREATE VIRTUAL TABLE IF NOT EXISTS chronicle_search USING fts5(
    entry_id        UNINDEXED,
    chronicle_date  UNINDEXED,
    section_key     UNINDEXED,
    body_md,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- 운영 상태
CREATE TABLE IF NOT EXISTS chronicle_backfill_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    payload_json    TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

INSERT INTO schema_version(version, applied_at, description)
VALUES (2, CURRENT_TIMESTAMP, 'Phase 3: chronicle C/D + FTS5 + sections + backfill_state');
```

설계 의도:
- **검색 키 외부화**: C 의 regime/regime_label/main_actor/sentiment 가 모두 컬럼화. context_retriever 의 8단계 점수화가 JSON parse 없이 동작 가능 (성능 ↑).
- **JSON 보존**: phrases_list/context_tags_list 는 list 형식의 자유도가 필요 + 검색 키 외부화 비용 대비 효율 낮아 JSON 유지.
- **CASCADE**: 인덱스 삭제 시 reports/sections/search 동기 정리. backfill.reset 안전성 향상.
- **FTS5 unicode61 + 한국어**: `remove_diacritics 2` 옵션으로 한글·라틴 동시 처리. (시험 후 한국어 토크나이저 별도 도입 검토 — Phase 3.5)

### 11.4 chronicle_repo 의 read/write 동작
- `chronicle_index_list()` → `SELECT * FROM chronicle_entries ORDER BY chronicle_date DESC` → v2 dict 복원 (json.loads context_tags_json/phrases_json).
- `chronicle_index_append(entry_dict, full_md=..., header_md=..., body_md=...)` → BEGIN → INSERT chronicle_entries → INSERT chronicle_reports → 파싱한 섹션 N INSERT (chronicle_report_sections + chronicle_search) → COMMIT.
- `chronicle_index_replace_all(entries_list)` → BEGIN → DELETE chronicle_entries (CASCADE) → bulk INSERT → COMMIT. **본문은 보존되지 않으므로 호출부 주의** (현재 backfill.reset 은 entries 만 갱신).
- `chronicle_search_fulltext(query, limit=10)` → `SELECT entry_id, chronicle_date, section_key, snippet(chronicle_search, 3, '<<', '>>', '...', 16) FROM chronicle_search WHERE body_md MATCH ? LIMIT ?`.
- `chronicle_get_backfill_state() / chronicle_save_backfill_state(state_dict)` → 단일 row payload_json read/write (Phase 2 의 scalp_session 패턴과 동일).

### 11.5 .md 본문 파싱 로직 (P3F5)
```python
def _parse_full_md(full_md: str) -> tuple[str, str, list[dict]]:
    """Returns (header_md, body_md, sections_list)."""
    # 1. 헤더 분리: "# Market Chronicle ..." 또는 "# Market Chronicle (Backfill) ..."
    #    첫 빈 줄까지를 header_md, 나머지를 body_md.
    # 2. body_md 를 "^## " 로 분할.
    # 3. 각 섹션의 첫 줄을 헤딩으로 추출.
    # 4. 헤딩 텍스트로 section_key 매핑.
    ...
```

`section_key` 매핑 룰 (대소문자/공백/괄호 무시):
| 헤딩 패턴 (정규화) | section_key |
|---|---|
| "intradayflow" 또는 "장중흐름" 포함 | intraday_flow |
| "사건과원인" 포함 | event_and_cause |
| "미래행동지침" 또는 "행동지침" 포함 | action_guideline |
| "한줄요약" 포함 | one_line_summary |
| 그 외 | unknown |

### 11.6 호출자 마이그레이션 매트릭스 (Phase 3 PR 적용 범위)
| 파일 | 변경 호출 수 | 비고 |
|---|---|---|
| `src/memory/chronicle_writer.py` | 3 (file_exists / write_text / append_index) → `report_exists_by_date / chronicle_index_append (atomic)` | 트랜잭션 격상 |
| `src/memory/backfill.py` | 16 (read/write_json_relative / file_exists / write_text / read_text / read_master_index / write_master_index / append_index_entry / list_files_under / delete_file_relative / delete_file_by_id) | 가장 큰 변경 |
| `src/memory/context_retriever.py` | 1 (read_master_index → chronicle_index_list) | 점수화 로직 무변경 |
| `src/memory/lifecycle.py` | 0 (Phase 3 비대상, Phase 5 에서 통째 정리) | — |
| `scripts/migrate_master_index_v2.py` | 0 (Drive 모드 호환을 위해 유지) | — |

총 20 호출 + 3 import = 23 라인 변경 (Phase 1 의 38 라인보다 적음).

### 11.7 폴백/에러 정책 (Phase 3, §9.7 보강)
- E1. **.md 헤딩 매칭 실패** → 본문은 손실 없이 `section_key=unknown` 으로 1 섹션 보존. (P3E1)
- E2. **FTS5 빌드 미지원** → 시작 시점 1회 stderr 경고. `chronicle_search_fulltext` 는 정규식 폴백 (`re.search` on `chronicle_reports.body_md`). 정확도는 떨어지지만 봇 운영 정상. (P3E2)
- E3. **.md 본문 누락** (Drive `report_rel_path` 가리키는 파일 부재): 마이그레이션 스크립트가 `skipped` 격리 + 슬랙 보고. 인덱스는 그대로 진행. (P3E3)
- E4. **FK CASCADE 사고**: `chronicle_delete_entry(entry_id, delete_report=False)` 옵션 제공. 호출부 옵션 명시.
- E5. **SQLite IO 실패**: Phase 2 §9.7 와 동일 정책. 예외 전파 → 상위에서 B-Type Pause.

### 11.8 Phase 3 검증 체크리스트
- [ ] `python -m py_compile src/storage/chronicle_repo.py src/storage/migrations/v002_chronicle.py` OK
- [ ] `python -c "from src.storage import state_store; state_store.chronicle_index_list()"` 심볼 노출
- [ ] 호출자 3 파일 lint 0건 (`chronicle_writer / backfill / context_retriever`)
- [ ] `tests/smoke_chronicle_repo.py` (Phase 3 신설): Drive/SQLite 양 모드 라운드트립 + FTS5 검색 + 섹션 정합
- [ ] grep 로 `from src.memory import drive_client` 호출 중 `read_master_index / append_index_entry / write_master_index / read_text_relative / write_text_relative / file_exists_relative / list_files_under / delete_file_relative / read_json_relative / write_json_relative` 는 `chronicle_repo` 호출로 치환됐는지 확인 (lifecycle.py + migrate_master_index_v2.py 제외)

### 11.9 마이그레이션 스크립트 동작 (Step 3 신설)
```
[Step 1/8] Drive 로드
  - master_index.json (v2 가드)
  - reports/**/*.md 재귀 (이미 entries 가 가리키는 파일만)
  - _system/backfill_state.json (선택)

[Step 2/8] SQLite 스키마 부트스트랩
  - apply_pending → [1, 2] (v001 + v002)

[Step 3/8] dry-run? → 카운트만 비교 후 종료

[Step 4/8] chronicle_entries DELETE + bulk INSERT

[Step 5/8] 각 entry 의 .md 본문 다운로드 + 파싱
  - chronicle_reports INSERT
  - chronicle_report_sections N INSERT
  - chronicle_search N INSERT

[Step 6/8] chronicle_backfill_state DELETE + INSERT (단일 row)

[Step 7/8] 카운트 비교
  - Drive entries vs SQLite chronicle_entries
  - Drive .md 갯수 vs SQLite chronicle_reports
  - SQLite chronicle_report_sections / chronicle_search row 수

[Step 8/8] 결과 출력 + 슬랙 보고
```

### 11.10 부트스트랩 순서 (Phase 2 §10.4 계승)
- chronicle_repo 도 동일하게 import 시점에 `STATE_STORE_BACKEND` 를 읽는다.
- `main.py` 의 `load_dotenv()` 가 **모든 `from src.*` 보다 먼저** 호출되어야 한다 (Phase 2 PR 에서 이미 정정됨, 추가 변경 불필요).

## 12. Phase 3 Post-Update 동기화 (Step 2/3 적용 후 갱신)
- 본 §11.6 매트릭스의 실제 변경 라인 수 확인.
- `src/storage/chronicle_repo.py` 의 공개 시그니처가 §02 API Spec §7.1 과 일치하는지 확인.
- `tests/smoke_chronicle_repo.py` 결과 (Drive/SQLite 라운드트립) 를 §11.8 에 PASS 로 기록.
- 실 서버에서 `scripts/migrate_chronicles_to_sqlite.py` 실행 후 entries / .md / sections / FTS row 카운트 기록.

## 11. M6 운영 안정성 운반대 (Runbook, Phase 2 Step 5)
### 11.1 목적/대상/주기
- **목적**: SQLite 백엔드로 전환된 봇이 운영 환경에서 정상 동작하는지 **1~3일간 검증**한다.
- **대상**: Lightsail Ubuntu (`/home/ubuntu/my_bot`, systemd unit `stockbots.service`).
- **주기**: 별도 agent 가 **1일 1회 순회**하여 결과를 슬랙 또는 stdout 으로 보고. cron 대신 agent 가 호출하는 이유는 결과 해석 및 후속 조치(롤백 판단)까지 자동화하기 위함.

### 11.2 자동 점검 도구 (`scripts/m6_stability_check.py`)
별도 agent 가 ssh 로 접속해 단일 명령 `python3 scripts/m6_stability_check.py` 로 호출한다. 모든 점검이 직렬화된 결과 객체(`{check_id, category, status, detail}`)로 반환되어 agent 가 파싱·해석 가능.

| 옵션 | 기능 |
|---|---|
| (없음) | 사람이 읽기 좋은 텍스트 출력 + 종합 PASS/FAIL/WARN |
| `--json` | JSON 직렬화 출력 (별도 agent 파싱용) |
| `--slack` | 결과를 슬랙 채널에 1회 게시 (요약 + 비-PASS 상세) |
| `--day {1,2,3}` | 일자별 집중 점검 셀렉터 (생략 시 전체) |
| `--db-path PATH` | DB 파일 경로 override (기본: `STATE_STORE_DB_PATH` → `data/sqlite/autostock.db`) |
| `--service NAME` | systemd unit 이름 override (기본: `stockbots.service`) |

#### 점검 상태(Status) 4단계
- `PASS`: 자동으로 정상 확인됨.
- `WARN`: 자동으로 단정 불가 (예: 슬랙 명령 응답 - 사람 확인 필요) 또는 경계값.
- `FAIL`: 회귀 신호. 롤백 트리거 후보.
- `SKIP`: 해당 일자(또는 환경)에서 해당 점검이 적용 대상 아님.

### 11.3 점검 매트릭스
| ID | 카테고리 | 점검 항목 | 자동화 방식 | 정상 기준 | 권장 일자 |
|---|---|---|---|---|---|
| C01 | boot | 서비스 active | `systemctl is-active stockbots.service` | `active` | 1~3 |
| C02 | boot | 메인 프로세스 PID 살아있음 | `systemctl show -p MainPID` → `/proc/{pid}` 확인 | PID > 0 & 디렉터리 존재 | 1~3 |
| C03 | boot | DB 파일 존재 + 크기 > 0 | `os.stat(db_path)` | size > 0 | 1~3 |
| C04 | boot | WAL 파일 존재 | `os.path.exists(db_path + "-wal")` | True | 1~3 |
| C05 | boot | 부팅 로그 `STATE_STORE backend=sqlite` (또는 동등) | `journalctl -u <svc> --since "10 min ago" \| rg ...` | 매칭 1+ | 1 |
| C06 | runtime | `sqlite3.OperationalError` / `STATE_STORE` 에러 없음 | `journalctl -u <svc> --since "1 hour ago" \| rg -i "OperationalError\|STATE_STORE.*ERROR"` | 매칭 0 | 1~3 |
| C07 | runtime | `[Drive Read Fallback]` 이 떠도 Chronicle 만 | 위 명령어 + `rg "Drive Read Fallback"` 의 도메인 분류 | operational 도메인 (paper_*/split_orders/theme_context/scalp_session) 0건 | 1~3 |
| C08 | runtime | 오케스트레이터 정기 사이클 통과 | `journalctl ... \| rg "orchestrator\|이상종목\|시간대"` | 최근 1시간 내 1+ | 1~3 |
| C09 | trading | 09:00 자동 시장 진입 로그 | `journalctl --since "today 08:55" \| rg "Market.*Open\|장 시작\|09:00"` | 거래일 한정 1+ | 2~3 |
| C10 | trading | portfolio 갱신 시각 | SQLite `SELECT MAX(updated_at) FROM portfolio` | 최근 24h 이내(거래일) | 2~3 |
| C11 | trading | split_orders 갱신 (해당 시) | 동일 패턴 | 24h 또는 0 row | 2~3 |
| C12 | trading | trades append (최근 5건 ts) | `SELECT ts FROM trades ORDER BY id DESC LIMIT 5` | 거래 발생 시 최근 24h 이내 | 2~3 |
| C13 | trading | theme_context / scalp_session 갱신 | 동일 패턴 | 24h 또는 0 row | 2~3 |
| C14 | backup | PRAGMA integrity_check | `conn.execute("PRAGMA integrity_check")` | `[('ok',)]` | 2~3 |
| C15 | backup | WAL 파일 < 10MB | `os.stat(db_path + "-wal").st_size` | < 10 \* 1024 \* 1024 | 1~3 |
| C16 | backup | 디스크 여유 공간 | `shutil.disk_usage('/')` | free > 1 GiB | 1~3 |
| C17 | regression | master_index.json Drive 갱신 (Chronicle 정상 R/W) | `drive_client.get_file_modified_time('master_index.json')` | 최근 24h 이내(보고일 기준) | 3 |
| C18 | regression | paper_portfolio.json Drive 더 이상 갱신 X | 동일 + mtime 비교 | mtime < SQLite 활성화 시각 | 3 |
| C19 | regression | paper_trades.json Drive 더 이상 갱신 X | 동일 | 동일 | 3 |
| C20 | regression | OAuth 만료 시 Pause 트리거 정상 | 슬랙 알림 패턴 매칭 (수동 시나리오) | WARN(자동 단정 불가) | 1~3 |

### 11.4 종합 판정 정책
- 모든 점검 결과 중 `FAIL` 이 1건이라도 있으면 **종합 결과 = FAIL** (롤백 권고).
- `FAIL` 없이 `WARN` 만 있으면 **종합 결과 = WARN** (다음 회차에 재점검).
- `FAIL`/`WARN` 모두 없으면 **종합 결과 = PASS**.
- exit code: `0`=PASS, `1`=WARN, `2`=FAIL. 별도 agent 가 exit code 만으로도 1차 판단 가능.

### 11.5 보조 통계 출력 (informational)
점검 결과와 별도로 항상 출력되는 운영 통계 (별도 agent 가 추세 분석에 사용):
- `schema_version` 적용 이력 (version, applied_at, description).
- 5 도메인 row 수.
- portfolio / split_orders / theme_context / scalp_session 의 `MAX(updated_at)`.
- trades 최근 5건 (`ts`, `ticker`).
- WAL 파일 크기.
- DB 파일 크기.
- 디스크 사용량.

### 11.6 롤백 트리거
다음 중 1개라도 만족 시 운영자는 즉시 `.env` 의 `STATE_STORE_BACKEND=sqlite` 줄을 주석 처리(또는 `=drive`) 후 `s-restart`:
- C06 (OperationalError / STATE_STORE 에러) 가 24h 내 3회 이상.
- C07 (Drive Read Fallback 의 operational 도메인 누출) 가 1회라도 발생.
- C14 (integrity_check) 결과가 `ok` 가 아님.
- C10/C12 가 정상 거래 발생일에도 24h 이상 정체.

Drive 측 데이터는 이관 후에도 그대로 보존되므로 (`Phase 5` 정리 전까지), 롤백 시 데이터 손실 없음.

### 11.7 별도 agent 운영 시나리오
1. agent 가 ssh 로 `/home/ubuntu/my_bot` 접속.
2. `python3 scripts/m6_stability_check.py --json --day {1|2|3}` 호출.
3. JSON 결과를 파싱하여 `FAIL`/`WARN` 항목과 보조 통계를 슬랙 또는 사용자에게 보고.
4. exit code 가 `2` 면 §11.6 롤백 트리거 적용 여부를 사람에게 확인 요청 (B-Type 게이트키핑).
5. 3일 무결성 통과(Day 3 PASS) 시 본 §11 의 Step 5 구현율을 `100%` 로 마킹하고, README 의 v1.1 라인을 동기화.

### 11.8 Post-Update 동기화 (Step 5 도구 신설 후, 2026-06-02)
실제 구현 시그니처를 사양과 일치시키기 위한 기록.

#### 11.8.1 부팅 로그 추가
- `src/storage/state_store.py:_resolve_backend()` 에 부팅 신호 print 1줄 추가.
  - SQLite: `[STATE_STORE] backend=sqlite db_path=<path>`
  - Drive: `[STATE_STORE] backend=drive`
- systemd 가 stdout 을 journalctl 로 캡처하므로 C05 점검이 자동 매칭 가능해진다.

#### 11.8.2 `scripts/m6_stability_check.py` 시그니처
- 진입점: `main(argv: Optional[List[str]] = None) -> int`.
- argparse 옵션: `--db-path`, `--service`, `--day`, `--json`, `--slack` (§11.2 표와 일치).
- 핵심 자료구조:
  - `RunContext` (dataclass) — `db_path`, `wal_path`, `service_name`, `day_filter`, `now_utc`, `sqlite_activation_ts`.
  - `CheckResult` (dataclass) — `check_id`, `category`, `day_scope`, `label`, `status`, `detail`, `elapsed_ms`.
- 점검 매트릭스 `_CHECK_LIST`: 20 항목 (C01~C20) 을 §11.3 표 순서 그대로 등록.
- 점검 함수 시그니처 규약:
  - `runner_kind='ctx'`: `runner(ctx) -> (status, detail)`
  - `runner_kind='conn'`: `runner(conn, ctx) -> (status, detail)`
  - 모든 점검 함수는 예외 안전 (예외 발생 시 호출부에서 `_STATUS_FAIL` 로 흡수).
- 점검 함수 → ID 매핑 (실측):
  - `_c01_service_active` (`systemctl is-active`)
  - `_c02_main_pid_alive` (`systemctl show -p MainPID` + `/proc/<pid>`)
  - `_c03_db_file_present`, `_c04_wal_file_present` (os.path.exists + getsize)
  - `_c05_boot_log_backend` (`journalctl --since 10 min ago|1 hour ago|today`)
  - `_c06_runtime_error_absent` (`journalctl --since 1 hour ago` + regex `sqlite3.OperationalError|STATE_STORE.*ERROR`)
  - `_c07_drive_fallback_scope` (`journalctl --since 24 hour ago` + `_OPERATIONAL_FILENAME_LIST` 누출 검사)
  - `_c08_orchestrator_cycle` (regex `orchestrator|이상종목|시간대|정기 사이클|MarketOrchestrator`)
  - `_c09_market_open_log` (`journalctl --since "today 08:55"` + regex `Market.*Open|장 시작|09:00|시장 진입`)
  - `_c10_portfolio_freshness`, `_c11_split_orders_freshness` (`_check_updated_freshness`, `fresh_hours=24`)
  - `_c12_trades_recent` (`SELECT ts FROM trades ORDER BY id DESC LIMIT 1`, 임계 72h)
  - `_c13_theme_scalp_freshness` (theme_context+scalp_session OR 시맨틱)
  - `_c14_integrity_check` (`PRAGMA integrity_check`)
  - `_c15_wal_size_bound` (10 MiB), `_c16_disk_free` (`shutil.disk_usage('/')` >= 1 GiB)
  - `_c17_chronicle_drive_rw`, `_c18_drive_portfolio_stale`, `_c19_drive_trades_stale` — Drive `modifiedTime` 동적 조회(`drive_client` 의 메타데이터 API 존재 시).
  - `_c20_oauth_pause_pattern` (`invalid_grant|OAuth|Pause` 패턴, WARN 한정).
- 출력 함수 3종:
  - `_render_text` (기본), `_render_json` (`--json`), `_render_slack` (`--slack` 보고용 별도 간결 포맷).
- 종합 판정 `_aggregate_status` + `_exit_code_for`:
  - `FAIL>=1` → overall FAIL → exit 2
  - `WARN>=1` (FAIL=0) → overall WARN → exit 1
  - 그 외 → overall PASS → exit 0
  - 도구 자체 예외 → exit 3 (사양 §11.2 종료 코드)
- 보조 통계 `_collect_stats`:
  - `schema_version` 적용 이력
  - 5 도메인 `rows` + `max_updated_at` (trades 제외, trades 는 `recent_trades` 별도 출력)
  - `recent_trades` (최근 5건 `ts`,`ticker`)
  - DB/WAL 파일 크기, `/` 파티션 여유/총량(GiB)
- SQLite 활성화 시각 `_resolve_sqlite_activation_ts`:
  - 우선: `schema_version.applied_at` (v1) → 다음: DB 파일 mtime.
  - C18/C19 의 "활성화 이후 Drive 갱신 발생" 판정 기준 시각.

#### 11.8.3 Windows 환경 smoke 결과 (검증 자체는 Lightsail 에서 수행)
- Windows 에서 `--json --day 1` 실행 시: `C01~C04` 정확히 `FAIL`, `C05~C08/C15/C20` 정확히 `WARN`, `C16` 만 `PASS`, exit code `2`. **점검 함수의 예외 안전성과 종합 판정 로직이 사양 §11.4 와 정확히 일치함을 확인.**
- 운영 Lightsail Ubuntu 에서 실행 시: systemd/journalctl/DB 가 모두 존재하므로 점검 도구가 의도된 결과를 자동 산출한다.

#### 11.8.4 향후 보강 후보 (Step 5 진행 중 발견 시 추가)
- C17/C18/C19 의 Drive 메타데이터 조회 API 가 `drive_client` 에 명시 노출되지 않은 경우, `_drive_modified_time` 의 메서드 검색 목록(`get_file_metadata`/`get_app_file_metadata`/`stat_app_file`/`describe_app_file`)에 실제 함수명을 추가해야 한다.
- Day 1 PASS 후 안정성이 확인되면 `--slack` 옵션을 cron 1일 1회로 등록해 사람·agent 이중 보고 체계로 격상.

