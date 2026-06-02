# Data Persistence Requirements

## 1. 범위
### 1.1 Phase 1 (완료)
- 도메인 API 모듈: `src/storage/state_store.py`
- 도메인 적용: A(운영 상태) + B(거래 이력)
- 백엔드: Drive 위임 (변경 없음).
- 호출자 영향: import 경로 변경 + 함수명 변경. 비즈니스 로직 변경 0.

### 1.2 Phase 2 (본 PR 의 사양 정의 단계)
- SQLite 백엔드 신설: `src/storage/sqlite_backend.py`.
- 마이그레이션 러너: `src/storage/migrations/runner.py` + `v001_initial.py`.
- 이관 스크립트(수동): `scripts/migrate_drive_to_sqlite.py`.
- 환경변수 분기: `STATE_STORE_BACKEND`, `STATE_STORE_DB_PATH`.
- 도메인 적용: A/B 만. C/D(Chronicles) 는 Phase 3 에서 v2 스키마와 함께.
- `logger.record_trade` 의 `paper_trades.json` self-call 은 Phase 2 에서 변경하지 않는다 (Phase 2.5).

## 2. 기능 요구사항
- F1. 호출자는 백엔드 종류(Drive/SQLite/PG)를 알 수 없어야 한다.
- F2. 도메인 메서드는 의미 단위로 분리한다 (`get_portfolio`, `save_split_orders` 등). 파일명·확장자·경로를 호출자가 알 필요 없다.
- F3. `state_store` 는 백엔드 객체를 모듈 레벨 단일 인스턴스로 보유한다. Phase 2 에서 환경변수(`STATE_STORE_BACKEND`)로 교체 가능.
- F4. 반환 타입은 Python 기본 자료형(`dict`/`list`)으로 통일한다. Phase 3 에서 dataclass 도입 시에도 호환성 유지.
- F5. Phase 1 단계에서 `src/utils/logger.py` 의 `load_json_from_gdrive`/`save_json_to_gdrive`/`record_trade` 는 하위 호환을 위해 유지한다. 테스트 monkeypatch 와 logger 내부 self-call 보호.

## 3. 비기능 요구사항
- N1. 외부 의존성 0 (Phase 1 은 stdlib 만 사용. Phase 2 의 `sqlite3` 도 stdlib).
- N2. 동일 프로세스 내 호출 빈도 100/sec 까지 지연 무시 가능 수준.
- N3. 백엔드 교체 시 호출자 코드 0건 변경 (Repository 패턴).
- N4. 모듈 import 사이클 없음. `state_store` 는 `logger` 만 의존, 반대 방향 금지.

## 4. 제약
- C1. 룰(`.cursor/rules/autostock.mdc` §2) 의 변수 명명 규칙 준수: 구조체는 `_dict`/`_list` 접미사.
- C2. UTF-8 + .py 이모지 금지.
- C3. `.json`/`.env` 파일 직접 분석 금지 (룰 §3).
- C4. 도메인 메서드 시그니처는 Phase 2/3 진행 시에도 **추가만 가능, 기존 메서드 시그니처 변경 금지**.

## 5. 도메인 책임 정의
### A. 운영 상태 (mutable snapshot)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| portfolio | 보유 종목 잔고/평단/모드 | 매 거래 시 |
| split_orders | 분할 매수 큐 (티커별 잔여 차수) | 매분 ~ 매 거래 |
| theme_context | AI 테마 기억 (수동등록 / 발굴) | 매 등록 시 |
| scalp_session | 단타 세션 상태 (예산/lifecycle/position) | 매 lifecycle 전이 |

### B. 거래 이력 (append-only)
| 도메인 | 데이터 의미 | 변경 빈도 |
|---|---|---|
| trades | 모든 매수/매도 기록 (시계열) | 매 체결 시 |

### Phase 1 제외 (Phase 3 에서 다룸)
- C. Chronicle 인덱스 (`master_index entries`)
- D. Chronicle 본문 (`.md` 5섹션)

