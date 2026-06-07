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
- `chronicle_index_replace_all(entries_list)` → BEGIN → 새 set 에서 사라진 entry_id 만 명시 DELETE (FK CASCADE) → 나머지는 INSERT OR REPLACE 로 인덱스 row 만 UPSERT → COMMIT. **본문/섹션/FTS 는 보존된다** (reindex 안전). 본문까지 정리하려면 호출부가 `chronicle_delete_entry(entry_id, delete_report=True)` 를 명시.
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

`section_key` 매핑 룰 (대소문자/공백/괄호/구두점 무시 — `_normalize_heading_key` 정규화):
| 헤딩 패턴 (정규화) | section_key |
|---|---|
| "intradayflow" / "장중흐름" 포함 | intraday_flow |
| "eventandcause" / "사건과원인" 포함 | event_and_cause |
| "actionguideline" / "미래행동지침" / "행동지침" / "최종행동" 포함 | action_guideline |
| "onelinesummary" / "한줄요약" 포함 | one_line_summary |
| 그 외 | unknown |

**구현 실측 (2026-06-02)**: 한국어 본문 4 섹션 모두 100% 정확 매핑 확인. 영문 헤딩(`Intraday Flow / Action Guideline / ...`)도 호환 매칭 (옵션). 매핑 실패 시 `section_key=unknown` 으로 본문 보존 (P3E1).

### 11.6 호출자 마이그레이션 매트릭스 (Phase 3 PR 적용 범위, 실측 갱신)
| 파일 | 변경 호출/효과 | 비고 |
|---|---|---|
| `src/memory/chronicle_writer.py` | `file_exists_relative + write_text_relative + append_index_entry` (3 호출) → `chronicle_report_exists_by_date + chronicle_index_append(full_md=...)` (2 호출) | **트랜잭션 격상**: SQLite 모드에서 인덱스/본문/섹션/FTS 단일 트랜잭션 |
| `src/memory/backfill.py` | `_load_state / _save_state / _write_chronicle_for_event / diagnose_reports / purge_leftover_backfill_reports / reset_backfill / reindex_keyphrases` 등 7 함수의 chronicle 호출 12 곳을 `state_store.chronicle_*` 로 전환 + SQLite 모드 분기 신설 (`_is_sqlite_backend()` 헬퍼) | Drive 모드 동작 100% 보존, SQLite 모드는 FK CASCADE 활용 |
| `src/memory/context_retriever.py` | `drive_client.is_ready() + read_master_index()` → `state_store.chronicle_index_list()` (1 호출) | 점수화 로직 무변경 |
| `src/storage/state_store.py` | C/D 도메인 16개 함수 re-export 추가 | `__all__` 명시 |
| `src/storage/chronicle_repo.py` (신설) | Drive/SQLite 양 백엔드 + 16 공개 API | Repository 패턴 |
| `src/storage/chronicle_sqlite_backend.py` (신설) | `_SQLiteChronicleBackend` (5 테이블 + FTS5) + `parse_full_md` 헬퍼 | UPSERT 패턴 (PK 충돌 시 FK CASCADE 미트리거) |
| `src/storage/migrations/v002_chronicle.py` (신설) | 4 테이블 + 6 인덱스 + (선택) FTS5 가상 테이블 | FTS5 가용성 자동 감지 |
| `src/memory/lifecycle.py` | 0 (Phase 3 비대상, Phase 5 에서 통째 정리) | — |
| `scripts/migrate_master_index_v2.py` | 0 (Drive 모드 호환을 위해 유지) | — |

**실측 합계**: 신설 3 파일 + 수정 4 파일 + Drive 모드 분기 헬퍼 5 곳에 `[Drive 모드 전용]` docstring 추가.

### 11.7 폴백/에러 정책 (Phase 3, §9.7 보강)
- E1. **.md 헤딩 매칭 실패** → 본문은 손실 없이 `section_key=unknown` 으로 1 섹션 보존. (P3E1)
- E2. **FTS5 빌드 미지원** → 시작 시점 1회 stderr 경고. `chronicle_search_fulltext` 는 정규식 폴백 (`re.search` on `chronicle_reports.body_md`). 정확도는 떨어지지만 봇 운영 정상. (P3E2)
- E3. **.md 본문 누락** (Drive `report_rel_path` 가리키는 파일 부재): 마이그레이션 스크립트가 `skipped` 격리 + 슬랙 보고. 인덱스는 그대로 진행. (P3E3)
- E4. **FK CASCADE 사고**: `chronicle_delete_entry(entry_id, delete_report=False)` 옵션 제공. 호출부 옵션 명시.
- E5. **SQLite IO 실패**: Phase 2 §9.7 와 동일 정책. 예외 전파 → 상위에서 B-Type Pause.

### 11.8 Phase 3 검증 체크리스트 (Step 2 실측 결과)
- [x] **py_compile**: `v002_chronicle / chronicle_sqlite_backend / chronicle_repo / state_store / chronicle_writer / context_retriever / backfill` 7 파일 PASS
- [x] **ReadLints**: 7 파일 모두 0건
- [x] **심볼 노출**: `state_store` 의 chronicle_* 16개 + A/B 도메인 11개 = **20 심볼 모두 callable** (state_store `__all__` 검증)
- [x] **Drive 모드 import**: `STATE_STORE_BACKEND` 미설정 시 `_DriveBackend / _DriveChronicleBackend` 로드 OK, FTS 가용성=False
- [x] **SQLite 모드 라운드트립** (Windows 로컬, 임시 DB):
    - append 1건 → `chronicle_index_count()=1` / `report_exists=True`
    - 섹션 분류 4/4 정확 (intraday_flow / event_and_cause / action_guideline / one_line_summary)
    - `chronicle_search_fulltext('panic')` → 1 hit (영문 토크나이저 정상)
    - `chronicle_index_replace_all(entries)` → **본문 보존 240자 (UPSERT 패턴)**, 섹션 4→4 유지
    - `chronicle_index_replace_all([])` → FK CASCADE 동작, report 동기 삭제
    - `chronicle_delete_entry(id, delete_report=True)` → True 반환, count=0, report 미존재
- [x] **잔존 호출 검증** (`drive_client.read_master_index / append_index_entry / write_master_index / read/write_text_relative / file_exists / list_files / delete_file_*`): `chronicle_repo._DriveChronicleBackend` 내부 + `backfill.py` 의 Drive 모드 분기 + `lifecycle.py` (Phase 5 비대상) + `migrate_master_index_v2.py` (Drive 호환 유지) 외 0건
- [ ] **smoke 통합 테스트** (`tests/smoke_chronicle_repo.py`): Step 3 (마이그레이션 스크립트) 와 함께 신설 — Step 2 단독에서는 본 §11.8 의 라운드트립 인라인 테스트로 대체
- [ ] **실 서버 동작**: Step 3 마이그레이션 스크립트 실행 후 `chronicle_entries / chronicle_reports / chronicle_report_sections / chronicle_search` row 수 일치 확인 (서버 별 agent)

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

