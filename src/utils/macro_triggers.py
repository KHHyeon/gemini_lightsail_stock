# -*- coding: utf-8 -*-
"""
매크로 트리거 임계값 및 평가 함수 단일 정의.

- Market Chronicles 의 T-Day 작성 트리거 (VIX>=25 또는 KOSPI/KOSDAQ 등락률
  절댓값 >=1.5%) 와 매크로 셧다운 단계 판정의 매직 넘버를 본 모듈로 통합.
- 호출부: chronicle_writer.should_write_chronicle / backfill._trigger_reason /
  chronicle_writer._build_keyphrases / backfill._build_keyphrases /
  context_retriever.extract_market_context / orchestrator.daily_routine.
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
