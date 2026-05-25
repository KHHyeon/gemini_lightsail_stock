# AI Investment Decision API Spec

## 구현율
- v1.3 (2026-05-25): 5축 GARP 채점 + 분석보류 라벨 + AI ±2 확장.

## 1. 임계값/라벨 API (src/utils/macro_triggers.py)

```python
OPINION_LABEL_HOLD = "분석보류"
OPINION_LABEL_DISAGREE = "매수반대"
OPINION_LABEL_NEUTRAL = "관망/주의"
OPINION_LABEL_CAUTION = "매수주의"
OPINION_LABEL_AGREE = "매수찬성"
OPINION_LABEL_STRONG = "매수적극찬성"

# (min_score, label) 내림차순. score=None 은 derive 함수가 별도 처리.
OPINION_THRESHOLDS_LIST = [
    (80, OPINION_LABEL_STRONG),
    (65, OPINION_LABEL_AGREE),
    (50, OPINION_LABEL_CAUTION),
    (35, OPINION_LABEL_NEUTRAL),
    (0,  OPINION_LABEL_DISAGREE),
]

# AI 보정 인접 이동 계산용. 분석보류는 보정 대상에서 제외.
OPINION_LABEL_ORDER = [
    OPINION_LABEL_DISAGREE,
    OPINION_LABEL_NEUTRAL,
    OPINION_LABEL_CAUTION,
    OPINION_LABEL_AGREE,
    OPINION_LABEL_STRONG,
]

MAX_OPINION_DELTA = 2  # AI 보정 최대 폭

derive_opinion_from_score(score) -> str
    # score None / 음수 / 비숫자 -> OPINION_LABEL_HOLD
    # 그 외 OPINION_THRESHOLDS_LIST 적용

adjust_opinion_label(label, delta) -> str
    # |delta| 는 MAX_OPINION_DELTA 로 클램프
    # label == OPINION_LABEL_HOLD 면 보정 적용하지 않고 그대로 반환
```

## 2. 펀더멘털 스코어 API (src/strategy/screener.py)

```python
score_single_ticker(ticker, name, base_url, app_key, secret_key, token,
                    target_theme=None) -> dict
```

반환 키 (모든 경로에서 dict 보장, 데이터 부족 시 unscorable):

```python
{
    "score": int | None,
    "score_details": list[str],
    "score_breakdown": {
        "value": int,
        "quality": int,
        "growth": int,
        "momentum": int,
        "smart_money": int,
    } | None,
    "unscorable_reason": str | None,
    "target_theme": str,
    "current_price": int,
    "pbr": float,
    "per": float,
    "roe": float,
    "is_financial": bool,
}
```

### 5축 채점 (비금융 기본)

| 축 | 만점 | 산식 |
|---|---|---|
| Value | 20 | PER 단계(≤8: +10, ≤12: +7, ≤18: +4, ≤25: +1) + PBR 단계(≤0.7: +10, ≤1.0: +7, ≤1.5: +4, ≤2.5: +1) |
| Quality | 20 | ROE ≥20: +20, ≥15: +15, ≥10: +10, ≥8: +6, ≥5: +3, ≥0: +1 |
| Growth | 20 | 매출증가율(≥10: +5, ≥5: +3, ≥0: +1) + 영업이익증가율(≥20: +10, ≥10: +6, ≥0: +3) + 턴어라운드 보너스 +5 |
| Momentum | 20 | 종가 ≥60일선: +10, 종가 ≥20일선: +5, 20일선 > 60일선: +5 |
| Smart Money | 20 | 외/기 둘 다 + : +20, 한쪽만 + : +10, 둘 다 - : 0 |

금융주: Value 의 PER 항목은 의미가 약하므로 ROE 가산점(+10)으로 대체.

### 보류 조건

- `current_price <= 0`: `unscorable_reason = "price_unavailable"`, `score=None`
- `tr_amount < 100_000_000` (1억): `unscorable_reason = "liquidity_too_low"`, `score=None`

(기존 10억 컷은 보류 라벨 적용으로 완화. 단 자동발굴 `run_3track_screener` 의 트랙별 유동성 컷은 유지.)

## 3. AI 결정 보조 API (src/strategy/ai_logic.py)

```python
review_opinion_with_ai(
    ticker, name, score, code_label, val, news, theme_context,
    *, telegram_insight_list=None, domestic_news_list=None,
    max_abs_delta=None,
) -> dict
```

- 반환: `{"delta": int (-max_abs_delta .. +max_abs_delta), "reason": str}`
- `max_abs_delta=None` 입력 시 `macro_triggers.MAX_OPINION_DELTA` (기본 2) 사용.
  운영중 1로 제한하고 싶을 때 `max_abs_delta=1` 명시 호출.
- AI 응답 토큰: `[유지] | [+1] | [-1] | [+2] | [-2]` (max_abs_delta 에 따라 토큰 가이드 동적 변경).
- `code_label == OPINION_LABEL_HOLD` 또는 `score is None` → AI 호출 스킵 →
  `{"delta": 0, "reason": "분석보류 - AI 보정 미적용"}`.

```python
get_multi_agent_investment_report(...) -> tuple[str, dict]
```

- `fundamental_score` 가 None 이면 LLM 본문 호출은 진행하되, opinion_code/opinion_final = `OPINION_LABEL_HOLD`, `[한줄요약]` 라인에 `[분석보류 - 사유: {unscorable_reason}]` 포함.

## 4. 슬랙 진입점 호출 규약 (src/utils/slack_interface.py)

`_build_single_stock_report(ticker, fallback_theme, strategy_label, say) -> dict`

신규 반환 키:
```python
{
    "ok": bool,
    "report": str,
    "score": int | None,
    "score_breakdown": dict | None,
    "unscorable_reason": str | None,
    "ctx_text": str,
    "val": dict,
    "target_theme": str,
    "opinion_code": str,
    "opinion_final": str,
    "opinion_delta": int,
    "ai_review_reason": str,
}
```

### `!ai매수`
- `opinion_final == OPINION_LABEL_HOLD` 이면 분석 결과만 안내, 승인 버튼 미노출.

### `!수동등록`
- 보류라도 등록 진행. reason 에 `[분석보류 - 사유]` 포함.

### `!발굴`
- `score=None` 이면 결과 메시지에서 `(분석보류: {reason})` 으로 표기.