## 12. Phase 3 Post-Update 동기화

### 12.1 Step 2 (코드 구현) 완료 후 갱신 — 2026-06-02 작성
- ✅ **§11.6 매트릭스**: 실제 변경 파일/호출 수로 갱신. 신설 3 + 수정 4 + Drive 모드 헬퍼 5.
- ✅ **§02 API Spec 정합**: `chronicle_repo.py` 의 공개 16개 함수 시그니처 == §02 §7.1 정의. `chronicle_index_replace_all` 의미 보강 (UPSERT 패턴, 본문 보존).
- ✅ **§11.5 section_key 매핑**: 한국어 + 영문 키워드 모두 지원하도록 구현/문서 동기화.
- ✅ **§11.8 체크리스트**: Step 2 단독 PASS 항목 6개 기록. Step 3 와 함께 검증할 잔여 2개 명시.
- ✅ **버그 수정 기록**: `INSERT OR REPLACE` → `INSERT ON CONFLICT DO UPDATE` 전환으로 PK 충돌 시 FK CASCADE 자식 row 손실 방지. `_INSERT_ENTRY_UPSERT_SQL` 상수화.
- ⏳ **Step 3 대상**: `scripts/migrate_chronicles_to_sqlite.py` 신설 + 실 서버 entries/.md/sections/FTS row 수 일치 확인 + `tests/smoke_chronicle_repo.py` 통합 테스트.

### 12.2 Step 3 (마이그레이션 스크립트 + smoke) 완료 후 갱신 — 2026-06-05 작성
- ✅ **신설 `scripts/migrate_chronicles_to_sqlite.py`** (8 단계 흐름, ~290 라인):
  - Step 1/8: `drive_client.read_master_index(allow_auto_migrate=False)` + `_system/backfill_state.json` 로드. v1 인덱스인 경우 `DriveSchemaMismatchError` 로 즉시 종료 (자동 변환은 별도 `migrate_master_index_v2.py`).
  - Step 2/8: `_SQLiteChronicleBackend` 직접 인스턴스화 → `apply_pending` 이 v001 + v002 자동 적용. FTS5 가용성 즉시 보고.
  - Step 3/8: `--dry-run` 분기 → entries / backfill_state / FTS 가용성 카운트만 출력하고 종료.
  - Step 4/8: `backend.replace_entries([])` 로 chronicle_entries 비우기 (FK CASCADE 로 reports/sections/search 동기 정리) → entry 별 `append_entry(entry)` UPSERT.
  - Step 5/8: entry 별 `_load_drive_report_md(rel_path)` → `backend.save_report(... full_md=...)` (parse_full_md 가 헤더/본문/섹션 자동 분해 + FTS 인덱싱). 본문 누락은 `skipped_list` 로 격리하고 진행 (P3E3).
  - Step 6/8: `backend.save_backfill_state(...)` (단일 row UPSERT). Drive 측 부재 시 스킵.
  - Step 7/8: 카운트 비교 표 (`chronicle_entries` Drive↔SQLite / `chronicle_reports` Drive↔SQLite-with-skipped / sections+search 정보 출력 / `chronicle_backfill_state` Drive↔SQLite).
  - Step 8/8: 슬랙 보고 + 종료 코드 (0 / 1 / 2 / 3).
- ✅ **CLI 인터페이스**: `--db-path` / `--dry-run` / `--no-slack` / `--no-reports` 4 옵션 노출, `--help` 정상 동작.
- ✅ **Idempotency**: 시작 시점 `replace_entries([])` + UPSERT 패턴으로 N회 재실행 시 동일 결과.
- ✅ **신설 `tests/smoke_chronicle_repo.py`** (7 단계 검증, ~210 라인): Phase 2 `smoke_state_store_sqlite.py` 패턴 동일. 모든 단계 PASS.
  - [1/7] 기본 백엔드 = `_DriveChronicleBackend` (Drive 모드 보존)
  - [2/7] 알 수 없는 `STATE_STORE_BACKEND` 값 → Drive 폴백
  - [3/7] SQLite 인덱스/본문/backfill_state 라운드트립
  - [4/7] 섹션 5종 분류 4/4 정확 + FTS5 검색 1 hit (`'패닉셀'`)
  - [5/7] UPSERT 본문 보존 (`md_len=290`, sections=4, replace_all 전후 동일)
  - [6/7] FK CASCADE delete_entry → 본문/섹션 동기 삭제
  - [7/7] schema_version v1 + v2 양 row 기록
