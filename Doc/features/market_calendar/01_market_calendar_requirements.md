# Market Calendar Requirements

## 1. 기능 요구사항 (Functional)

### R1. 거래일 판별
- KST 기준 **토·일 제외**.
- `data/krx_holidays.json` 에 등록된 **KRX 공휴일** 제외.
- 환경변수 `KRX_HOLIDAYS_EXTRA`(쉼표 구분 `YYYY-MM-DD`) 로 임시 휴장일 추가 가능.

### R2. 장중 판별
- `is_market_hours`: 거래일이면서 09:00:00 ~ 15:30:00 KST (양끝 포함).

### R3. 주간 첫 거래일
- `is_first_trading_day_of_week`: 해당 ISO 주(월~일)에서 **가장 이른 거래일**이 오늘인지 판별.
- 단타 `scalp_pre_routine` / `scalp_open_fallback` 의 월요일 고정 스케줄을 대체한다.

### R4. 휴장일 스케줄 정책
휴장일(주말·공휴일)에는 **일일보고 계열을 제외한 정기보고(주/월/분기)만** 허용하고,
아래는 **SKIP** (A-Type, 슬랙 알림 없음):

| 분류 | Job / 기능 | 휴장일 | 거래일(장전) | 거래일(장중) |
|---|---|---|---|---|
| 토큰 자동 | 08:00 `issue_daily_token` | SKIP | RUN | SKIP(08:00만) |
| 일일 시황 | 08:45 `daily_routine` | SKIP | RUN | SKIP |
| 3트랙 발굴 | 08:50 `auto_stock_discovery` | SKIP | RUN | SKIP |
| 심층/점심/오후 | 10:00/11:45/14:30 | SKIP | SKIP | RUN |
| 수동종목 알림 | 14:20 | SKIP | SKIP | RUN |
| T-Day Chronicle | 15:35 `chronicle_routine` | SKIP | SKIP | RUN(거래일) |
| 주간 리포트 | 월 09:45 `weekly_routine` | SKIP | SKIP | RUN(장중) |
| 리스크 감시 | 30분 `risk_monitor` | SKIP | SKIP | RUN |
| 단타 장중 | 3분 `_scalp_intraday_job` | SKIP | SKIP | RUN |
| 단타 15:10 청산 | `scalp_force_liquidation` | SKIP | SKIP | RUN |
| 단타 주간 예산 | 첫 거래일 08:30/09:00 | SKIP | RUN(첫 거래일) | SKIP |

- **정기보고**(`!주간보고`/`!월간보고`/`!분기보고`, `_run_portfolio_report`): 휴장일에도 **수동 실행** 허용.
- **일일보고**(`!일일보고`, `daily_routine`, `chronicle_routine`): **거래일만**.

### R5. 슬랙/on-demand 명령
- `!HTS스캔`, `!잔고`, `!단타시작` 등 사용자 명령은 휴장일에도 실행 가능(KIS 토큰은 on-demand 정책).

## 2. 비기능 요구사항 (Non-Functional)

### N1. 의존성
- 외부 API 없이 로컬 JSON + 주말 규칙으로 1차 판별(네트워크 불필요).

### N2. 하위 호환
- `helpers.is_market_open()` / `timekit.is_market_open()` 시그니처 유지, 의미만 **장중**으로 정정.

### N3. 연간 갱신
- 매년 `data/krx_holidays.json` 에 다음 연도 공휴일 append (append-only).
