# Market Calendar (Feature Index)

## 구현율
- v1.0 (2026-05-24): 100%

## 기능 요약
한국 주식 **거래일(trading day)** 과 **장중(market hours)** 을 구분하여 스케줄러·오케스트레이터가
휴장일/공휴일에 불필요한 KIS 호출·3트랙 발굴·일일 시황을 실행하지 않도록 게이트한다.

## 핵심 개념
| 함수 | 의미 |
|---|---|
| `is_trading_day(now)` | KST 평일 + KRX 공휴일 제외 |
| `is_market_hours(now)` | `is_trading_day` AND 09:00~15:30 |
| `is_first_trading_day_of_week(now)` | 해당 주 첫 거래일(월요일 공휴 시 화요일 등) |

기존 `is_market_open()` 은 **장중** 의미로 유지하되 내부 구현을 `is_market_hours` 로 통일한다.

## 문서 인덱스
- `./01_market_calendar_requirements.md`: 요구사항·스케줄 분류
- `./02_market_calendar_api_spec.md`: 공개 API
- `./03_market_calendar_state_logic.md`: 공휴일 데이터·스케줄 가드 매트릭스

## 연관 기능
- `./../kis_token/`: 거래일 08:00 토큰 자동 발급 게이트
- `./../scalp_logic/`: 단타 월요일 08:30/09:00 -> `is_first_trading_day_of_week`
