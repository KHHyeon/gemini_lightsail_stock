AI Investment Decision Requirements

1) 기능 요구사항 (Functional)

R1. 단일 진입점 일관성

  - !ai매수, !수동등록, !발굴 모두 동일한 펀더멘털 스코어 산출 함수와 동일한 theme_context 생성
    규칙(build_theme_context_entry)을 사용한다.
  - 동일 종목·동일 시점에서 세 진입점이 산출하는 점수/의견은 동일해야 한다.

R2. 코드 결정 / LLM 설명 분리

  - 의견 라벨(5단계)은 코드가 결정한다(derive_opinion_from_score).
  - LLM 은 의견 라벨을 재선택하지 않는다.
  - LLM 은 '근거 설명 / 상승 조건 / 손절 조건' 세 항목 텍스트만 생성한다.
  - 최종 [한줄요약] 라인은 코드가 조립한다.

R3. AI 1회 sanity 검토(선택)

  - 코드가 결정한 의견 라벨을 AI 가 ±1 단계 범위에서만 보정 제안한다.
  - 보정 제안은 입력일 뿐이며, 최종 라벨은 코드가 adjust_opinion_label 로 결정한다.

R4. 임계값 외부화

  - 의견 라벨 결정 임계값과 라벨 순서는 src/utils/macro_triggers.py 한 곳에 상수로 노출되어 운영 중 수정 가능해야
    한다.

R5. theme_context 일관성

  - theme_context.json[ticker] 값은 [테마: {target_theme} | 총점:
    {score}]\n{narrative} 형식을 유지한다.
  - !수동등록 의 target_theme 폴백은 "수동등록(단일종목)" 으로 고정한다.
  - !ai매수 의 target_theme 폴백은 "AI매수(단일종목)" 으로 고정한다.
  - 둘 다 코드가 산출한 점수/내역을 사용해 동일 함수로 생성·저장한다.

[추가] R6. 텔레그램 리서치 컨텍스트 주입

  - AI가 매매 근거(Rationale)를 설명할 때, 해당 종목에 연관된 최근 텔레그램 증권사 리서치 정보(telegram_insight_dict)가 존재할 경우 이를 프롬프트에 제공하여 풍부한 문맥을 반영하도록 한다.

2) 비기능 요구사항 (Non-Functional)

N1. 재현성

  - 같은 점수에서 같은 의견 라벨이 결정되어야 한다(LLM 비결정성 제거).

N2. 토큰/속도 최적화

  - LLM 호출 횟수 증가 1회(review_opinion_with_ai) 이내로 제한.
  - 본문 리포트의 의견 라벨 자유선택 제거로 토큰 사용량은 동등 또는 감소.

N3. 하위 호환

  - theme_context.json 의 기존 키 포맷·파일 경로는 유지.
  - paper_trades.json 기록의 strategy_tag 등 기존 필드 유지.

3) 운영 제약

  - 임계값/라벨 변경은 macro_triggers.py 상수만 수정.
  - 점수 산출 로직 변경 시 screener.score_single_ticker 한 곳만 수정.
  - 새로운 진입점을 추가할 때도 동일 헬퍼를 재사용해야 한다.