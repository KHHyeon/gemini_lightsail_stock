# Market Calendar API Spec

## 1. 모듈: `src/utils/market_calendar.py`

```python
load_holiday_date_set(*, reload=False) -> set[date]
is_trading_day(now=None) -> bool
is_market_hours(now=None) -> bool
is_first_trading_day_of_week(now=None) -> bool
get_holiday_label(now=None) -> str | None
get_holiday_load_status() -> dict
```

### `load_holiday_date_set`
- `data/krx_holidays.json` 의 `holidays` 배열(`YYYY-MM-DD`) + `KRX_HOLIDAYS_EXTRA` env 병합.
- 스키마 v2 부터 `details_YYYY` 매핑(사유 라벨)도 함께 적재한다.
- 파일 없으면 빈 set (주말만 제외) + `[Calendar] 휴장일 파일 없음` 1회 경고.

### `get_holiday_label(now=None)`
- 거래일이면 `None`. 토/일이면 `"주말"`. 휴장일이면 사유 라벨(빈 문자열일 수 있음).

### `get_holiday_load_status()`
- 진단/기동 알림용. 키: `file_exists`, `file_path`, `count`, `extra_count`, `schema_version`, `loaded`.

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

`data/krx_holidays.json` (schema_version: 2):
```json
{
  "schema_version": 2,
  "market": "KRX",
  "note": "...",
  "holidays": ["2025-01-01", "..."],
  "details_2026": {
    "2026-05-25": "부처님오신날 대체공휴일(5/24 일)"
  }
}
```

- v1 호환: `holidays` 배열만 있어도 정상 로드된다.
- `details_YYYY` 매핑은 슬랙/리포트에 사유를 노출하기 위한 부가 정보로, 누락은 허용된다.

## 5. 가시성 알림 진입점 (`main.py`)

```python
_bootstrap_market_calendar_status()  # 기동 시 1회 슬랙 발송
_calendar_daily_notice()             # 매일 08:30 cron — 평일 휴장일만 안내
```

자세한 동작은 `03_market_calendar_state_logic.md §3` 참조.