## 6. 호환성/회귀 안전망
- R1. Phase 1 PR 적용 후 봇 기동/매수/매도/risk_monitor/scalp_session 모든 흐름이 동일하게 동작해야 한다.
- R2. 테스트 monkeypatch 코드(`tests/temp_test_scalp_logic.py:277,311`, `tests/temp_test_market_calendar_and_token.py:196-197`) 는 `orchestrator.load_json_from_gdrive` 를 패치하므로, **orchestrator 의 `load_json_from_gdrive` import 는 유지**한다 (state_store 와 별개로 보존).
- R3. Phase 2 진입 전 단위 테스트(`tests/test_state_store.py`) 추가 권장.

## 7. Phase 2 요구사항
### 7.1 기능
- P2F1. SQLite 백엔드는 `_StateStoreBackend` 인터페이스를 동일하게 구현한다 (`read_json`/`write_json`). 호출자 코드 0 변경.
- P2F2. `state_store` 모듈 로드 시 환경변수 `STATE_STORE_BACKEND` 값(소문자 trim)으로 백엔드를 결정한다. 기본값 `"drive"`. `"sqlite"` 만 허용 추가 키워드.
- P2F3. SQLite 파일 경로는 환경변수 `STATE_STORE_DB_PATH` (기본 `data/sqlite/autostock.db`). 파일이 없으면 자동 생성하고 `apply_pending` 으로 스키마 부트스트랩.
- P2F4. 마이그레이션 러너는 `src/storage/migrations/` 의 `vNNN_*.py` 파일을 버전 오름차순으로 적용한다. `schema_version` 테이블이 적용 이력을 기록한다.
- P2F5. 이관 스크립트는 명시적 사용자 실행. `--db-path`/`--dry-run` 옵션. 단계: ① Drive 5 도메인 로드 → ② SQLite 스키마 생성 → ③ INSERT → ④ 카운트 비교 → ⑤ 결과 출력/슬랙.
- P2F6. 이관 후 Drive 의 원본 JSON 5개는 그대로 보존한다 (Phase 5 까지).

### 7.2 비기능
- P2N1. 외부 의존성 0 (`sqlite3` 은 stdlib).
- P2N2. SQLite 연결은 모듈 단일 인스턴스. `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`.
- P2N3. 모든 write 는 트랜잭션 1건으로 묶는다 (자동 rollback 보장).
- P2N4. read latency 는 동일 프로세스 기준 1ms 이하 목표 (paper_trades.json 1MB 가정).

### 7.3 폴백/에러 정책
- P2E1. SQLite 에러는 그대로 상위로 전파한다 (Drive 폴백 금지). 상위(`drive_client` Pause 라인과 동일 위치)에서 B-Type 으로 처리하도록 일관성 유지.
- P2E2. DB 파일 디렉터리 부재 시 자동 생성 (`os.makedirs(exist_ok=True)`).
- P2E3. 스키마 마이그레이션 실패 시 부분 적용 방지 — `BEGIN`/`COMMIT` 묶음 + 실패 시 ROLLBACK.

### 7.4 비고
- P2T1. trades 테이블은 Phase 2 시작점에서 `payload_json` 단일 컬럼만 둔다. `mode_type`/`strategy_tag`/`price`/`qty` 등 검색 키는 Phase 3+ 에서 점진적으로 외부 컬럼화한다 (2-phase migration 패턴).
- P2T2. `replace_trades` 는 Phase 2 에서도 전체 교체 시맨틱을 유지한다. Phase 2.5 에서 `append_trade` 추가 검토.

## 8. Phase 2 회귀 안전망
- P2R1. `STATE_STORE_BACKEND` 미설정 → 기존 Drive 백엔드 100% 동일 동작. Phase 1 회귀 0.
- P2R2. SQLite 백엔드 전환 후 `state_store` 의 모든 공개 함수 시그니처/반환 타입은 Phase 1 과 동일하다.
- P2R3. 이관 스크립트의 dry-run 모드에서 INSERT 미실행 + 카운트만 출력. 사용자가 결과 확인 후 실제 적용 명령 별도 실행.