- ✅ **§11.8 체크리스트 잔여 항목**: smoke 통합 테스트 항목 완료.
- ✅ **실 서버 1회 실행 결과 (2026-06-05, LightSail `/home/ubuntu/my_bot`)**:
  ```
  [Step 1/8] master_index.entries : 40건 / backfill_state.json : 있음
  [Step 2/8] SQLite 부트스트랩 OK / FTS5 가용성 : 활성
  [Step 4/8] chronicle_entries : 40건 INSERT 완료
  [Step 5/8] chronicle_reports : 40건 / sections : 160건 / search(FTS5) : 160건 / skipped : 0건
  [Step 6/8] chronicle_backfill_state : 1건 (UPSERT)
  [Step 7/8] 모든 카운트 OK (entries 40==40, reports 40==40, backfill_state 1==1)
  [Step 8/8] 성공. 소요 63.34s
  ```
  - **평균 섹션 수**: 160 / 40 = 정확히 4.0 → 5종 분류 룰이 모든 entry 에 안정 적용 (모든 .md 가 4 섹션 구조 = `intraday_flow / event_and_cause / action_guideline / one_line_summary`, `unknown` 0건).
  - **본문 누락 0건**: P3E3 격리 분기 미발동. master_index ↔ Drive reports/*.md 정합 100%.
  - **FTS5 활성** 확인 → `chronicle_search_fulltext(...)` 가 운영 환경에서 즉시 사용 가능.

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
| C08 | runtime | 오케스트레이터 정기 사이클 통과 | `journalctl ... \| rg "Screener\|News Crawler\|Orchestrator\|orchestrator\|이상종목\|발굴\|시간대"` | **최근 4시간 내 1+** (sparse 패턴 수용, §11.8.3.2 근거) | 1~3 |
| C09 | trading | 09:00 자동 시장 진입 로그 | `journalctl --since "YYYY-MM-DD 08:55:00" \| rg "Market.*Open\|장 시작\|09:00\|시장 진입\|Screener.*탐색 시작"` | 거래일 한정 1+. since 는 **KST today 의 ISO 형식**으로 명시 (`today` 자연어 금지) | 2~3 |
| C10 | trading | portfolio 갱신 시각 | SQLite `SELECT MAX(updated_at) FROM portfolio` | 최근 24h 이내(거래일) | 2~3 |
| C11 | trading | split_orders 갱신 (해당 시) | 동일 패턴 | 24h 또는 0 row | 2~3 |
| C12 | trading | trades append (최근 5건 ts) | `SELECT ts FROM trades ORDER BY id DESC LIMIT 5` | 거래 발생 시 최근 24h 이내 | 2~3 |
| C13 | trading | theme_context / scalp_session 갱신 | 동일 패턴 | 24h 또는 0 row | 2~3 |
| C14 | backup | PRAGMA integrity_check | `conn.execute("PRAGMA integrity_check")` | `[('ok',)]` | 2~3 |
| C15 | backup | WAL 파일 < 10MB | `os.stat(db_path + "-wal").st_size` | < 10 \* 1024 \* 1024 | 1~3 |
| C16 | backup | 디스크 여유 공간 | `shutil.disk_usage('/')` | free > 1 GiB | 1~3 |
| C17 | regression | master_index.json Drive 갱신 (Chronicle 정상 R/W) | `drive_client.get_relative_file_modified_time('MarketChronicles/index/master_index.json')` | 최근 24h 이내(보고일 기준) | 3 |
| C18 | regression | paper_portfolio.json Drive 더 이상 갱신 X | `drive_client.get_app_file_modified_time(...)` + mtime 비교 | mtime <= SQLite cutover 시각(+24h 유예창) | 3 |
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
  - `RunContext` (dataclass) — `db_path`, `wal_path`, `service_name`, `day_filter`, `now_utc`, `sqlite_activation_ts`, `sqlite_cutover_ts`.
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
  - `sqlite_cutover_ts`(신규)는 journalctl 의 `[STATE_STORE] backend=sqlite` 최초 부팅 로그 시각을 우선 사용.
  - C18/C19 의 Drive 정체 판정은 `sqlite_cutover_ts`(+24h 유예창) 기준으로 수행.

#### 11.8.3 Windows 환경 smoke 결과 (검증 자체는 Lightsail 에서 수행)
- Windows 에서 `--json --day 1` 실행 시: `C01~C04` 정확히 `FAIL`, `C05~C08/C15/C20` 정확히 `WARN`, `C16` 만 `PASS`, exit code `2`. **점검 함수의 예외 안전성과 종합 판정 로직이 사양 §11.4 와 정확히 일치함을 확인.**
- 운영 Lightsail Ubuntu 에서 실행 시: systemd/journalctl/DB 가 모두 존재하므로 점검 도구가 의도된 결과를 자동 산출한다.

#### 11.8.3.1 Lightsail 실서버 Day 1 실측 (2026-06-02, append-only)
| 회차 | 시각 (UTC) | overall | PASS | WARN | FAIL | C05 status | 비고 |
|---|---|---|---|---|---|---|---|
| 1 | 07:33:16 | WARN | 8 | 3 | 0 | WARN | `state_store.py` 부팅 print 미배포 (commit `74934a3` 직전) |
| 2 | 07:39:51 | WARN | 8 | 3 | 0 | WARN | `git pull` 후 `s-restart` 수행. 그러나 `Already up to date.` — `74934a3` 가 아직 origin 미반영 |
| 3 | 07:59:16 | WARN | **9** | 2 | 0 | **PASS** | `74934a3` push + 운영 서버 재배포 후. C05 매칭 라인: `python[103947]: [STATE_STORE] backend=sqlite db_path=data/sqlite/autostock.db` (부팅 후 16초) |

회차 3 의 잔여 WARN 2건:
- **C08 (오케스트레이터 사이클)**: 16:59 KST = 장 마감(15:30) +1h29m 시점이라 1시간 윈도우에서 사이클 0건. 사양 의도대로 `"장 외 시간일 수 있음"` 안내 부착. 다음 거래일 장중 점검 시 PASS 예상.
- **C20 (OAuth/Pause)**: regex 매칭 4건 (회차 1/2 는 3건). 재시작 과정의 토큰 재로드 라인이 1건 추가된 것으로 추정. 자동 단정 불가 → WARN 유지 (사양 §11.3 의도 그대로).

실시간 쓰기 누적 증거 (보조 통계):
| 시각 (UTC) | WAL bytes | `scalp_session.max_updated_at` | 점검 시각 대비 갱신 |
|---|---|---|---|
| 07:33:16 | 8,272 | 07:33:09 | 7초 전 |
| 07:39:51 | 12,392 | 07:39:43 | 8초 전 |
| 07:59:16 | 16,512 | 07:59:07 | 9초 전 |

→ 매 점검 직전 `scalp_session` 이 갱신되고 WAL 이 점증하므로, **봇이 SQLite 에 실시간 쓰기 중**임이 확정. portfolio/theme_context 의 `updated_at` 이 06:57:27 정체인 것은 장 마감 후 거래 없음의 정상 신호.

판정: **Day 1 = PASS** (회귀 신호 0건. 잔여 WARN 2건은 모두 환경/시점 의존).

#### 11.8.3.2 Lightsail 실서버 Day 2/3 실측 (2026-06-05, append-only)
68시간 44분 무중단 가동 후 동일 MainPID(`103947`) 로 두 차례 점검. 시각 04:43 UTC = **13:43 KST (금요일 장중)**.

| 일자 | 시각 (UTC) | overall | PASS | WARN | FAIL | SKIP | 비고 |
|---|---|---|---|---|---|---|---|
| Day 2 | 04:43:12 | WARN | 9 | 5 | 0 | 1 | C09 신규 WARN(도구 버그) + C12/C13 sparse + C17~C19 미수행 |
| Day 3 | 04:43:25 | WARN | 9 | 7 | 0 | 1 | Day 2 + C17/C18/C19 도구 보강 후보 표면화 |

핵심 PASS:
- **C14 PRAGMA integrity_check = ok** (활성화 +68h 시점 무결성 유지 확정)
- **C10 portfolio 갱신 4.7h 전** (06-05 00:00:15 UTC = 09:00:15 KST 장 시작 평가 동작 확인)
- C01~C07/C15/C16: 운영 본체 모든 영역 정상

신규/잔여 WARN 진단 (운영자 진단 명령 실측):

| 신호 | 원시 진단 결과 | 최종 판정 |
|---|---|---|
| **C08** 1시간 윈도우 사이클 0건 | 24h 전체 로그 = **19줄** (`08:50/10:00/11:45` 의 Screener/News Crawler). 4.7h 동안 silent. 슬랙 `!잔고` 즉시 응답 OK | **정상 sparse 동작** — 도구 윈도우/regex 보강 대상 (§11.8.4-S1) |
| **C09** journalctl rc=1 | stderr: `Failed to parse timestamp: today 08:55`. timezone = `Asia/Seoul` (UTC 가설 반증) | **도구 버그** — systemd 의 `today` 자연어 거부 → ISO 형식으로 교체 (§11.8.4-S2) |
| **C12** trades 184.4h 전 | 마지막 거래 2026-05-28 12:18:30, portfolio 1종목 유지 매도 신호 미발생 | **정상 sparse** (거래 룰상 자연스러움, 사양 임계 72h 는 보수적) |
| **C13** theme_context/scalp_session 정체 | `journalctl ... grep -E "scalp\|단타"` = **0건** (단타 모드 미활성 확정) | **정상 sparse** (단타 미활성 + ai 의사결정 없음) |
| **C17~C19** Drive 메타데이터 조회 실패 | `drive_client` 의 4 후보 메서드(`get_file_metadata` 등) 미존재 | **도구 보강 대상** (§11.8.4-S3) |
| **C20** OAuth 이벤트 없음 | Day 1 의 "N건 감지" → "이벤트 없음" 으로 전이 | **OAuth 무사 동작** — WARN 은 사양 의도 |

봇 sparse 동작 패턴 (실측 19줄 분포):
```
08:50:00  Screener '기대주_발굴' 탐색 시작
08:50:00  Screener 조건식 확인 완료
08:50:03  Screener '배당주_발굴'
08:50:10  Screener '낙폭과대_발굴'
09:00:15  (silent) portfolio 평가 → SQLite write
10:00:12  News Crawler '반도체'
11:45:01  Screener '당일_주도주_발굴'
13:45:xx  (점검 시각, 최근 1시간 윈도우 0건)
```
→ 봇은 unique 시간대(매시 정각/장 시작/장 마감 등)에만 stdout 출력하는 sparse 패턴. **봇 응답성(슬랙 `!잔고` OK) + DB 무결성(C14) + 09:00 평가 동작(C10)** 의 세 가지 직교 신호로 sparse 가 정상임을 확정.

상태 변화 (Day 1 → Day 3):
| 지표 | Day 1 (3회차) | Day 2 | Day 3 |
|---|---|---|---|
| MainPID | 103947 | 103947 | 103947 |
| WAL bytes | 16,512 | 49,472 | 49,472 |
| DB bytes | 65,536 | 65,536 | 65,536 |
| portfolio rows / updated | 1 / 2026-06-02T06:57 | 1 / 2026-06-05T00:00 | 1 / 2026-06-05T00:00 |
| trades rows | 5 | 5 | 5 |
| integrity_check | (미수행, Day 1 범위 외) | **ok** | **ok** |
| disk free GiB | 32.56 | 32.55 | 32.55 |

판정: **Day 2 = PASS, Day 3 = PASS** (회귀 신호 0건. 잔여 WARN 은 모두 도구 버그/보강 항목 또는 정상 sparse 표현).

종합: **Phase 2 SQLite 백엔드 안정성 검증 완료** — 3일 무중단 + 무결성 + 응답성 + 도메인 write 정상 + Drive 폴백 누출 0건.

#### 11.8.4 도구 보강 확정 명세 (Day 2/3 진단 근거 반영, 2026-06-05)
Day 1~3 검증으로 표면화된 점검 도구 자체의 보강 항목 3건. **운영 회귀가 아닌 도구 정확성 개선 작업**.

##### S1. C08 윈도우/regex 보강
- **변경**: `--since "1 hour ago"` → `--since "4 hour ago"`. regex 에 `Screener|News Crawler|Orchestrator|orchestrator|이상종목|발굴|시간대` 사용.
- **근거**: 봇은 unique 시간대(시간 단위)에만 로그 출력. 1시간 윈도우는 정상 sparse 동작을 회귀로 오인. 4시간은 거래일 봇의 최소 1 사이클을 보장하면서 hang 조기 감지 가능.
- **사양 §11.3 갱신 완료** (4시간 + 신규 regex).

##### S2. C09 since 형식 안전화
- **변경**: `--since "today 08:55"` → `--since "{KST_today_iso} 08:55:00"`. Python 측에서 `datetime.now(KST).strftime("%Y-%m-%d 08:55:00")` 로 정확 형식 생성.
- **근거**: systemd journalctl 의 `today` 자연어 파서가 환경에 따라 거부 (`Failed to parse timestamp`). ISO 형식은 systemd 모든 버전에서 안전.
- **사양 §11.3 갱신 완료**.

##### S3. C17~C19 drive_client 헬퍼 신설
- **변경**:
  - `src/memory/drive_client.py` 에 신규 함수:
    - `get_relative_file_modified_time(rel_path: str) -> Optional[str>`
    - `get_app_file_modified_time(filename: str) -> Optional[str]` (wrapper)
  - `scripts/m6_stability_check.py` 는 C17에서 `MarketChronicles/index/master_index.json` 상대경로 조회를 사용하고, C18/C19는 app_data wrapper를 사용.
- **근거**: `drive_client.py` 의 기존 표면(line 696 `list_files_under` 의 fields 에 `modifiedTime` 포함)은 폴더 단위 조회용이라 단일 도메인 파일 점검에는 비효율적. 작은 단일 파일 헬퍼 1개로 점검 도구가 정확히 매칭.

##### S4. C18 기준시각 보정 (활성화 vs cutover)
- **변경**:
  - C18/C19 비교 기준시각을 `schema_version(v1).applied_at` 단일값에서 `sqlite_cutover_ts` 로 승격.
  - `sqlite_cutover_ts` 는 journalctl 의 `[STATE_STORE] backend=sqlite` 최초 부팅 로그 시각(UTC)으로 추정.
  - cutover 직후 잔여 write 오탐 방지를 위해 `+24h` 유예창 허용.
- **근거**:
  - `schema_version.applied_at` 는 "스키마 생성 시각"이며 실제 Drive 쓰기 완전 중단(cutover) 시각과 다를 수 있다.
  - Day3 실측에서 `paper_portfolio.json` 이 cutover 전/직후 이력으로 남아 C18 오탐 FAIL 발생.

##### S5. (선택) 슬랙 cron 1일 1회 보고
- Day 1~3 PASS 확정 후 `cron` 또는 `systemd timer` 로 `python3 scripts/m6_stability_check.py --slack` 를 18:00 KST 일일 자동 등록 가능. 사람·agent 이중 보고 체계로 격상.
- 우선순위는 S1~S4 완료 후 별도 PR 검토.

## 13. Phase 4 — SQLite Local 백업 동작 흐름 (정책 SCP/Local, 2026-06-07 갱신)

> **정책 변경 이력**: 본 §13 은 초기 v1.3 의 GitHub Private Repo 정책에서 LightSail 로컬 디렉터리 정책으로 통째 갱신됨 (commit `7db5f52` + `5b79cf0` + `6c7f9c6` 의 GitHub 안 → 본 PR 의 SCP/Local 안). 변경 사유와 트레이드오프는 §1.4 (사양 01) + §13.12 (본 섹션 말미) 참조.

### 13.1 모듈 의존 그래프 (Phase 4, BACKUP_ENABLED=true 시)
```
main.py (부팅 시 1회)
  └─> src.storage.backup_scheduler.register_backup_jobs(schedule, notify_fn=slack)
         ├─> schedule.every().day.at(BACKUP_DAILY_AT).do(_run_in_thread, kind='daily')
         ├─> schedule.every().<weekday>.at(BACKUP_WEEKLY_AT).do(_run_in_thread, kind='weekly')
         └─> schedule.every().day.at(BACKUP_MONTHLY_AT).do(_run_in_thread_if_first, kind='monthly')

(매 트리거 시각)
schedule (메인 thread, blocking)
  └─> _run_in_thread(kind)
        └─> threading.Thread(target=_safe_run_backup, daemon=True).start()
              └─> _safe_run_backup(kind)
                    └─> scripts.backup_sqlite_local.run_backup_cycle(kind=..., db_path=..., backup_dir=..., notify_fn=...)
                          ├─> sqlite3.connect(db_path).execute("VACUUM INTO ...")
                          ├─> gzip.open(...).write(...)
                          ├─> shutil.copy / os.replace (월간 승격)
                          ├─> _rotate_files(kind, retention)  ← os.remove
                          └─> notify_fn(text)
```

> 주: git subprocess 호출 0건. 외부 네트워크/PAT 의존 0.

복원 경로 (운영자 수동):
```
운영자 (CLI / SSH)
  └─> python scripts/restore_sqlite_from_local.py --latest --kind daily
         └─> run_restore(...)
                ├─> _check_bot_not_running(target_path)  ← 안전 가드 (P4F7-1)
                ├─> gzip.open(...).read() → staging/restored.db
                ├─> sqlite3.connect(staging/restored.db).execute("PRAGMA integrity_check")
                ├─> os.rename(target_path, target_path + ".bak-{stamp}")
                └─> os.replace(staging/restored.db, target_path)  ← atomic
```

외부 동기화 경로 (본 봇 외부 — 운영자 PC):
```
운영자 PC (macOS / Linux)
  └─> rsync -avz --delete ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/my_bot/data/backup_local/ \
            ~/autostock_backup/
```

### 13.2 디렉터리/파일 명명 규약
```
data/backup_local/                           ← BACKUP_LOCAL_DIR (.gitignore 자동 차단)
├── staging/                                 ← VACUUM INTO 임시 출력 + 복원 staging
│   └── (사이클 사이에 비어있음)
├── daily/
│   ├── autostock-20260507-1800.db.gz        ← (회전됨, os.remove 후 미존재)
│   ├── autostock-20260606-1800.db.gz        ← 최근 30일 보존
│   └── ...
├── weekly/
│   ├── autostock-20260315-2200.db.gz        ← (회전됨, 미존재)
│   ├── autostock-20260607-2200.db.gz        ← 최근 12주 보존
│   └── ...
└── monthly/
    ├── autostock-20260101-1800.db.gz        ← 매월 1일 일간 백업에서 승격
    ├── autostock-20260201-1800.db.gz
    └── ...
```

타임스탬프 규칙: KST `YYYYMMDD-HHMM`. UTC 미사용 (운영자 인지 단순화).
git 메타데이터(.git, .gitignore, README.md) 미존재 — 단순 디렉터리 구조.

### 13.3 환경변수 적용 흐름
- `BACKUP_ENABLED` 미설정 (또는 `false`/`0`/`no`) → `register_backup_jobs` 가 첫 라인에서 즉시 `False` 반환. schedule 등록 0건. **Phase 1~3 회귀 0** (P4R1).
- `BACKUP_ENABLED=true` + 모든 키가 형식 정상 → schedule 등록 후 `True` 반환. 다음 트리거 시각부터 백업 사이클 동작.
- 정책 변경: 본 정책에서는 **외부 인증 키가 없으므로** 필수 키 누락 분기가 사라졌다 (`BACKUP_ENABLED` 만으로 충분). 단, `BACKUP_*_AT` 형식 오류 (예: weekday 잘못, day 1~28 범위 초과) 시 schedule 등록 차단 + 슬랙 ERROR 1회 보고 + `False` 반환.
- 환경변수는 모듈 import 시점이 아닌 `register_backup_jobs` 호출 시점에 1회 읽는다. 봇 재기동 시 갱신 가능.

### 13.4 단일 백업 사이클 동작 (`run_backup_cycle`, 7단계 상세)
다음은 일간 백업(`kind='daily'`) 기준. 주간도 동일 흐름이며 월간은 §13.5 의 승격 분기를 따른다.

```
[Step 1/7] 환경변수/인자 로드 + KST 타임스탬프 + 사전 점검
  - now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
  - stamp = now_kst.strftime("%Y%m%d-%H%M")  → "20260606-1800"
  - kind = 'daily' | 'weekly' | 'monthly'
  - db_path = "data/sqlite/autostock.db"
  - backup_dir = "data/backup_local"
  - retention = {'daily': 30, 'weekly': 12, 'monthly': 12}[kind]
  - if not os.path.exists(db_path):
        notify_fn("[Backup FAIL] {kind} {stamp} | step=preflight | err=DB 파일 미존재: ...")
        return {status: "preflight_failed"}

[Step 2/7] 작업 디렉터리 보장
  for sub in ('staging', 'daily', 'weekly', 'monthly'):
      os.makedirs(os.path.join(backup_dir, sub), exist_ok=True)

[Step 3/7] (kind == 'monthly' 분기) → §13.5 의 승격 흐름. 그 외 kind 는 Step 4 진행.

[Step 4/7] VACUUM INTO (라이브 DB 의 일관된 스냅샷 생성)
  staging_path = backup_dir + "/staging/autostock-" + stamp + ".db"
  if os.path.exists(staging_path): os.remove(staging_path)
  try:
      sqlite3.connect(db_path).execute(f"VACUUM INTO '{staging_path}'")
  except sqlite3.OperationalError:
      time.sleep(60)
      sqlite3.connect(db_path).execute(f"VACUUM INTO '{staging_path}'")  # 1회 재시도
  ← WAL/SHM 자동 통합. write transaction 차단 < 100ms. read 영향 0.

[Step 5/7] gzip 압축 + 이동
  gz_path = backup_dir + "/" + kind + "/autostock-" + stamp + ".db.gz"
  with open(staging_path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
      shutil.copyfileobj(src, dst)
  os.remove(staging_path)
  if dry_run:
      os.remove(gz_path)  ← dry-run 은 결과물도 즉시 폐기
      → 결과 dict 반환 (회전 시뮬레이션은 Step 6 에서 수행 후 즉시 폐기)
  ← compresslevel=6: 균형(속도/비율). 9 는 느려서 미채택.

[Step 6/7] 보관 정책 회전 (rotate)
  rotated_list = []
  cutoff = _retention_cutoff(kind, now_kst)
  for f in sorted(os.listdir(backup_dir + "/" + kind)):
      if _parse_stamp_to_kst(f) < cutoff:
          os.remove(backup_dir + "/" + kind + "/" + f)  ← git rm 대신 단순 os.remove
          rotated_list.append(kind + "/" + f)

[Step 7/7] 결과 dict 반환 + 슬랙 보고
  notify_fn(f"[Backup OK] {kind} {stamp} | gz={gz_size//1024}KB | rotated={len(rotated_list)} | elapsed={ms//1000}s")
  return {kind, stamp, gz_size, gz_file_rel, rotated_files_list, elapsed_ms, status="ok"}
```

### 13.5 월간 승격 로직 (`kind='monthly'` 특수 처리)
월간 백업은 새로 VACUUM INTO 하지 않고 **일간 백업 1개를 monthly/ 로 복사**한다. 사유: 같은 시각에 두 번 VACUUM 비효율 + DB 정합성 동일 보장.

```
[Step 3/7 분기] 월간 승격
  daily_dir = backup_dir + "/daily"
  daily_files = sorted(os.listdir(daily_dir))  # 가장 최근 stamp 가 마지막
  if not daily_files:
      slack INFO ("[Backup INFO] monthly {stamp} skip — daily 백업 미존재. 다음 월간 트리거 시 재시도.")
      return {status: "skip_no_daily"}
  source = daily_files[-1]
  target = backup_dir + "/monthly/autostock-" + stamp + ".db.gz"
  shutil.copy(daily_dir + "/" + source, target)
  → Step 6 (회전) 으로 점프. Step 4~5 (VACUUM/gzip) 미실행.
```

매월 1일 00:30 KST 트리거 시 직전 18:00 일간 백업이 존재해야 함. 첫 달 운영 시 누락 가능 — INFO 로그.

### 13.6 보관 정책 회전 알고리즘 (P4F5)
| kind | 보존 기간 | 회전 기준 |
|---|---|---|
| daily | 30일 | `_parse_stamp_to_kst(filename)` < `now_kst - timedelta(days=30)` |
| weekly | 12주 | `< now_kst - timedelta(weeks=12)` |
| monthly | 12개월 | `< now_kst - timedelta(days=12*31)` |

회전은 **백업 사이클 Step 6/7** 에서 수행. 회전은 단순 `os.remove` 이며 git rm/commit 미사용 (정책 변경). 회전 실패는 백업 자체의 성공 여부에 영향 없음 (P4E4 → WARN).

### 13.7 복원 절차 흐름 (`run_restore`, 6단계)
```
[Step 1/6] --list 분기 → BACKUP_LOCAL_DIR/{daily,weekly,monthly}/ 파일 나열 + 종료
  for kind_dir in ['daily', 'weekly', 'monthly']:
      print("=== {kind_dir} ===")
      for f in sorted(os.listdir(backup_dir + "/" + kind_dir)):
          size = os.path.getsize(...)
          print(f"  {f}  {size}B")
  return

[Step 2/6] --latest 또는 --stamp 분기로 source 결정
  if stamp is None:  # --latest
      files = sorted(os.listdir(backup_dir + "/" + kind))
      if not files:
          exit(1)
      source = files[-1]
  else:
      source = "autostock-" + stamp + ".db.gz"
      if not os.path.exists(backup_dir + "/" + kind + "/" + source):
          exit(1)

[Step 3/6] 봇 실행 점검 (안전 가드, P4F7-1)
  if not force:
      if _is_db_in_use(target_path):  # lsof / fuser / wal+shm 폴백
          print("[ERROR] 봇이 실행 중일 가능성. 먼저 s-stop 후 재시도. (--force 옵션 가능)")
          exit(2)

[Step 4/6] 압축 풀이 → BACKUP_LOCAL_DIR/staging/restored.db
  staging_db = backup_dir + "/staging/restored.db"
  with gzip.open(backup_dir + "/" + kind + "/" + source, "rb") as src, open(staging_db, "wb") as dst:
      shutil.copyfileobj(src, dst)

[Step 5/6] integrity_check (P4E5)
  conn = sqlite3.connect(staging_db)
  result = conn.execute("PRAGMA integrity_check").fetchall()
  if result != [("ok",)]:
      os.remove(staging_db)
      print(f"[ERROR] integrity_check FAIL: {result}")
      exit(4)
  if dry_run:
      print "[Restore DRY-RUN OK]"
      os.remove(staging_db)
      return

[Step 6/6] 원자적 교체 + 슬랙 보고 + dict 반환
  bak_path = target_path + ".bak-" + now_kst.strftime("%Y%m%d-%H%M")
  if os.path.exists(target_path):
      os.rename(target_path, bak_path)  # 안전 백업
  try:
      os.replace(staging_db, target_path)  # atomic on POSIX
  except OSError:
      os.rename(bak_path, target_path)  # 자동 롤백
      exit(3)
  notify_fn(f"[Restore OK] {kind} {stamp} -> {target_path} | size={N}KB | integrity=ok | elapsed={E}s")
  return {kind, stamp, gz_size, restored_db_size, integrity_check, backup_of_target, elapsed_ms, status="ok"}
```

> 정책 변경 차이: 초기 v1.3 의 8단계(`git fetch` + `git reset --hard` 가 Step 1.5 였음)에서 git 의존성이 사라져 6단계로 단순화. 외부 통신 단계 0.

### 13.8 폴백/에러 정책 (Phase 1~3 §9.7/§11.7 보강, SCP/Local 정책 갱신)
- **P4E1. VACUUM INTO 실패** (`sqlite3.OperationalError: database is locked` / disk full):
  - 60초 sleep → 1회 재시도.
  - 재시도 실패 시: staging 파일 정리 + 슬랙 ERROR + B-Type Pause 안내 + exit 1.
- **P4E2. gzip 실패** (디스크 부족):
  - staging .db 파일 자동 정리 + 슬랙 ERROR + exit 2. 후속 회차에서 재시도.
- **P4E3. (미사용)** GitHub 정책 폐기로 git push 에러 분기 삭제. 본 정책에서는 외부 네트워크 의존 0.
- **P4E4. 보관 정책 회전 실패** (`os.remove` 권한/잠금 등):
  - 백업 자체는 성공 (`status="ok"` 그대로 유지) + WARN 슬랙 1회 보고. 다음 회차에 재시도.
- **P4E5. 복원 시 integrity_check 실패**:
  - 압축 풀이된 staging .db 즉시 폐기 + `.bak` 자동 복원 + exit 4.
  - 운영자에게 백업 파일 손상 안내 + 다른 시점 백업으로 재시도 권고.
- **P4E6. 백업 thread 예외**:
  - `daemon=True` 이므로 봇 본체 영향 0. 슬랙 1회 보고 후 다음 schedule tick 에서 재시도.

모든 에러는 Phase 2/3 의 **B-Type 정책** (`system_architecture.md §42-46`) 과 일관: 사용자 개입 필요 시 Pause + Slack 안내 + 운영자가 조치 후 슬랙 `완료` 입력으로 재개.

### 13.9 Phase 4 검증 체크리스트 (정책 SCP/Local, 본 PR 실측 — 2026-06-07 갱신)
- [x] **py_compile**: `backup_scheduler.py / backup_sqlite_local.py / restore_sqlite_from_local.py / verify_backup_e2e.py / smoke_backup_local.py` 5 파일 PASS.
- [x] **ReadLints**: 5 파일 + `main.py` 0건.
- [x] **smoke `tests/smoke_backup_local.py`** (16 PASS / 0 FAIL, elapsed ≈ 0.03s):
  - [x] BACKUP_ENABLED=false → register_backup_jobs 가 schedule 등록 0건 + return False.
  - [x] BACKUP_ENABLED=true + 8 키 정상 → register_backup_jobs 가 schedule 3 jobs 등록 + return True.
  - [x] weekday 매핑 검증: jobs 의 weekday 속성이 `{day, sunday}` 로 정확히 분포 (day 2건 + sunday 1건).
  - [x] run_backup_cycle(kind='daily', dry_run=True) → VACUUM + gzip 후 결과물 즉시 폐기. daily/ 비어있음.
  - [x] run_backup_cycle(kind='daily') 실 실행 → daily/{stamp}.db.gz 1건 생성. gz_size > 0.
  - [x] result.gz_size 와 실제 파일 사이즈 일치.
  - [x] 회전 알고리즘 — seed 31일 전 stamp 1개 + 30일 이내 4개 + 신규 1개 → 31일 전 1개만 회전(`os.remove`), 5개 잔존.
  - [x] run_backup_cycle(kind='monthly') 승격: daily 1개 → monthly/ 복사 (VACUUM 미실행).
  - [x] run_backup_cycle(kind='monthly') 일간 미존재 시 skip + status=skip_no_daily.
  - [x] run_restore --list (`_list_all_backups`) 가 daily/weekly/monthly 카운트 정확.
  - [x] run_restore(--latest --dry-run) → integrity_check=ok + target 미생성.
  - [x] run_restore(--latest, force=True) 실 실행 → target 생성 + integrity_check=ok + status=ok + 복원 DB 가 원본 과 동일 (cycle 무손실).
  - [x] DB 미존재 사전 점검 → status=preflight_failed (P4F3-1).
- [x] **verify_backup_e2e.py 로컬 graceful**: 로컬 PC (BACKUP_ENABLED 미설정 + DB 없음) → [1/7] 사전조건 FAIL → exit 2 (B-Type 보고) graceful 종료 확인.
- [x] **부트스트랩 통합**: `main.py` 의 schedule 등록 영역에 `register_backup_jobs(schedule, notify_fn=orchestrator.send_slack)` 1 블록 (정책 변경 후 동일, main.py 수정 0).
  - 활성 시: `[BACKUP] backup jobs registered: daily=18:00, weekly=sunday 22:00, monthly=day01 00:30`
  - 비활성 시: `[BACKUP] disabled (BACKUP_ENABLED=false)`
- [ ] **실 서버 1회 백업 성공**: LightSail 에서 `python scripts/backup_sqlite_local.py --kind daily` 1회 실행 후 `data/backup_local/daily/` 에 .db.gz 1건 + 슬랙 `[Backup OK]` 수신. (**Step 2' 운영자 작업**)
- [ ] **운영자 PC rsync 1회**: 운영자 macOS 에서 `rsync -avz --delete ubuntu@<LIGHTSAIL>:/home/ubuntu/my_bot/data/backup_local/ ~/autostock_backup/` 1회 + 결과 확인. (**Step 2' 운영자 작업**)
- [ ] **복원 시뮬레이션 1회**: 운영자 PC 에서 다운받은 .db.gz 로 임시 경로 복원 → integrity_check ok. (**Step 2' 운영자 작업**)
- [ ] **1주 운영 안정**: 일간 백업 7회 + 주간 백업 1회 모두 성공 슬랙 수신. (**Step 2' 운영자 작업**)
- [ ] **(권장) 서버 E2E 1-shot 검증**: LightSail 에서 `python scripts/verify_backup_e2e.py` 1회 실행 → 위 실 백업 + 복원 시뮬레이션을 자동 묶음 검증 (§13.13 참조). (**Step 2' 운영자 작업**)

### 13.10 Phase 4 부트스트랩 순서 (Phase 2 §10.4 / Phase 3 §11.10 계승)
- `backup_scheduler.register_backup_jobs` 는 **봇 부팅 시 1회만 호출**되고, 이후 `schedule` 가 트리거 시각마다 자동 실행한다.
- `register_backup_jobs` 호출 시점에서 `BACKUP_ENABLED` / `BACKUP_LOCAL_DIR` / `BACKUP_*_AT` 등을 1회 읽는다.
- 따라서 `main.py` 의 `load_dotenv()` 가 `register_backup_jobs` 호출 라인보다 먼저 호출되어야 한다 (이미 Phase 2 PR 에서 정정됨).

### 13.11 Phase 4 회귀 차단 (P4R1~7 검증, SCP/Local 정책)
- **R1**: 기본값 `BACKUP_ENABLED=false` → 봇 부팅 시 schedule 등록 0건. Phase 1~3 동작 100% 동일.
- **R2**: 백업 thread 가 SQLite write transaction 을 갖지 않음 (`VACUUM INTO` 는 read snapshot). 봇 거래/Chronicle 흐름에 lock contention 없음.
- **R3**: 복원 스크립트의 `_is_db_in_use` 가드 (P4F7-1) 가 라이브 DB 덮어쓰기 사고 차단 (lsof / fuser / wal+shm 폴백, `--force` 미지정 시).
- **R4**: 회전은 단순 `os.remove` (정책 변경, 이전 `git rm` + commit 폐기). 회전 이력은 슬랙 로그(`rotated={N}`) 로만 추적.
- **R5**: `BACKUP_LOCAL_DIR=data/backup_local/` 는 .gitignore 에 자동 차단되어 봇 본체 repo 의 `git add` 에 절대 포함되지 않는다. .db.gz 가 main 브랜치로 누출되는 사고 0.
- **R6**: 정책 변경으로 `GIT_CEILING_DIRECTORIES` 가드 불필요. 본 정책에서는 git subprocess 호출 0 → 봇 본체 repo 오염 위험 0 (origin 차단). 단, 정책 변경 이력은 본 §13 + §1.4 에서 고지.
- **R7**: 외부 호스팅 의존 0. PAT 만료 / 외부 권한 차단 / 외부 네트워크 장애 등 외부 요인에 의한 백업 실패 분기 없음. 봇 측 백업 사이클은 LightSail 디스크 IO 만 의존.

### 13.12 정책 변경 (GitHub → SCP/Local) 이력 — 2026-06-07 작성
- **변경 사유**:
  - 외부 호스팅(GitHub Private Repo) 의존 회피: PAT 만료/Repo 쿼터/외부 네트워크 장애 등 외부 요인 제거.
  - 단일 책임 원칙: 봇 = 백업 파일 생성 + 회전, 외부 동기화 = 별도 SCP/rsync 채널 (운영자 PC).
  - 코드 단순화: git subprocess 일체 제거 → 백업 사이클 10단계 → 7단계, 복원 8단계 → 6단계.
  - 보안 강화: PAT/외부 인증 키 0개 → .env 키 13종 → 8종.
  - 회귀 안전: `GIT_CEILING_DIRECTORIES` 가드 불필요 (R6 단순화).
- **트레이드오프**:
  - 단점: 외부 재해(LightSail + 운영자 PC 동시 손실) 시 백업 동시 사망. 운영자 PC 가 꺼져있으면 외부 미러 정체 (rsync 채널 분리 필수).
  - 보완: rsync 채널을 launchd/cron 으로 자동화 권장 (사양 §02 §9.5).
- **신설 3 파일**:
  - `src/storage/backup_scheduler.py` (수정): import 모듈을 `scripts.backup_sqlite_to_github` → `scripts.backup_sqlite_local` 로 변경. 필수 키 검증 5종 → 0종 (`BACKUP_ENABLED` 만 점검). 환경변수 `BACKUP_REPO_DIR` → `BACKUP_LOCAL_DIR` 로 변경.
  - `scripts/backup_sqlite_local.py` (~360 라인): `run_backup_cycle(*, kind, db_path, backup_dir, notify_fn=None, dry_run=False) -> dict` + 7단계 흐름 + CLI 진입점 + helper (`_kst_now / _format_kst_stamp / _vacuum_into / _gzip_file / _rotate_files / _promote_monthly_from_daily`). git/PAT 헬퍼 일체 제거.
  - `scripts/restore_sqlite_from_local.py` (~270 라인): `run_restore(...)` + 6단계 흐름 + CLI 진입점 + 봇 실행 점검 (`_is_db_in_use` lsof/fuser/wal+shm 폴백) + DRY 원칙으로 `backup_sqlite_local` 의 helper 재사용.
  - `tests/smoke_backup_local.py` (~340 라인): 12 항목 검증 + 자체 `_StubScheduler` (로컬 schedule 미설치 환경 대응). 외부 통신 0.
- **삭제 3 파일** (commit history 보존):
  - `scripts/backup_sqlite_to_github.py` / `scripts/restore_sqlite_from_github.py` / `tests/smoke_backup_to_github.py`.
- **재작성 1 파일**: `scripts/verify_backup_e2e.py` — SCP/Local 정책 기준 E2E 검증으로 재작성 (§13.13 참조).
- **수정 1 파일**: `.gitignore` — `data/backup_repo/` 제거 + `data/backup_local/` 추가, `*.db.gz` 유지, `data/.smoke_workspace/` 유지.
- **시그니처/상수 실측**:
  - 환경변수 정확히 §02 §9.1 의 8종 표 와 일치. `BACKUP_DAILY_AT` 기본 `18:00`, `BACKUP_WEEKLY_AT` 기본 `sunday 22:00`, `BACKUP_MONTHLY_AT` 기본 `01 00:30` (1~28일만 허용).
  - 타임스탬프 형식: `YYYYMMDD-HHMM` KST. `_format_kst_stamp(dt)`.
  - 회전 cutoff 단순화: `daily=days(30) / weekly=weeks(12) / monthly=days(months*31)`. relativedelta 외부 의존성 회피 (P4N1).
- **슬랙 메시지 실측 포맷** (`§02 §9.6` 와 일치):
  - 성공: `[Backup OK] daily 20260606-1800 | gz=12KB | rotated=1 | elapsed=8s`
  - 실패: `[Backup FAIL] daily 20260606-1800 | step={preflight|vacuum_into|gzip} | err=...`
  - 회전 WARN: `[Backup WARN] daily 20260606-1800 OK / rotate FAIL — 백업 자체는 성공. 다음 회차 재시도.`
  - 월간 skip: `[Backup INFO] monthly 20260601-0030 skip — daily 백업 미존재. 다음 월간 트리거 시 재시도.`
  - 복원: `[Restore OK] daily 20260606-1800 -> /path | size=N KB | integrity=ok | elapsed=Xs`

### 13.13 Step 2' 서버 종단(E2E) 검증 스크립트 — SCP/Local 정책 갱신
- **목적**: `tests/smoke_backup_local.py` 가 임시 디렉터리로만 검증하는 한계를 보완. 운영 서버(LightSail)에서 **실제 라이브 DB + 실제 `BACKUP_LOCAL_DIR`** 로 Step 2' 의 6단계 운영자 검증을 단일 명령으로 자동화한다.
- **재작성 파일**: `scripts/verify_backup_e2e.py` (~360 라인, 이전 GitHub 8단계 → SCP/Local 7단계). `backup_sqlite_local` / `restore_sqlite_from_local` 의 공개 함수·헬퍼를 DRY 로 재사용.
- **안전 정책 (P4R 계승)**:
  - 라이브 DB(`STATE_STORE_DB_PATH`)는 **절대 변경하지 않는다**. 복원 대상은 항상 `tempfile.mkdtemp()` 하위 임시 경로.
  - 백업 디렉터리도 운영 봇의 `BACKUP_LOCAL_DIR` 와 분리된 임시 디렉터리를 사용하여 동시 실행 중인 봇과 충돌 없음(R5 강화).
- **검증 7단계**:
  1. 사전조건: `BACKUP_ENABLED=true` + 라이브 DB 존재. 미충족 시 즉시 B-Type 보고 + exit 2. (`BACKUP_REPO_URL`/`BACKUP_GITHUB_TOKEN` 점검 분기 삭제.)
  2. 디스크/디렉터리 점검: 임시 작업 디렉터리 생성 가능 + 디스크 free 충분 (DB 크기 × 3 이상). git 설치 점검 분기 삭제.
  3. scheduler 등록: 격리된 `schedule.Scheduler()` 인스턴스에 `register_backup_jobs` 적용 → 3 jobs (글로벌 schedule 무오염). schedule 미설치 시 SKIP.
  4. backup dry-run: VACUUM INTO + gzip + 회전 시뮬레이션 (.db.gz 즉시 폐기).
  5. backup 실 실행: 실제 .db.gz 생성 (임시 backup_dir/daily/). 1건 이상 확인.
  6. restore `--list`: 임시 디렉터리에서 daily 1건 확인.
  7. restore 실 설치 (임시 대상): integrity_check + 테이블 카운트 + schema_version row 확인.
- **CLI 옵션**: `--db-path` / `--skip-real-backup` / `--no-slack` / `--keep-temp`.
- **종료 코드**: 0(전 단계 PASS 또는 SKIP만) / 1(1단계 이상 FAIL) / 2(사전조건 미충족, B-Type).
- **슬랙 보고**: 성공 시 `[Backup VERIFY OK] N건 통과 / SKIP M건 / elapsed=Xs`, 실패 시 `[Backup VERIFY FAIL] ...`.
- **로컬 검증**: py_compile PASS + ReadLints 0건. 로컬 PC(키·DB·schedule 부재)에서는 [1/7] 사전조건 FAIL → exit 2 로 graceful 종료.
- **운영 권장 사용**: `python scripts/verify_backup_e2e.py` (전체) / `python scripts/verify_backup_e2e.py --skip-real-backup --no-slack` (비파괴 사전 점검).

