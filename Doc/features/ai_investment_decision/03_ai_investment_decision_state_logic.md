AI Investment Decision State Logic

버전별 구현율: v1.0 (100% 설계, 100% 구현 — 본 PR 기준) -> v1.1 (텔레그램 리서치 연동 반영)

1) 점수 → 의견 라벨 결정 (코드)

| 점수 범위 | 의견 라벨 | 비고 | | ------ | ------ | ------ | | 85 이상 | 매수적극찬성 | 최상위 권장 |
| 70 ~ 84 | 매수찬성 | 통상 매수 권장 | | 60 ~ 69 | 매수주의 | 분할/소액 검토 | | 50 ~ 59 | 관망/주의 |
신규 매수 보류 권장 | | 50 미만 | 매수반대 | 보유 시 비중 축소 검토 |

  - 임계값/라벨은 macro_triggers.OPINION_THRESHOLDS_LIST 와
    macro_triggers.OPINION_LABEL_ORDER 에서만 수정한다.
  - 라벨 수/순서 변경 시 본 표와 02_api_spec.md 를 동시 갱신해야 시야 한다.

2) AI sanity 검토 → delta 적용

1.  코드: opinion_code = derive_opinion_from_score(score)
2.  AI: review_opinion_with_ai(...) 호출.
      - 응답 첫 줄: [유지] | [+1] | [-1] 중 1택.
      - 두 번째 줄: 1문장 사유.
      - 파싱 실패/타임아웃 시 delta=0.
3.  코드: opinion_final = adjust_opinion_label(opinion_code, delta)
      - OPINION_LABEL_ORDER 양 끝에서 클램프.

3) theme_context 생성 단일 규칙

  - target_theme 결정 우선순위:
    1.  !발굴 경로: 네이버 공식 테마 매핑 결과 그대로.
    2.  !ai매수 경로: score_single_ticker 가 산출한 target_theme (예: "가치성장 대장주", "우량
        금융주"). 산출 실패 시 "AI매수(단일종목)".
    3.  !수동등록 경로: 동일 산출. 산출 실패 시 "수동등록(단일종목)".
  - narrative 는 ai_logic.get_theme_stock_narrative 호출 결과.
  - 저장 경로: theme_context.json[ticker].

4) [한줄요약] 라인 조립 규약

코드가 다음 포맷으로 1줄을 조립한다(LLM 본문 프롬프트는 이 라인을 만들지 않는다).

  - llm_rationale / llm_upside / llm_downside 는 LLM 본문에서 정규식으로 추출.
  - 추출 실패 시 "(자동 추출 실패)" 폴백.
  - [추가] LLM 본문 프롬프트 생성 시 텔레그램 인사이트가 주입된 경우, llm_rationale 항목 서술에 증권사 리서치 내용이 자연스럽게 통합되어 작성되도록 프롬프트로 강제한다.

5) 데이터 스키마 영향

  - paper_trades.json 의 BUY 레코드 reason 필드는 위 한줄요약을 그대로 포함한다.
  - pending_orders[oid] 추가 필드(메모리, !ai매수 승인 대기):
      - score: int (기존)
      - opinion: str (신규, 코드 결정 최종 라벨)
      - opinion_code: str (신규, AI 보정 전 라벨)
      - opinion_delta: int (신규, -1|0|+1)
  - split_orders.json[uuid] 추가 필드(승인 시 영속화):
      - 위 4종(score, opinion, opinion_code, opinion_delta) 동일.