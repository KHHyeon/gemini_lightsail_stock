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

### Phase 2 에서 추가될 백엔드 (예고)
- `_SQLiteBackend` — `data/autostock.db` 단일 파일. `_StateStoreBackend` 인터페이스 동일.
- 환경변수 `STATE_STORE_BACKEND=sqlite|drive` 로 모듈 로드 시 1회 결정.

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
