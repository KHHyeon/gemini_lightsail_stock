# Data Persistence Requirements

## 1. 범위 (Phase 1)
- 도메인 API 모듈: `src/storage/state_store.py`
- 도메인 적용: A(운영 상태) + B(거래 이력)
- 백엔드: Drive 위임 (변경 없음). Phase 2 에서 SQLite 추가.
- 호출자 영향: import 경로 변경 + 함수명 변경. 비즈니스 로직 변경 0.

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
