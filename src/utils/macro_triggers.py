# -*- coding: utf-8 -*-
"""
매크로 트리거 임계값 및 평가 함수 단일 정의.

- Market Chronicles 의 T-Day 작성 트리거 (VIX>=25 또는 KOSPI/KOSDAQ 등락률
  절댓값 >=1.5%) 와 매크로 셧다운 단계 판정의 매직 넘버를 본 모듈로 통합.
- 호출부: chronicle_writer.should_write_chronicle / backfill._trigger_reason /
  chronicle_writer._build_keyphrases / backfill._build_keyphrases /
  context_retriever.extract_market_context / orchestrator.daily_routine.

v3.4 추가: ``resolve_regime`` 및 ``REGIME_NEIGHBOR_MAP`` 을 도입하여
``market_state.regime`` 표준 enum 산출 + 인접 그룹 매칭을 단일 진입점으로
통합한다. 정의는 DETAIL CHRONICLES §5.1.3 참조.
"""

# T-Day 크로니클 트리거 (DETAIL CHRONICLES §1.4 참조)
VIX_WARN = 25.0  # 공포 확대 경계
INDEX_SHOCK_PCT = 1.5  # KOSPI / KOSDAQ 등락률 임계값 (퍼센트)

# 매크로 셧다운 단계 임계값 (SYS §3.2, GEMINI.md §1 주요 기능 참조)
VIX_CRITICAL = 30.0  # Level 1: 신규 매수 전면 중단
WTI_CRITICAL = 95.0
WTI_WARN = 90.0
TREASURY_CRITICAL = 4.8  # 미 국채 10년물 (%)
TREASURY_WARN = 4.5

# 셧다운 레벨 라벨 (외부 사용처 가독성용)
SHUTDOWN_LEVEL_NONE = 0  # 평상 운영
SHUTDOWN_LEVEL_HALF = 1  # 매수 예산 50% 축소
SHUTDOWN_LEVEL_FULL = 2  # 매수 전면 중단

# v3.4 표준 regime enum (8종, DETAIL CHRONICLES §5.1.3)
REGIME_PANIC_SELL = "PANIC_SELL"
REGIME_FEAR_EXTREME = "FEAR_EXTREME"
REGIME_FEAR_RISING = "FEAR_RISING"
REGIME_SHOCK_OPEN = "SHOCK_OPEN"
REGIME_BULLISH_RALLY = "BULLISH_RALLY"
REGIME_GREED_EXTREME = "GREED_EXTREME"
REGIME_TECH_REBOUND = "TECH_REBOUND"
REGIME_SIDEWAYS = "SIDEWAYS"

REGIME_ENUM_SET = {
    REGIME_PANIC_SELL,
    REGIME_FEAR_EXTREME,
    REGIME_FEAR_RISING,
    REGIME_SHOCK_OPEN,
    REGIME_BULLISH_RALLY,
    REGIME_GREED_EXTREME,
    REGIME_TECH_REBOUND,
    REGIME_SIDEWAYS,
}

# 인접 그룹 매핑 — context_retriever._score_entry 단계 3 에서 +2.0 보너스 산정.
# 같은 강도·방향 계열은 서로 인접으로 간주한다 (DETAIL §5.1.3(3) 참조).
REGIME_NEIGHBOR_MAP = {
    REGIME_PANIC_SELL: [REGIME_FEAR_EXTREME, REGIME_SHOCK_OPEN],
    REGIME_FEAR_EXTREME: [REGIME_PANIC_SELL, REGIME_FEAR_RISING],
    REGIME_FEAR_RISING: [REGIME_FEAR_EXTREME, REGIME_SHOCK_OPEN, REGIME_SIDEWAYS],
    REGIME_SHOCK_OPEN: [REGIME_PANIC_SELL, REGIME_FEAR_RISING, REGIME_TECH_REBOUND],
    REGIME_BULLISH_RALLY: [REGIME_GREED_EXTREME, REGIME_TECH_REBOUND],
    REGIME_GREED_EXTREME: [REGIME_BULLISH_RALLY],
    REGIME_TECH_REBOUND: [REGIME_BULLISH_RALLY, REGIME_SIDEWAYS, REGIME_SHOCK_OPEN],
    REGIME_SIDEWAYS: [REGIME_TECH_REBOUND, REGIME_FEAR_RISING],
}

