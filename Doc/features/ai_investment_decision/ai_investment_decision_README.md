# AI Investment Decision (Feature Index)

## 구현율
- v1.3 (2026-05-25): 5축 GARP 채점 + 분석보류 라벨 + AI ±2 확장 — 100% 설계, 100% 구현.

## 기능 요약
`!ai매수`, `!수동등록`, `!발굴` 세 진입점에서 발생하는 매수 판단 흐름을
"코드 결정 + LLM 근거 설명"의 2-Layer 구조로 표준화한다.

- 펀더멘털 점수: 코드(`screener.score_single_ticker`)가 **5축 GARP 100점**으로 산출
  - 5축: Value(20) + Quality(20) + Growth(20) + Momentum(20) + Smart Money(20)
  - 데이터 부족/유동성 미달은 `score=None` + `unscorable_reason` 반환 → **분석보류** 라벨
- 의견 라벨(6단계): 코드(`macro_triggers.derive_opinion_from_score`)가 임계값으로 결정
  - `분석보류 / 매수반대 / 관망/주의 / 매수주의 / 매수찬성 / 매수적극찬성`
- AI 보정: 1회 sanity check (`review_opinion_with_ai`, **±2 단계 이내**)
  - 분석보류는 AI 호출 자체를 스킵하여 토큰 절약.
- LLM 본문: '근거 설명/상승조건/손절조건' 만 담당, 의견 라벨 재선택 금지.
- `!ai매수` 분석보류 시 매수 승인 버튼을 노출하지 않는다.

## 목표
- 진입점(`!ai매수`/`!수동등록`/`!발굴`) 사이의 의견·점수 일관성 확보.
- 매수 결정의 재현성(코드가 결정, LLM은 설명)을 강제.
- 데이터 부족 종목을 0점/매수반대로 처리하지 않고 별도 라벨(`분석보류`)로 분기.
- 임계값을 `macro_triggers.py` 한 곳에서 튜닝 가능하도록 통합.

## 문서 인덱스
- `01_requirements.md`: 기능 요구사항·제약·운영 규칙
- `02_api_spec.md`: 공개 API/시그니처/입출력 규약
- `03_state_logic.md`: 상태 전이·점수 산출·의견 라벨 결정 로직

## 핵심 흐름
1. 진입점 명령 수신 (`!ai매수`/`!수동등록`/`!발굴`)
2. 펀더멘털 점수 산출 (`score_single_ticker` 또는 `run_unified_screener`)
   - 5축 채점. 데이터 부족 시 `score=None` + `unscorable_reason`.
3. 의견 라벨 1차 결정 (코드, `derive_opinion_from_score`)
   - `score=None` → `OPINION_LABEL_HOLD`
4. AI sanity 검토 (`review_opinion_with_ai` → ±2 단계 delta)
   - 분석보류 시 스킵.
5. 의견 라벨 최종 결정 (코드, `adjust_opinion_label(label, delta)`)
6. `theme_context` 단일 규칙 생성·저장 (`build_theme_context_entry`)
7. 멀티 에이전트 리포트 + 코드가 조립한 `[한줄요약]` 라인 출력
   - 분석보류 시 `[의견: 분석보류 - {unscorable_reason}] | [점수: N/A]` 양식.
