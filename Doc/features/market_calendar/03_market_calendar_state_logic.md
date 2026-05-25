# Market Calendar State & Logic

## 1. 공휴일 캐시
- 모듈 전역 `_holiday_date_set` (lazy load, `reload=True` 로 갱신).
- `KRX_HOLIDAYS_EXTRA=2026-05-01,2026-12-31` 형식.

## 2. 스케줄 가드 적용 위치

| 파일 | 변경 |
|---|---|
| `main.py` | `_is_first_trading_day` -> `is_first_trading_day_of_week` |
| `orchestrator.py` | `auto_stock_discovery`, `daily_routine`, `chronicle_routine` 등 거래일/장중 가드 |
| `risk_monitor.py` | `is_market_hours` (기존 `is_market_open` 경유) |

## 3. 판별 흐름

```
now_kst()
  -> weekday >= 5 ? -> not trading day
  -> date in holiday_set ? -> not trading day
  -> trading day
  -> 09:00 <= t <= 15:30 ? -> market hours
```

## 4. 파일 매핑
- 판별: `src/utils/market_calendar.py`
- KST/장중 alias: `src/utils/timekit.py`
- 호환 wrapper: `src/utils/helpers.py`
- 공휴일 데이터: `data/krx_holidays.json`
- 테스트: `tests/temp_test_market_calendar_and_token.py`