# v1 자유형 → enum 1차 매핑 키워드 사전 (DETAIL §5.1.3(4)).
# 우선순위: 상위 키워드 매칭이 강한 강도이며, 다중 매칭 시 가장 강한 강도 채택.
REGIME_KEYWORD_PRIORITY_LIST = [
    (REGIME_PANIC_SELL, ["패닉셀", "panic", "투매", "급락"]),
    (REGIME_FEAR_EXTREME, ["공포 확대", "공포확대", "극심한 변동성", "vix 27"]),
    (REGIME_SHOCK_OPEN, ["갭다운", "쇼크 개장", "갭하락", "shock open"]),
    (REGIME_FEAR_RISING, ["공포", "긴축", "리스크오프", "위험회피"]),
    (REGIME_GREED_EXTREME, ["과열", "광기", "버블", "탐욕"]),
    (REGIME_BULLISH_RALLY, ["상승", "랠리", "강세", "rally"]),
    (REGIME_TECH_REBOUND, ["반등", "기술적 반등", "되돌림"]),
    (REGIME_SIDEWAYS, ["횡보", "박스", "관망", "혼조"]),
]


def resolve_regime(vix, kospi_chg, kosdaq_chg, open_chg=None, prev_regime=None):
    """매크로 1차 트리거로 표준 regime enum 1종을 결정한다.

    DETAIL CHRONICLES §5.1.3(1)~(2) 의 우선순위를 코드로 옮긴 단일 진입점이다.

    Args:
        vix: VIX 종가 (float|None).
        kospi_chg: KOSPI 일간 등락률 (%) (float|None).
        kosdaq_chg: KOSDAQ 일간 등락률 (%) (float|None).
        open_chg: 시초가 갭 등락률 (%). 별도 데이터가 없으면 None.
        prev_regime: 직전 영업일 regime enum (옵션). 일부 모호 케이스의
            안전 폴백에 사용 (예: VIX 만 살짝 상승 + 지수는 무변동 → 직전
            regime 유지).

    Returns:
        str: REGIME_ENUM_SET 중 한 값.
    """
    vix_v = _safe_float(vix)
    kospi_v = _safe_float(kospi_chg)
    kosdaq_v = _safe_float(kosdaq_chg)
    open_v = _safe_float(open_chg) if open_chg is not None else 0.0

    if open_v <= -2.0:
        return REGIME_SHOCK_OPEN

    worst_chg = min(kospi_v, kosdaq_v)
    best_chg = max(kospi_v, kosdaq_v)

    if vix_v >= 30.0 and worst_chg <= -1.5:
        return REGIME_PANIC_SELL
    if vix_v >= 27.0:
        return REGIME_FEAR_EXTREME

    if best_chg >= 2.0 and vix_v < 18.0:
        return REGIME_BULLISH_RALLY
    if vix_v <= 13.0 and best_chg >= 0.5:
        return REGIME_GREED_EXTREME

    if worst_chg <= -1.5 and vix_v >= VIX_WARN:
        return REGIME_FEAR_RISING

    if best_chg >= 1.0 and prev_regime in {
        REGIME_PANIC_SELL,
        REGIME_FEAR_EXTREME,
        REGIME_FEAR_RISING,
        REGIME_SHOCK_OPEN,
    }:
        return REGIME_TECH_REBOUND

    return REGIME_SIDEWAYS


def map_regime_from_text(free_text):
    """v1 자유형 regime 문자열을 표준 enum 1종으로 1차 매핑한다.

    Args:
        free_text: v1 엔트리의 ``regime`` 자유형 문자열 (예: "공포 확대").

    Returns:
        str|None: 매칭된 enum. 매칭 0건이면 None.
    """
    if not free_text:
        return None
    lowered = str(free_text).lower()
    for enum_value, keyword_list in REGIME_KEYWORD_PRIORITY_LIST:
        for keyword in keyword_list:
            if keyword in lowered or keyword in str(free_text):
                return enum_value
    return None


