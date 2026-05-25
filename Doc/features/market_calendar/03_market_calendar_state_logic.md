# Market Calendar State & Logic

## 구현율
- v1.1 (2026-05-25): 휴장일 사유 라벨 노출 + 기동/일일 가시성 알림 — 100% 설계, 100% 구현.

## 1. 공휴일 캐시
- 모듈 전역 `_holiday_date_set` (lazy load, `reload=True` 로 갱신).
- 사유 라벨 캐시 `_holiday_label_map`: `details_YYYY` 매핑(있는 경우만)을 보존.
- 로드 상태 캐시 `_holiday_load_status`: `file_exists`, `count`, `extra_count`, `schema_version`, `loaded`.
- `KRX_HOLIDAYS_EXTRA=2026-05-01,2026-12-31` 형식의 env 로 임시 추가 가능.

### 1.1 휴장일 데이터 (`data/krx_holidays.json`) 스키마

```json
{
  "schema_version": 2,
  "market": "KRX",
  "note": "...",
  "holidays": ["2025-01-01", ...],
  "details_2026": {"2026-05-25": "부처님오신날 대체공휴일(5/24 일)", ...}
}
```

- `holidays`: ISO date 문자열. 토/일은 코드의 weekday 가드로 자동 제외되므로 평일 휴장일만 우선 등재.
- `details_YYYY`: 사유 라벨(슬랙/리포트 노출용). 누락되면 빈 라벨로 동작.
- **연말 append-only 갱신** 의무. 신규 임시공휴일/대체공휴일 발생 시 즉시 반영.

### 1.2 휴장일 갱신 정책 (운영 규칙)

| 시점 | 트리거 | 동작 |
|---|---|---|
| 매년 12월 | KRX 익년 휴장일 공시 + 천문연 월력요항 발표 | 다음해 holidays + details_YYYY 추가 PR 머지 |
| 수시 | 임시공휴일 지정 | 24시간 내 PR 머지. 긴급 시 `KRX_HOLIDAYS_EXTRA` env 로 임시 적용 |
| 정정 | 누락/오류 발견 | 즉시 PR + 본 사양서 §1.1 example 갱신 |

## 2. 스케줄 가드 적용 위치

| 파일 | 변경 |
|---|---|
| `main.py` | `_is_first_trading_day` -> `is_first_trading_day_of_week`, `_calendar_daily_notice` 08:30 cron |
| `orchestrator.py` | `auto_stock_discovery`, `daily_routine`, `chronicle_routine`, `scalp_force_liquidation` 등 거래일/장중 가드 |
| `risk_monitor.py` | `is_market_hours` (기존 `is_market_open` 경유) |

가드 호출 사슬: `helpers.is_market_open()` → `timekit.is_market_open()` → `market_calendar.is_market_hours()` → 내부 `is_trading_day()` → `load_holiday_date_set()`.

## 3. 가시성 알림 정책 (v1.1)

운영자가 휴장일에 routine 들이 조용히 SKIP 되는 상황을 인지하지 못해 사고가 늦게 발견되는 패턴을 방지한다.

### 3.1 기동 시 1회 알림 (`main._bootstrap_market_calendar_status`)
- 파일 미존재 → `[Calendar][경고] data/krx_holidays.json 미존재` 경고 발송.
- 파일 정상 + 오늘 거래일 → `[Calendar] 휴장일 N건 로드 (schema vX). 오늘은 거래일.`
- 파일 정상 + 오늘 휴장일 → `[Calendar] 휴장일 N건 로드 ... 오늘은 {사유} - 자동 매매/시황 routine SKIP, 정기보고만 수동 실행 가능.`

### 3.2 일일 안내 (`_calendar_daily_notice`, 08:30 cron)
- 평일 + 거래일 → **침묵** (노이즈 회피)
- 평일 + 휴장일 → 1회 안내: `[Calendar] 오늘(YYYY-MM-DD) 휴장 — 사유: {label}. 자동 매매/시황 routine SKIP. 필요 시 수동 정기보고만 실행 가능.`
- 토/일 → **침묵**

### 3.3 사유 라벨 API (`market_calendar.get_holiday_label`)
- 입력일 KST datetime/date/None(=now).
- 반환: 거래일이면 `None`, 토/일이면 `"주말"`, 휴장일이면 라벨 문자열(없으면 빈 문자열).

## 4. 판별 흐름

```
now_kst()
  -> weekday >= 5 ? -> not trading day
  -> date in holiday_set ? -> not trading day
  -> trading day
  -> 09:00 <= t <= 15:30 ? -> market hours
```

## 5. 파일 매핑
- 판별: `src/utils/market_calendar.py`
- KST/장중 alias: `src/utils/timekit.py`
- 호환 wrapper: `src/utils/helpers.py`
- 공휴일 데이터: `data/krx_holidays.json`
- 기동/일일 알림: `main.py` (`_bootstrap_market_calendar_status`, `_calendar_daily_notice`)
- 테스트: `tests/temp_test_market_calendar_and_token.py`
