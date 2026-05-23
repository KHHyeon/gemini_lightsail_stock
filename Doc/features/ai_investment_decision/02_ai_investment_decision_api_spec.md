AI Investment Decision API Spec

1) 임계값/라벨 API (src/utils/macro_triggers.py)

OPINION_THRESHOLDS_LIST: list[tuple[int, str]]

  - 정의: (min_score, label) 의 내림차순 리스트.
  - 기본값:
      - (85, "매수적극찬성")
      - (70, "매수찬성")
      - (60, "매수주의")
      - (50, "관망/주의")
      - (0, "매수반대")

OPINION_LABEL_ORDER: list[str]

  - 낮은 강도 → 높은 강도 정렬 라벨 리스트. 인접 보정 계산용.
  - 기본값: ["매수반대", "관망/주의", "매수주의", "매수찬성", "매수적극찬성"]

derive_opinion_from_score(score) -> str

  - 입력: int|float|str 펀더멘털 점수.
  - 출력: OPINION_THRESHOLDS_LIST 에 의해 결정된 라벨 1종.

adjust_opinion_label(label, delta) -> str

- 입력: 현재 라벨, 정수 delta (예: -1, 0, +1).
  - 출력: OPINION_LABEL_ORDER 인덱스를 delta 만큼 이동(클램프)한 라벨.

2) 펀더멘털 스코어 API (src/strategy/screener.py)

score_single_ticker(ticker, name, base_url, app_key, secret_key, token) -> dict | None

  - 목적: 단일 종목 펀더멘털 스코어 산출(임계값 필터 미적용).
  - 출력 키: score, score_details, target_theme, current_price, pbr, per, roe,
    is_financial.
  - 유동성/주가 데이터 부재 시 None.

run_unified_screener(...) (변경 없음, 내부적으로 score_single_ticker 재사용)

3) AI 결정 보조 API (src/strategy/ai_logic.py)

build_theme_context_entry(ticker, name, target_theme, score, score_details, val) -> str

- 목적: theme_context.json[ticker] 값을 단일 규칙으로 생성.
  - 출력 포맷: "[테마: {target_theme} | 총점: {score}]\n{narrative}".
  - 내부적으로 get_theme_stock_narrative 를 호출한다.

register_theme_context(ticker, name, target_theme, score, score_details, val) -> str

  - 목적: build_theme_context_entry 결과를 theme_context.json 에 저장하고 반환.

review_opinion_with_ai(ticker, name, score, code_label, val, news, theme_context) -> dict

  - 출력: {"delta": int (-1|0|+1), "reason": str}
  - 실패/모호 응답은 {"delta": 0, "reason": ""} 폴백.

get_multi_agent_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context, recent_news, *, fundamental_score, fundamental_details=None, telegram_insights_list=None) -> tuple[str, dict]

- 변경 사항:
      - fundamental_score 키워드 인자 필수화.
      - [추가] telegram_insights_list 키워드 인자를 추가하여 해당 종목에 해당하는 리서치 정보를 프롬프트에 주입.
      - 내부에서 derive_opinion_from_score + review_opinion_with_ai
          - adjust_opinion_label 호출하여 의견 라벨을 코드가 결정.
      - LLM 본문 프롬프트에서 의견 라벨 자유선택을 제거.
      - [한줄요약] 라인은 코드가 조립.
  - 반환: (report_text, meta). meta 키: score, opinion_code, opinion_final,
    opinion_delta, ai_review_reason.

4) 슬랙 진입점 호출 규약

공통 헬퍼 _build_single_stock_report(ticker, fallback_theme, strategy_label, say) -> dict

  - 위치: src/utils/slack_interface.py (register_slack_handlers 내부 클로저).
  - 반환: 실패 시 {"ok": False}. 성공 시: {"ok": True, "report", "score", "ctx_text",
    "val", "target_theme", "opinion_code", "opinion_final", "opinion_delta",
    "ai_review_reason"}.
  - !ai매수 / !수동등록 가 동일 함수를 호출하여 흐름 일관성을 보장한다.

!ai매수 [종목코드] [총예산]

  - 흐름: _build_single_stock_report → pending_orders[oid] 에 score, opinion,
    opinion_code, opinion_delta 저장 → 승인/기각 버튼.
  - 승인 시 split_orders[uuid] 에 동일 필드들이 함께 저장된다.

!수동등록 [종목코드] [트랙]

  - 흐름: 잔고 조회 → _build_single_stock_report → record_trade 호출.
  - reason 필드는 코드 조립 [한줄요약] 라인을 포함한다.

!발굴 [키워드|배당률]

  - 변경 사항: 통합 스캔 루프(execute_unified_scan)에서 register_theme_context 단일 함수를 호출(인라인
    f-string 제거).