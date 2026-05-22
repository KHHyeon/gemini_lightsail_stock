# AI Investment Decision (Feature Index)

## 기능 요약
`!ai매수`, `!수동등록`, `!발굴` 세 진입점에서 발생하는 매수 판단 흐름을
"코드 결정 + LLM 근거 설명"의 2-Layer 구조로 표준화한다.

- 펀더멘털 점수: 코드(`screener.score_single_ticker`)가 100점 만점으로 산출
- 의견 라벨: 코드(`macro_triggers.derive_opinion_from_score`)가 임계값으로 결정
- AI 보정: 1회 sanity check 만 허용(±1단계, `review_opinion_with_ai`)
- LLM 본문: '근거 설명/상승조건/손절조건' 만 담당, 의견 라벨 재선택 금지
- theme_context: `build_theme_context_entry` 단일 규칙으로 생성·저장

## 목표
- 진입점(`!ai매수`/`!수동등록`/`!발굴`) 사이의 의견·점수 일관성 확보.
- 매수 결정의 재현성(코드가 결정, LLM은 설명)을 강제.
- 임계값을 `macro_triggers.py` 한 곳에서 튜닝 가능하도록 통합.

## 문서 인덱스
- `01_requirements.md`: 기능 요구사항·제약·운영 규칙
- `02_api_spec.md`: 공개 API/시그니처/입출력 규약
- `03_state_logic.md`: 상태 전이·점수 산출·의견 라벨 결정 로직

## 핵심 흐름
1. 진입점 명령 수신 (`!ai매수`/`!수동등록`/`!발굴`)
2. 펀더멘털 점수 산출 (`score_single_ticker` 또는 `run_unified_screener`)
3. 의견 라벨 1차 결정 (코드, `derive_opinion_from_score`)
4. AI sanity 검토 (`review_opinion_with_ai` → ±1 단계 delta)
5. 의견 라벨 최종 결정 (코드, `adjust_opinion_label(label, delta)`)
6. `theme_context` 단일 규칙 생성·저장 (`build_theme_context_entry`)
7. 멀티 에이전트 리포트 + 코드가 조립한 `[한줄요약]` 라인 출력
