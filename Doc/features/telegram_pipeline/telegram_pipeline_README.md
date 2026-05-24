# Telegram Pipeline (Feature Index)

## 기능 요약
Telegram Pipeline 은 텔레그램 채널 메시지를 수집/정제하여 정규화된 결과를
오케스트레이터에 반환만 하는 **독립 Ingestion Pipeline** 이다.
인덱스 적재(Market Chronicles), AI 프롬프트 주입(ai_investment_decision)
등 후속 처리는 본 파이프라인의 책임이 아니다.

## 설계 원칙 (관심사 분리)
- Telegram Pipeline → 수집/정제 + 반환만.
- Orchestrator → 라우팅(어떤 후속 파이프라인에 위임할지 결정).
- Market Chronicles → 인덱스 적재 및 검색.
- 의존성 방향성: `telegram_pipeline -> orchestrator -> market_chronicles`
  (역방향 import 금지).

## 핵심 흐름
1. `src/core/telegram_client.py` 가 텔레그램 API 호출(인증/Rate Limit/예외 캡슐화).
2. `src/pipeline/telegram_pipeline.py` 가 메시지 정제·정규화 후 결과 리스트 반환.
3. `src/execution/orchestrator.py` 가 반환 결과를 후속 처리(Chronicles 적재 등)에 위임.

## 문서 인덱스
- `01_telegram_pipeline_requirements.md`: 기능/비기능 요구사항, 운영 제약
- `02_telegram_pipeline_api_spec.md`: 공개 API 시그니처·반환 규약
- `03_telegram_pipeline_state_logic.md`: 상태 모델, 에러 격리 로직, 영속화 키

## 에러 격리 (A-Type)
- 텔레그램 API 인증/네트워크/Rate Limit 등 외부 장애는 본 파이프라인 내부에서
  완전히 흡수하고, 호출자에게는 **빈 결과(_list)** 만 반환한다.
- 외부 장애가 트레이딩 코어(KIS/주문/리스크 감시) 흐름을 멈추게 해서는 안 된다.
- 단, 인증 정보 자체가 잘못 구성된 운영자 개입 케이스는 상위(B-Type) 정책 대상이며,
  본 파이프라인은 그 신호만 노출한다(실제 Pause 결정은 오케스트레이터).
