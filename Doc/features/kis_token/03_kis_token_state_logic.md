# KIS Token State & Logic

## 1. 캐시 스키마 (`token_info.json`)

```json
{
  "access_token": "...",
  "issued_at": "2026-05-24 08:00:05"
}
```

`issued_at` 은 **로컬 naive datetime** (`datetime.now()`), TTL 비교도 동일.

## 2. 의사결정 (scheduled)

```
scheduled + not trading_day -> SKIP (return cache or None)
scheduled + trading_day + last_issue < 1h -> SKIP (return cache)
scheduled + trading_day + last_issue >= 1h -> ISSUE (ignore 24h TTL)
on_demand + valid cache -> RETURN cache
on_demand + invalid/missing -> ISSUE (any day)
force=True -> ISSUE (any day, ignore interval/TTL)
```

## 3. 호출 경로

| 경로 | context |
|---|---|
| `issue_daily_token` | scheduled |
| `slack_interface` 핸들러 | on_demand |
| `auto_stock_discovery`, `scalp_*`, `risk_monitor` | on_demand |

## 4. A-Type
- scheduled SKIP 은 에러 아님, 슬랙 미발송.

## 5. 파일 매핑
- `src/core/token_manager.py`
- 테스트: `tests/temp_test_market_calendar_and_token.py` (TestTokenPolicy)
