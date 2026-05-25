# KIS Token Requirements

## 1. 기능 요구사항

### T1. 24시간 TTL
- 유효 캐시(`issued_at` + 24h 미경과)가 있으면 재사용.

### T2. 휴장일 자동 발급 금지
- `context="scheduled"` (08:00 `issue_daily_token`) 는 **거래일**에만 KIS API 호출.
- 휴장일 스케줄 트리거 시 기존 유효 캐시 반환, 없으면 `None` (발급 안 함).

### T3. 휴장일 on-demand 발급
- `context="on_demand"` (슬랙 명령, 사용자 조회): 캐시 만료/없음이면 **휴장일에도** 발급.
- 유효 캐시 있으면 재사용.

### T4. 거래일 08:00 스케줄 갱신
- 거래일 08:00 KST `scheduled` 호출 시 **24h 미경과여도** 새 토큰 발급 허용.
- 단, **마지막 발급 후 1시간 미경과**면 발급 SKIP (기존 캐시 반환).
- env `KIS_TOKEN_MIN_INTERVAL_MIN` 기본 60.

### T5. force 플래그
- `force=True`: 1시간 규칙·TTL 무시하고 즉시 재발급 (운영/디버그용, 스케줄 기본 경로에서는 미사용).

## 2. 비기능

### N1. 저장
- `token_info.json` (project root, jsonio). `.env` 키는 읽지 않음.

### N2. 실패
- KIS API 실패 시 `None` 반환, 호출부에서 슬랙/로그 처리.
