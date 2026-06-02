System Architecture (Atomic)

1. 문서 체계/워크플로우
- 설계 우선: 사양(SYS/DETAIL) 업데이트 후 코드 변경.
- Post-Update: 구현 완료 후 시그니처/변경 파일을 문서에 동기화.
- 변경 이력: append-only, 이전 항목 생략 금지.
- 섹션 순서: "향후 과제"는 문서 최하단 유지.

2. 전역 코딩 규칙
- 명명: 구조체 접미사 사용 (_list, _dict, _map, _set).
- DRY: 동일 로직은 공통 헬퍼로 추출.
- 언어/인코딩: 한국어 주석/설명, UTF-8, .py 이모지 금지.
- 보안: .json, .env .session 내용 직접 분석 금지.

3. 전역 런타임 구조
- 진입점: main.py
- 오케스트레이션: src/execution/orchestrator.py
- 외부 연동:
  - KIS: src/core/kis_api.py
  - Gemini: src/strategy/ai_logic.py
  - Google Drive: src/memory/drive_client.py
  - Slack: src/utils/slack_interface.py (알림 송신 및 대화형 Block Kit 기반 사용자 명령/상호작용 전담 게이트웨이)
- 인제스트 파이프라인:
  - Telegram Pipeline: src/pipeline/telegram_pipeline.py (외부 정보 수집 전용 채널)
- 공통 유틸: src/utils/{timekit,market_calendar,paths,jsonio,macro_triggers}.py
- 데이터 영속화: src/storage/state_store.py (도메인 API). 호출자는 백엔드(Drive/SQLite/PG) 를 알지 못한다. Doc/features/data_persistence/
- 거래일/장중: src/utils/market_calendar.py (`is_trading_day`, `is_market_hours`). 기존 `is_market_open` = 장중.
- KIS 토큰: src/core/token_manager.py (24h TTL, 거래일 08:00 scheduled, on-demand). Doc/features/kis_token/
- 매수 결정 단일화: !ai매수/!수동등록/!발굴 은 동일한 점수 산출 로직을 사용한다.
- 슬랙 명령어 컨벤션 (v1.4, 2026-05-25): **`!카테고리 [서브명령] [옵션]`** 패턴으로 통일.
  - 통합 카테고리: `!보고`, `!단타`, `!백필`, `!테스트` (예: `!보고 일일`, `!단타 시작`, `!백필 스캔 30`).
  - 단독 명령: `!잔고`, `!성과`, `!HTS스캔`, `!역발상`, `!발굴`, `!타점분석`, `!ai매수`, `!수동등록`, `!크로니클`, `!초기화`, `!명령어`, `완료`, `확인`.
  - 구 명령어(`!일일보고`, `!단타시작`, `!백필스캔` 등)는 하위호환 OR 정규식으로 수용되며, 입력 시 새 컨벤션 안내 메시지 1줄을 출력한다.
  - 잘못된 서브명령·옵션 입력 시 각 카테고리는 자체 `_xxx_usage()` 헬퍼로 사용법을 출력한다.
  - 모든 사용법 표시는 `!명령어` 매뉴얼과 일치한다.
- Execution Mode:
  - 기본 모드 (Fundamental Swing)
  - 단타 모드 (Aggressive Day-Trading): src/strategy/scalp_logic.py를 통해 3분봉 기반의 패턴 매칭 및 3중 리스크 방어막 수행. 기동 전 형태 백테스트(scalp_backtest.py) 게이트 PASS + Slack `!단타 시작` 으로 스케줄 실행 활성화 (구 `!단타시작` 호환).

4. 전역 에러/중단 정책
- A-Type: 자가복구(재시도/스킵). 텔레그램 API Rate Limit, 외부 인제스트 장애 등. 주간 예산 입력 대기 중 사용자의 미입력 타임아웃 상황도 A-Type 폴백 정책으로 처리한다.
- B-Type: 사용자 개입 필요 시 Pause + Slack 안내 + 완료로 재개. 단타 모드(Aggressive Day-Trading) 중 주문 실패, 15:10 강제 청산 실패 시 B-Type으로 처리하여 오버나이트 리스크를 방지한다.
- C-Type: 치명적 오류 즉시 중단.
- 스키마 불일치: DriveSchemaMismatchError를 B-Type으로 처리.
- OAuth `invalid_grant` 자동 감지 (B-Type): 런타임 중 Google Drive refresh_token 만료/취소 발생 시 `drive_client._handle_oauth_expiry_if_needed` 가 자동으로 Pause + 슬랙 알림 + `_DRIVE_SERVICE` 캐시 무효화를 수행한다. 진입점은 `read_json_relative`/`write_json_relative` 와 `logger.{load,save}_json_from_gdrive` 의 fallback 핸들러 두 곳이다. 사용자가 `scripts/drive_oauth_setup.py --no-browser` 로 재발급 후 슬랙 `완료` 입력 시 재개. Testing 모드(7일 만료) 회피를 위해 OAuth 동의 화면 Production 승격을 권장한다.

5. 인프라/운영 기준
- 환경: AWS LightSail, Ubuntu 22.04, Python 3.10+
- 실행: 상시 실행(systemd/nohup)
- 설정: .env 기반(인증키/모드/Drive/Slack API 설정)
- 슬랙 게이트웨이: 모든 시스템 알림 송신 및 사용자 제어 명령(슬랙 앱 핸들러 및 인터랙티브 웹훅) 주입을 일원화하여 관리한다.

6. 커밋/변경 기록 정책
- 커밋 메시지: 핵심 2~3줄. 상세는 문서 참조 한 줄로 대체.
- 기능 변화는 SYS/FEATURE 문서 동시 갱신.