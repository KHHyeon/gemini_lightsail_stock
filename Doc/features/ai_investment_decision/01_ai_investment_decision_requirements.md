# AI Investment Decision Requirements

## 구현율
- v1.3 (2026-05-25): 5축 GARP 채점 + 분석보류 라벨 + AI ±2 확장 — 진행 중

1. 기능 요구사항 (Functional)

R1. 단일 진입점 일관성
  - !ai매수, !수동등록, !발굴 모두 동일한 펀더멘털 스코어 산출 함수(`screener.score_single_ticker`) 와 동일한 theme_context 생성 규칙(build_theme_context_entry)을 사용한다.
  - 동일 종목·동일 시점에서 세 진입점이 산출하는 점수/의견은 동일해야 한다.

R2. 코드 결정 / LLM 설명 분리
  - 의견 라벨(5단계 + 분석보류)은 코드가 결정한다(`derive_opinion_from_score`).
  - LLM 은 의견 라벨을 재선택하지 않는다.
  - LLM 은 '근거 설명 / 상승 조건 / 손절 조건' 세 항목 텍스트만 생성한다.
  - 최종 [한줄요약] 라인은 코드가 조립한다.

R3. AI sanity 검토 + 정성적 가중치 평가 (±2 확장)
  - 코드가 결정한 의견 라벨에 대해 AI 가 기본 ±1 단계, 강한 정성적 근거가 있는 경우 ±2 단계까지 보정 제안한다.
  - 보정 제안은 입력일 뿐이며, 최종 라벨은 코드가 `adjust_opinion_label` 로 결정한다.
  - 텔레그램(해외 변수)과 뉴스(국내 변수)가 동시 주입될 경우 두 변수의 정성적 가중치를 비교하여 delta 의 핵심 근거로 삼는다.
  - [폴백 정책]: AI 가 명확한 결론을 도출하지 못하면 `delta=0`, 사유는 `FALLBACK_REASON_AMBIGUOUS` 로 일관 로깅.

R4. 임계값 외부화
  - 의견 라벨 결정 임계값과 라벨 순서는 `src/utils/macro_triggers.py` 한 곳에 상수로 노출.

R5. theme_context 일관성
  - theme_context.json[ticker] 값은 `[테마: {target_theme} | 총점: {score}]\n{narrative}` 형식 유지.
  - 폴백 라벨: `!ai매수` → `AI매수(단일종목)`, `!수동등록` → `수동등록(단일종목)`.

R6. 외부 리서치/시황 컨텍스트 주입 (확장)
  - LLM 본문 작성 시 텔레그램 인사이트·국내 뉴스가 있으면 프롬프트에 주입.
  - 상충 시 종목 특성(수출주/내수주)에 따른 가중치를 서술에 명시.

R7. 5축 GARP 펀더멘털 채점 (v1.3 신규)
  - **하드 컷 폐기**: 거래대금 미달은 점수 0이 아니라 별도 라벨(`분석보류`)로 분리한다.
  - 5축 합산 100점 만점:
    1. **Value (밸류에이션)** 20점 — PER 단계 가점 + PBR 단계 가점.
    2. **Quality (수익성)** 20점 — ROE 절대값 단계 가점.
    3. **Growth (성장성)** 20점 — 매출증가율 + 영업이익증가율 + 턴어라운드.
    4. **Momentum (추세)** 20점 — 60일선/20일선 위치, 정배열.
    5. **Smart Money (수급)** 20점 — 외국인·기관 순매수 부호.
  - 금융주: Value 의 PER 항목을 ROE 가산으로 대체, 나머지 축 동일.
  - 데이터 부족(`current_price<=0`) 또는 거래대금 < 1억 → `score=None`, `unscorable_reason` 명시.

R8. 분석보류 / 유동성미달 라벨
  - `score=None` 인 경우 `derive_opinion_from_score(None)` 은 `OPINION_LABEL_HOLD = "분석보류"` 반환.
  - 슬랙 진입점은 보류 라벨 시 LLM 본문 호출은 진행하되, 매수 승인 버튼을 노출하지 않는다(`!ai매수`).
  - `!수동등록` 의 경우 보류 라벨이어도 사용자가 명시적으로 등록 의사를 표시했으므로 등록은 진행하되 reason 에 `[분석보류]` 태그를 포함한다.

2. 비기능 요구사항 (Non-Functional)

N1. 재현성
  - 같은 점수에서 같은 의견 라벨이 결정되어야 한다(LLM 비결정성 제거).
  - 5축 채점은 입력값이 같으면 항상 같은 점수.

N2. 토큰/속도 최적화
  - LLM 호출 횟수 증가 1회(`review_opinion_with_ai`) 이내로 제한.

N3. 하위 호환
  - `theme_context.json` 의 기존 키 포맷·파일 경로 유지.
  - `paper_trades.json` 기록 필드 유지(추가 필드만 신설).

3. 운영 제약
  - 임계값/라벨 변경은 `macro_triggers.py` 상수만 수정.
  - 점수 산출 로직 변경은 `screener.score_single_ticker` 한 곳만 수정.
  - 신규 진입점 추가 시 `_build_single_stock_report` 헬퍼 재사용.
