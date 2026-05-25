# Market Calendar API Spec

## 1. 모듈: `src/utils/market_calendar.py`

```python
load_holiday_date_set(*, reload=False) -> set[date]
is_trading_day(now=None) -> bool
is_market_hours(now=None) -> bool
is_first_trading_day_of_week(now=None) -> bool
```

### `load_holiday_date_set`
- `data/krx_holidays.json` 의 `holidays` 배열(`YYYY-MM-DD`) + `KRX_HOLIDAYS_EXTRA` env 병합.
- 파일 없으면 빈 set (주말만 제외).

### `is_trading_day(now=None)`
- KST 기준. `now` None 이면 `now_kst()`.

### `is_market_hours(now=None)`
- `is_trading_day` AND 09:00 <= t <= 15:30.

### `is_first_trading_day_of_week(now=None)`
- 해당 주 월요일~오늘 사이 더 이른 거래일이 없고, 오늘이 거래일.

## 2. timekit 연동 (`src/utils/timekit.py`)

```python
is_market_open(now=None) -> bool  # alias: is_market_hours 와 동일
```

## 3. helpers 연동 (`src/utils/helpers.py`)

```python
is_market_open() -> bool  # timekit 위임 (변경 없음)
is_trading_day(now=None) -> bool  # market_calendar 위임 (신규)
```

## 4. 데이터 파일

`data/krx_holidays.json`:
```json
{
  "schema_version": 1,
  "market": "KRX",
  "holidays": ["2025-01-01", "..."]
}
```