def _safe_float(value, default=0.0):
    """문자열·None 안전 float 변환."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_chronicle_trigger(vix, kospi_chg, kosdaq_chg):
    """T-Day 크로니클 작성 트리거 평가.

    Returns:
        tuple[bool, str]: (트리거 여부, 사유 문자열). 사유는 슬랙·리포트
        헤더에 그대로 노출되므로 사람이 읽기 쉬운 형태로 반환한다.
    """
    vix_v = _safe_float(vix)
    kospi_v = _safe_float(kospi_chg)
    kosdaq_v = _safe_float(kosdaq_chg)

    if vix_v >= VIX_WARN:
        return True, f"VIX {vix_v:.1f}"
    if abs(kospi_v) >= INDEX_SHOCK_PCT:
        return True, f"KOSPI {kospi_v:+.2f}%"
    if abs(kosdaq_v) >= INDEX_SHOCK_PCT:
        return True, f"KOSDAQ {kosdaq_v:+.2f}%"
    return False, ""


# =====================================================================
# 펀더멘털 점수 → 의견 라벨 (코드 결정, LLM 비참여)
# =====================================================================
#
# Doc/features/ai_investment_decision/03_state_logic.md §1 참조.
# 임계값/라벨 변경은 본 파일에서만 수행한다. LLM 은 본 라벨을 재선택할 수 없으며,
# review_opinion_with_ai 의 ±1 단계 보정 제안만 입력으로 사용된다.

OPINION_LABEL_DISAGREE = "매수반대"
OPINION_LABEL_NEUTRAL = "관망/주의"
OPINION_LABEL_CAUTION = "매수주의"
OPINION_LABEL_AGREE = "매수찬성"
OPINION_LABEL_STRONG = "매수적극찬성"

# (min_score, label) 의 내림차순 리스트.
OPINION_THRESHOLDS_LIST = [
    (85, OPINION_LABEL_STRONG),
    (70, OPINION_LABEL_AGREE),
    (60, OPINION_LABEL_CAUTION),
    (50, OPINION_LABEL_NEUTRAL),
    (0, OPINION_LABEL_DISAGREE),
]

# 낮은 강도 → 높은 강도 정렬 라벨 리스트 (인접 보정 계산용).
OPINION_LABEL_ORDER = [
    OPINION_LABEL_DISAGREE,
    OPINION_LABEL_NEUTRAL,
    OPINION_LABEL_CAUTION,
    OPINION_LABEL_AGREE,
    OPINION_LABEL_STRONG,
]


def derive_opinion_from_score(score):
    """펀더멘털 점수 → 의견 라벨 1종.

    Args:
        score: 정수/실수/문자열 형태의 점수. 변환 실패 시 0 으로 간주.

    Returns:
        str: ``OPINION_LABEL_ORDER`` 중 1개.
    """
    s = _safe_float(score, default=0.0)
    for min_s, label in OPINION_THRESHOLDS_LIST:
        if s >= min_s:
            return label
    return OPINION_THRESHOLDS_LIST[-1][1]


def adjust_opinion_label(label, delta):
    """의견 라벨을 ±N 단계 보정한다.

    AI sanity 검토(``review_opinion_with_ai``) 의 delta 를 코드가 적용할 때 사용한다.
    범위를 벗어나면 양 끝 라벨로 클램프한다.

    Args:
        label: ``OPINION_LABEL_ORDER`` 중 1개.
        delta: 정수. 양수면 강도 상향, 음수면 하향.

    Returns:
        str: 보정 후 라벨. 입력 라벨이 미등록이면 입력값 그대로 반환.
    """
    if label not in OPINION_LABEL_ORDER:
        return label
    try:
        d = int(delta)
    except (TypeError, ValueError):
        d = 0
    idx = OPINION_LABEL_ORDER.index(label)
    new_idx = max(0, min(len(OPINION_LABEL_ORDER) - 1, idx + d))
    return OPINION_LABEL_ORDER[new_idx]


def evaluate_macro_shutdown_level(vix, wti, treasury_yield):
    """매크로 셧다운 단계 평가 (0=평상, 1=Half-Buy, 2=Shutdown).

    가장 강한 조건이 우선한다(Level 2 > Level 1).
    """
    vix_v = _safe_float(vix)
    wti_v = _safe_float(wti)
    treasury_v = _safe_float(treasury_yield)

    if (
        vix_v >= VIX_CRITICAL
        or wti_v >= WTI_CRITICAL
        or treasury_v >= TREASURY_CRITICAL
    ):
        return SHUTDOWN_LEVEL_FULL
    if vix_v >= VIX_WARN or wti_v >= WTI_WARN or treasury_v >= TREASURY_WARN:
        return SHUTDOWN_LEVEL_HALF
    return SHUTDOWN_LEVEL_NONE
