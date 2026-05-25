# AI Investment Decision State Logic

## 구현율
- v1.3 (2026-05-25): 5축 채점 + 분석보류 라벨 + AI ±2 확장.

## 1. 점수 → 의견 라벨 결정 (코드)

| 점수 범위 | 의견 라벨 | 비고 |
|---|---|---|
| None / 비숫자 | 분석보류 | 데이터 부족 또는 유동성 미달. AI 보정 미적용. |
| 80 이상 | 매수적극찬성 | 5축 평균 16점 이상. 최상위 권장. |
| 65 ~ 79 | 매수찬성 | 5축 평균 13점 이상. 통상 매수 권장. |
| 50 ~ 64 | 매수주의 | 분할/소액 검토. |
| 35 ~ 49 | 관망/주의 | 신규 매수 보류 권장. |
| 0 ~ 34 | 매수반대 | 보유 시 비중 축소 검토. |

임계값/라벨은 `macro_triggers.OPINION_THRESHOLDS_LIST` 와 `macro_triggers.OPINION_LABEL_ORDER` 에서만 수정한다.

## 2. 5축 GARP 채점 모델 (Greenblatt/Lynch/Piotroski 결합)

### 2.1 비금융 종목

| 축 | 만점 | 근거 |
|---|---|---|
| Value | 20 | Joel Greenblatt Magic Formula 의 Earnings Yield 대용 — 낮은 PER/PBR 가점. |
| Quality | 20 | Greenblatt ROIC 대용으로 KIS 가 제공하는 ROE 절대값 사용. |
| Growth | 20 | Peter Lynch GARP — 매출/영업이익 증가율. |
| Momentum | 20 | 60일선/20일선 정배열. Mean-Reversion 회피. |
| Smart Money | 20 | 외국인·기관 누적 순매수 부호. |

### 2.2 금융주

- Value 의 PER 단계(최대 10점) 는 의미가 약하므로 **ROE 추가 가점(+10)** 으로 대체.
- 나머지 4축 동일.

### 2.3 보류 조건

- `current_price <= 0` → `unscorable_reason = "price_unavailable"`.
- `tr_amount < 100_000_000` → `unscorable_reason = "liquidity_too_low"`.

기존 거래대금 10억 하드컷은 폐기. 자동발굴(`run_3track_screener`) 의 트랙별 컷(10억/30억)은 유지.

## 3. AI sanity 검토 (±2 확장)

- 코드: `opinion_code = derive_opinion_from_score(score)`
- AI: `review_opinion_with_ai(..., max_abs_delta=2)`
  - 입력 토큰: `[유지] | [+1] | [-1] | [+2] | [-2]`
  - ±2 는 다음 조건에서만 허용: 강한 호재/악재(예: 산업 패러다임 전환, 어닝 쇼크) + 정성적 가중치 명확.
  - 모호한 경우 `[유지]` 강제, `delta=0` 폴백.
- 코드: `opinion_final = adjust_opinion_label(opinion_code, delta)` — OPINION_LABEL_ORDER 양 끝 클램프.
- `opinion_code == OPINION_LABEL_HOLD` 인 경우 AI 호출 스킵.

## 4. theme_context 생성 단일 규칙

- target_theme 결정 우선순위:
  1. `!발굴`: 네이버 공식 테마 매핑 결과.
  2. `!ai매수`: `score_single_ticker` 산출 target_theme. 실패 시 `AI매수(단일종목)`.
  3. `!수동등록`: 동일. 실패 시 `수동등록(단일종목)`.
- narrative: `ai_logic.get_theme_stock_narrative`.
- 저장 경로: `theme_context.json[ticker]`.

## 5. [한줄요약] 라인 조립 규약

```
[한줄요약] [의견: {opinion_final}] | [점수: {score} ({opinion_code} → 보정 {delta:+d})]
        | [근거] {llm_rationale} | [상승조건] {llm_upside} | [손절조건] {llm_downside}
```

`opinion_code == OPINION_LABEL_HOLD` 인 경우:

```
[한줄요약] [의견: 분석보류 - {unscorable_reason}] | [점수: N/A]
        | [근거] {llm_rationale} | [상승조건] {llm_upside} | [손절조건] {llm_downside}
```

## 6. 데이터 스키마 영향

`pending_orders[oid]` 및 `split_orders.json[uuid]` 필드:

| 키 | 타입 | 비고 |
|---|---|---|
| score | int \| None | 분석보류 시 None |
| score_breakdown | dict \| None | 5축 분해. 분석보류 시 None |
| unscorable_reason | str \| None | 분석보류 사유 |
| opinion | str | 최종 라벨 |
| opinion_code | str | AI 보정 전 |
| opinion_delta | int | -2~+2 |

## 7. 파일 매핑

- 점수 산출: `src/strategy/screener.py` (`score_single_ticker`)
- 의견 라벨: `src/utils/macro_triggers.py`
- LLM 보정: `src/strategy/ai_logic.py` (`review_opinion_with_ai`, `get_multi_agent_investment_report`)
- 슬랙 헬퍼: `src/utils/slack_interface.py` (`_build_single_stock_report`)
- 테스트: `tests/temp_test_investment_decision.py`
