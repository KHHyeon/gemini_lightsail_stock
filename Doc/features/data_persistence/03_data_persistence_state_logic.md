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

## 4. 호출자 마이그레이션 매트릭스 (Phase 1 PR 적용 범위)
| 파일 | 변경 호출 수 |
|---|---|
| `backtester.py` | 1 (read portfolio) |
| `src/utils/slack_interface.py` | 9 (read portfolio×3, read split×2, write split×1, read trades×1, reset×1, import 라인 갱신) |
| `src/execution/orchestrator.py` | 14 (read portfolio×4, read split×4, write portfolio×1, write split×4, import 라인 갱신) |
| `src/execution/risk_monitor.py` | 4 (read portfolio×1, read split×1, write portfolio×1, write split×1) |
| `src/strategy/ai_logic.py` | 2 (read/write theme_context) |
| `src/memory/scalp_session_store.py` | 3 (read scalp_session, write scalp_session, read portfolio) |
| `src/utils/logger.py` | 0 (self-call 유지) |

총 33 호출 변경 (이전 추정 26 보다 많음: 동일 함수 다회 호출 카운트 포함).

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
