# KIS Token API Spec

## 모듈: `src/core/token_manager.py`

```python
TOKEN_TTL_HOURS = 24
DEFAULT_MIN_INTERVAL_MIN = 60

get_access_token(app_key, secret_key, *, context="on_demand", force=False) -> str|None
get_token_cache_info() -> dict
issue_scheduled_token(app_key, secret_key) -> dict
```

### `context`
| 값 | 용도 |
|---|---|
| `on_demand` | 슬랙/오케스트레이터 장중 호출 (기본) |
| `scheduled` | 08:00 `issue_daily_token` |

### `get_token_cache_info() -> dict`
```python
{
  "has_token": bool,
  "issued_at": str|None,
  "expires_at": str|None,
  "minutes_since_issue": float|None,
  "is_valid": bool,
}
```

### `issue_scheduled_token(app_key, secret_key) -> dict`
- `is_trading_day()` False -> `{"issued": False, "reason": "not_trading_day", "token": cached|None}`
- 1h 미경과 -> `{"issued": False, "reason": "min_interval", "token": cached}`
- 성공 -> `{"issued": True, "reason": "scheduled_refresh", "token": str}`

## orchestrator

```python
MarketOrchestrator.issue_daily_token() -> None
```
- `issue_scheduled_token` 호출 후 `kis.set_token`, 슬랙 알림(issued=True 일 때만).

## 하위 호환
- 기존 `get_access_token(app_key, secret_key, force=False)` 호출은 `context="on_demand"` 로 동작.
