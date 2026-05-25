# KIS Token Policy (Feature Index)

## 구현율
- v1.0 (2026-05-24): 100%

## 기능 요약
KIS Open API OAuth access token 의 **24시간 TTL 캐시**, **거래일 08:00 스케줄 갱신**,
**휴장일 자동 발급 금지**, **on-demand(슬랙/사용자) 발급** 을 `token_manager` 에서 단일화한다.

## 문서 인덱스
- `./01_kis_token_requirements.md`
- `./02_kis_token_api_spec.md`
- `./03_kis_token_state_logic.md`

## 연관
- `./../market_calendar/`: `is_trading_day` 게이트
- `token_info.json`: 로컬 캐시 (issued_at + access_token)
