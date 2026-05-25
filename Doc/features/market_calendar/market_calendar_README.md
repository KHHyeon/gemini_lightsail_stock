# Market Calendar (Feature Index)

## 구현율
- v1.0 (2026-05-24): 거래일/장중 가드 100% — 완료
- v1.1 (2026-05-25): 휴장일 사유 라벨 + 기동/일일 가시성 알림 100% — 완료
  - **2026년 휴장일 데이터 전면 정정** (대체공휴일 4건/신규 휴장 3건/추석 일정 오류 수정)
  - 2025-01-27 임시공휴일 누락 정정

## 기능 요약
한국 주식 **거래일(trading day)** 과 **장중(market hours)** 을 구분하여 스케줄러·오케스트레이터가
휴장일/공휴일에 불필요한 KIS 호출·3트랙 발굴·일일 시황을 실행하지 않도록 게이트한다.
v1.1 부터는 휴장일 사유 라벨 노출과 기동/일일 슬랙 알림으로 **조용한 SKIP** 으로 인한 사고를 예방한다.

## 핵심 개념
| 함수 | 의미 |
|---|---|
| `is_trading_day(now)` | KST 평일 + KRX 공휴일 제외 |
| `is_market_hours(now)` | `is_trading_day` AND 09:00~15:30 |
| `is_first_trading_day_of_week(now)` | 해당 주 첫 거래일(월요일 공휴 시 화요일 등) |
| `get_holiday_label(now)` | 휴장일 사유 라벨 (거래일=None, 토/일="주말") |
| `get_holiday_load_status()` | 휴장일 파일 로드 상태 (진단/기동 알림용) |

기존 `is_market_open()` 은 **장중** 의미로 유지하되 내부 구현을 `is_market_hours` 로 통일한다.

## v1.1 가시성 알림
- **기동 시**: `main._bootstrap_market_calendar_status()` 가 휴장일 파일 로드 결과 + 오늘 거래일 여부를 슬랙으로 1회 발송.
- **매일 08:30**: `_calendar_daily_notice` cron — 평일 휴장일에만 안내, 거래일/주말은 침묵.

## 문서 인덱스
- `./01_market_calendar_requirements.md`: 요구사항·스케줄 분류
- `./02_market_calendar_api_spec.md`: 공개 API
- `./03_market_calendar_state_logic.md`: 공휴일 데이터·스케줄 가드 매트릭스

## 연관 기능
- `./../kis_token/`: 거래일 08:00 토큰 자동 발급 게이트
- `./../scalp_logic/`: 단타 월요일 08:30/09:00 -> `is_first_trading_day_of_week`
