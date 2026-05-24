System Architecture (Atomic)

1) 문서 체계/워크플로우

  - 설계 우선: 사양(SYS/DETAIL) 업데이트 후 코드 변경.
  - Post-Update: 구현 완료 후 시그니처/변경 파일을 문서에 동기화.
  - 변경 이력: append-only, 이전 항목 생략 금지.
  - 섹션 순서: "향후 과제"는 문서 최하단 유지.

2) 전역 코딩 규칙

  - 명명: 구조체 접미사 사용 (_list, _dict, _map, _set).
  - DRY: 동일 로직은 공통 헬퍼로 추출.
  - 언어/인코딩: 한국어 주석/설명, UTF-8, .py 이모지 금지.
  - 보안: .json, .env .session 내용 직접 분석 금지.

3) 전역 런타임 구조

  - 진입점: main.py
  - 오케스트레이션: src/execution/orchestrator.py
  - 외부 연동:
      - KIS: src/core/kis_api.py
      - Gemini: src/strategy/ai_logic.py
      - Google Drive: src/memory/drive_client.py
      - Telegram: src/core/telegram_client.py (외부 API 캡슐화 전용)
  - 인제스트 파이프라인:
      - Telegram Pipeline: src/pipeline/telegram_pipeline.py
        (수집·정제 후 오케스트레이터에 결과만 반환하는 독립 파이프라인)
  - 공통 유틸: src/utils/{timekit,paths,jsonio,macro_triggers}.py
  - 매수 결정 단일화: !ai매수/!수동등록/!발굴 은 동일한 점수 산출 (screener.score_single_ticker)과 동일한
    theme_context 생성 규칙 (ai_logic.build_theme_context_entry)을 사용한다. 의견 라벨은 코드가
    결정하고(macro_triggers.derive_opinion_from_score), LLM 은 근거 설명만 담당한다. 상세는
    Doc/features/ai_investment_decision/.
  - 관심사 분리 (인제스트 ↔ 도메인):
      - Telegram Pipeline 은 수집·정제 + 반환만 담당한다.
      - 오케스트레이터가 결과를 받아 후속 도메인(Market Chronicles 적재, 매수 결정 등)에 위임한다.
      - 의존성 방향: telegram_pipeline -> orchestrator -> (market_chronicles | ai_investment_decision)
        (역방향 import 금지). 상세는 Doc/features/telegram_pipeline/.

4) 전역 에러/중단 정책

  - A-Type: 자가복구(재시도/스킵). 텔레그램 API Rate Limit·일시 네트워크 장애·단일 메시지 파싱 실패 등
    외부 인제스트 장애는 A-Type 으로 격리하며, 트레이딩 코어(KIS 주문/리스크 감시) 실행을 멈추지 않는다.
  - B-Type: 사용자 개입 필요 시 Pause + Slack 안내 + 완료로 재개.
  - C-Type: 치명적 오류 즉시 중단.
  - 스키마 불일치: DriveSchemaMismatchError를 B-Type으로 처리.

5) 인프라/운영 기준

  - 환경: AWS LightSail, Ubuntu 22.04, Python 3.10+
  - 실행: 상시 실행(systemd/nohup)
  - 설정: .env 기반(인증키/모드/Drive/Telegram API 설정)
  - 슬랙 송신: 오케스트레이터 게이트웨이 단일화

6) 커밋/변경 기록 정책

  - 커밋 메시지: 핵심 2~3줄.
  - 상세는 문서 참조 한 줄로 대체.
  - 기능 변화는 SYS/FEATURE 문서 동시 갱신.