# AI Investment Decision State Logic

버전별 구현율: v1.1 (100% 설계, 100% 구현) -> v1.2 (국내/해외 변수 정성적 가중치 융합 및 폴백 정책 반영)

1. 점수 → 의견 라벨 결정 (코드)

| 점수 범위 | 의견 라벨 | 비고 |
| ------ | ------ | ------ |
| 85 이상 | 매수적극찬성 | 최상위 권장 |
| 70 ~ 84 | 매수찬성 | 통상 매수 권장 |
| 60 ~ 69 | 매수주의 | 분할/소액 검토 |
| 50 ~ 59 | 관망/주의 | 신규 매수 보류 권장 |
| 50 미만 | 매수반대 | 보유 시 비중 축소 검토 |

  - 임계값/라벨은 macro_triggers.OPINION_THRESHOLDS_LIST 와 macro_triggers.OPINION_LABEL_ORDER 에서만 수정한다.

2. AI sanity 검토 및 정성적 가중치 산출 → delta 적용

  - 코드: opinion_code = derive_opinion_from_score(score)
  - AI: review_opinion_with_ai(...) 호출 시 추가 컨텍스트 주입.
      - 프롬프트 평가 기준:
        1) 국내 뉴스 변수(수급/섹터 등)와 해외 텔레그램 변수(매크로/밸류체인) 병합 확인.
        2) 타겟 종목의 특성(수출주/내수주/기술주 등)을 기반으로 두 변수 중 어느 쪽이 주가 향방에 더 높은 정성적 가중치를 가지는지 내부 연산.
        3) 상충 시(예: 해외 호재 vs 국내 악재), 가중치가 높은 쪽을 따라 최종 delta 결정.
      - 응답 첫 줄: [유지] | [+1] | [-1] 중 1택.
      - 두 번째 줄: 정성적 가중치 판단이 포함된 1문장 사유.
      - [신규 안전 폴백]: AI 파싱 실패, 타임아웃, 또는 1문장 사유에서 명확한 결론을 도출하지 못할 경우(모호성 감지), 국내 펀더멘털 점수(코드 산출)를 우선순위 앵커로 간주하여 무조건 delta=0으로 폴백 처리한다.
  - 코드: opinion_final = adjust_opinion_label(opinion_code, delta)
      - OPINION_LABEL_ORDER 양 끝에서 클램프.

3. theme_context 생성 단일 규칙

  - target_theme 결정 우선순위:
    1. !발굴 경로: 네이버 공식 테마 매핑 결과 그대로.
    2. !ai매수 경로: score_single_ticker 가 산출한 target_theme. 산출 실패 시 "AI매수(단일종목)".
    3. !수동등록 경로: 동일 산출. 산출 실패 시 "수동등록(단일종목)".
  - narrative 는 ai_logic.get_theme_stock_narrative 호출 결과.
  - 저장 경로: theme_context.json[ticker].

4. [한줄요약] 라인 조립 규약

코드가 다음 포맷으로 1줄을 조립한다(LLM 본문 프롬프트는 이 라인을 만들지 않는다).

  - llm_rationale / llm_upside / llm_downside 는 LLM 본문에서 정규식으로 추출.
  - 추출 실패 시 "(자동 추출 실패)" 폴백.
  - LLM 본문 프롬프트 생성 시, 국내 뉴스 변수와 텔레그램 해외 변수의 가중치 비교 결과가 llm_rationale 항목 서술에 명시적으로 통합되어 작성되도록 프롬프트로 강제한다.

5. 데이터 스키마 영향

  - pending_orders[oid] 및 split_orders.json[uuid] 추가 필드:
      - score: int (기존)
      - opinion: str (신규, 코드 결정 최종 라벨)
      - opinion_code: str (신규, AI 보정 전 라벨)
      - opinion_delta: int (신규, -1|0|+1)