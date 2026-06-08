# -*- coding: utf-8 -*-
"""단타(Aggressive Day-Trading) 전략 모듈.

본 모듈은 3분봉 기반 20선 눌림목 1차 필터링과, 사전 내장된 '성공적인 20선 눌림목
프리셋 30종' 매트릭스 대비 형태 유사도(피어슨 상관계수) 산출, 그리고 3중 방어막
리스크 판정을 담당한다. 도메인 의사결정(주문 실행/슬랙 송신/영속화)은 호출자
(오케스트레이터)가 담당한다.

설계 원칙:
    - 1D 수치 배열의 피어슨 상관계수만 사용하여 LightSail CPU 부하 최소화.
    - 프리셋은 결정론적 형태 시드(상수)에서 생성하여 단위 테스트 재현성 보장.
    - AI 호출 0회. 호재 판정·뉴스 분석은 호출자가 ai_logic 을 통해 미리 수행한다.
    - 의견 라벨/매수 결정 등 도메인 의사결정 로직 포함 금지.

참조: Doc/features/scalp_logic/01_scalp_logic_requirements.md
"""

from __future__ import annotations

import math
import os
from datetime import time as _time

import numpy as np

from src.utils.timekit import KST, now_kst

# =====================================================================
# 가변 임계치 (Dynamic Threshold)
# =====================================================================
THRESHOLD_DEFAULT = 0.85  # 기본
THRESHOLD_AGGRESSIVE = 0.80  # 호재 뉴스 확인 시 (공격적 진입)
THRESHOLD_CONSERVATIVE = 0.90  # VIX 과열 시 (보수적 진입)
VIX_OVERHEAT = 30.0  # VIX 과열 기준

# =====================================================================
# 3중 방어막 리스크 임계치
# =====================================================================
STOP_LOSS_RATIO = -0.015  # 칼손절 -1.5%
TAKE_PROFIT_RATIO = 0.03  # 추적 익절 시작 +3%
TRAILING_STOP_RATIO = -0.01  # 추적 익절: 최고가 대비 -1%
FORCE_LIQUIDATION_HOUR = 15
FORCE_LIQUIDATION_MINUTE = 10

# =====================================================================
# 1차 필터: 거래대금 폭발 임계치
# =====================================================================
MIN_TR_AMOUNT_3MIN = 500_000_000  # 직전 3분 거래대금 5억원

# 형태 유사도 비교 벡터 길이(예: 3분봉 최근 20개 종가 + 20MA 기울기 + 거래량 추세 등).
SHAPE_VECTOR_LENGTH = 20


def determine_dynamic_threshold(vix_score, has_good_news):
    """시장 상황 + 뉴스 분석 결과로 동적 유사도 통과 임계값 결정.

    우선순위: VIX 과열(보수) > 호재 뉴스(공격) > 기본.
    상충 시 VIX 과열을 우선하여 위험 회피를 강제한다.

    Args:
        vix_score: 시장 공포지수 (float|None). None 이면 기본값 처리.
        has_good_news: 호재 뉴스 여부 (bool).

    Returns:
        float: ``THRESHOLD_CONSERVATIVE`` | ``THRESHOLD_AGGRESSIVE`` | ``THRESHOLD_DEFAULT``.
    """
    try:
        vix = float(vix_score) if vix_score is not None else 0.0
    except (TypeError, ValueError):
        vix = 0.0

    if vix >= VIX_OVERHEAT:
        return THRESHOLD_CONSERVATIVE
    if has_good_news:
        return THRESHOLD_AGGRESSIVE
    return THRESHOLD_DEFAULT


def calculate_shape_similarity(realtime_vector_list, preset_matrix):
    """실시간 1D 벡터와 프리셋 매트릭스 간 최대 피어슨 상관계수 산출.

    프리셋 매트릭스의 각 행(프리셋 하나)에 대해 상관계수를 계산하고 그 최대값을
    반환한다. 입력 분산이 0이거나 길이 불일치 시 0.0 폴백한다.

    Args:
        realtime_vector_list: 실시간 형태 벡터 (list|np.ndarray, 길이 ``SHAPE_VECTOR_LENGTH``).
        preset_matrix: 프리셋 매트릭스 (np.ndarray, shape=(N, SHAPE_VECTOR_LENGTH)).

    Returns:
        float: 0.0 ~ 1.0 사이의 최대 상관계수. 입력 부적합 시 0.0.
    """
    if realtime_vector_list is None or preset_matrix is None:
        return 0.0
    try:
        rt_vec = np.asarray(realtime_vector_list, dtype=float).ravel()
        pm = np.asarray(preset_matrix, dtype=float)
    except (TypeError, ValueError):
        return 0.0

    if rt_vec.ndim != 1 or pm.ndim != 2:
        return 0.0
    if rt_vec.size != pm.shape[1]:
        return 0.0
    if float(np.std(rt_vec)) == 0.0:
        return 0.0

    max_corr = 0.0
    for preset_vec in pm:
        if float(np.std(preset_vec)) == 0.0:
            continue
        corr_matrix = np.corrcoef(rt_vec, preset_vec)
        if corr_matrix.shape != (2, 2):
            continue
        corr_val = float(corr_matrix[0, 1])
        if math.isnan(corr_val):
            continue
        if corr_val > max_corr:
            max_corr = corr_val
    return float(max(0.0, min(1.0, max_corr)))


def build_default_preset_matrix(seed=20260524, count=30, length=SHAPE_VECTOR_LENGTH):
    """결정론적 '20선 눌림목 프리셋 30종' 합성 매트릭스 생성."""
    rng = np.random.default_rng(seed)
    preset_list = []
    for _ in range(count):
        peak_idx = rng.integers(3, 7)
        bottom_idx = rng.integers(10, 15)
        base = np.zeros(length, dtype=float)
        for i in range(peak_idx + 1):
            base[i] = 0.4 + i * (0.6 / max(peak_idx, 1))
        for i in range(peak_idx + 1, bottom_idx + 1):
            t = (i - peak_idx) / max(bottom_idx - peak_idx, 1)
            base[i] = 1.0 - t * 0.35
        for i in range(bottom_idx + 1, length):
            t = (i - bottom_idx) / max(length - bottom_idx - 1, 1)
            base[i] = 0.65 + t * 0.20
        noise = rng.normal(0.0, 0.015, size=length)
        preset_list.append(base + noise)
    return np.asarray(preset_list, dtype=float)


def evaluate_entry_candidate(
    ohlcv_3min_list,
    ma20,
    *,
    preset_matrix=None,
    vix_score=None,
    has_good_news=False,
):
    """S0->S3 진입 후보 평가 (단일 종목).

    Returns:
        dict: state(S0|S1|S2|S3), enter(bool), reason, similarity, threshold, shape_vector.
    """
    if preset_matrix is None:
        preset_matrix = build_default_preset_matrix()

    pullback = detect_pullback_signal(ohlcv_3min_list, ma20)
    if not pullback["is_signal"]:
        return {
            "state": "S0",
            "enter": False,
            "reason": pullback["reason"],
            "similarity": 0.0,
            "threshold": determine_dynamic_threshold(vix_score, has_good_news),
            "shape_vector": [],
        }

    shape_vector = extract_shape_vector_from_ohlcv(ohlcv_3min_list)
    similarity = calculate_shape_similarity(shape_vector, preset_matrix)
    threshold = determine_dynamic_threshold(vix_score, has_good_news)

    if similarity < threshold:
        return {
            "state": "S2",
            "enter": False,
            "reason": f"유사도 {similarity:.3f} < 임계치 {threshold:.2f}",
            "similarity": similarity,
            "threshold": threshold,
            "shape_vector": shape_vector,
        }

    return {
        "state": "S3",
        "enter": True,
        "reason": pullback["reason"],
        "similarity": similarity,
        "threshold": threshold,
        "shape_vector": shape_vector,
    }


def calc_market_buy_qty(budget_int, market_price):
    """예산 100% 시장가 매수 수량(floor)."""
    try:
        budget = int(budget_int)
        price = int(market_price)
    except (TypeError, ValueError):
        return 0
    if budget <= 0 or price <= 0:
        return 0
    return budget // price


def scalp_top_k():
    """Top-K 후보 랭킹 크기(.env `SCALP_TOP_K`, 기본 3)."""
    try:
        return max(1, int(os.getenv("SCALP_TOP_K", "3")))
    except (TypeError, ValueError):
        return 3


def scalp_similarity_soft_margin():
    """유사도 완화 폭(.env `SCALP_SIMILARITY_SOFT_MARGIN`, 기본 0.02)."""
    try:
        return max(0.0, float(os.getenv("SCALP_SIMILARITY_SOFT_MARGIN", "0.02")))
    except (TypeError, ValueError):
        return 0.02


def estimate_realized_volatility_ratio(ohlcv_3min_list, *, lookback=20):
    """최근 3분봉 종가 수익률 표준편차(비율) 추정."""
    if not ohlcv_3min_list:
        return 0.0
    close_list = [float(it.get("close", 0) or 0) for it in ohlcv_3min_list]
    close_list = close_list[-max(3, int(lookback)):]
    if len(close_list) < 3:
        return 0.0
    ret_list = []
    for prev, curr in zip(close_list[:-1], close_list[1:]):
        if prev <= 0 or curr <= 0:
            continue
        ret_list.append((curr - prev) / prev)
    if len(ret_list) < 2:
        return 0.0
    return float(np.std(np.asarray(ret_list, dtype=float)))


def calc_vol_targeted_buy_qty(
    budget_int,
    market_price,
    *,
    realized_vol_ratio,
    target_vol_ratio=0.012,
    min_scale=0.35,
    max_scale=1.0,
):
    """변동성 타깃 기반 시장가 수량 산출.

    realized_vol_ratio 가 target 보다 높을수록 포지션 크기를 줄인다.
    """
    base_qty = calc_market_buy_qty(budget_int, market_price)
    if base_qty <= 0:
        return 0, 0.0
    try:
        rv = float(realized_vol_ratio)
    except (TypeError, ValueError):
        rv = 0.0
    if rv <= 1e-9:
        scale = max_scale
    else:
        scale = target_vol_ratio / rv
        scale = max(min_scale, min(max_scale, scale))
    qty = int(base_qty * scale)
    if qty <= 0 and base_qty > 0:
        qty = 1
    return qty, float(scale)


def detect_pullback_signal(ohlcv_3min_list, ma20):
    """1차 필터: 거래대금 5억 + 20일선 눌림목 근접 감지.

    Args:
        ohlcv_3min_list: 3분봉 OHLCV dict 리스트.
            각 dict 키: open, high, low, close, volume, tr_amount(원). 최소 1개 필요.
        ma20: 3분봉 기준 20MA 가격(float).

    Returns:
        dict: ``{"is_signal": bool, "reason": str}``.
    """
    if not ohlcv_3min_list or ma20 is None or float(ma20) <= 0:
        return {"is_signal": False, "reason": "데이터 부족"}

    last = ohlcv_3min_list[-1]
    tr_amount = float(last.get("tr_amount", 0) or 0)
    if tr_amount < MIN_TR_AMOUNT_3MIN:
        return {"is_signal": False, "reason": f"거래대금 미달({tr_amount:.0f})"}

    close = float(last.get("close", 0) or 0)
    if close <= 0:
        return {"is_signal": False, "reason": "현재가 비정상"}

    # 20MA 근접도 ±1% 이내를 '눌림목 도달'로 정의.
    diff_ratio = (close - float(ma20)) / float(ma20)
    if abs(diff_ratio) > 0.01:
        return {"is_signal": False, "reason": f"20MA 이격 {diff_ratio*100:.2f}%"}

    return {
        "is_signal": True,
        "reason": f"거래대금 {tr_amount/1e8:.1f}억 + 20MA 근접 {diff_ratio*100:+.2f}%",
    }


def monitor_scalp_risk(ticker, current_price, avg_buy_price, highest_price,
                       *, half_sold=False):
    """3중 방어막 리스크 검사 (S4 단계).

    시간 기반 강제 청산은 별도 ``is_force_liquidation_time`` 으로 분리한다.

    Args:
        ticker: 종목코드(로그용).
        current_price: 현재가.
        avg_buy_price: 평균 매수가.
        highest_price: 보유 기간 최고가(추적용).
        half_sold: 50% 익절 후 잔여 추적 상태인지 여부.

    Returns:
        str: ``"HOLD" | "STOP_LOSS_1_5" | "TAKE_PROFIT_HALF" | "TRAILING_STOP"``.
    """
    try:
        curr = float(current_price)
        avg = float(avg_buy_price)
    except (TypeError, ValueError):
        return "HOLD"

    if avg <= 0 or curr <= 0:
        return "HOLD"

    # 칼손절 (최우선)
    if curr <= avg * (1.0 + STOP_LOSS_RATIO):
        return "STOP_LOSS_1_5"

    # 추적 익절 잔여 단계
    if half_sold:
        try:
            peak = float(highest_price) if highest_price else curr
        except (TypeError, ValueError):
            peak = curr
        if peak > 0 and curr <= peak * (1.0 + TRAILING_STOP_RATIO):
            return "TRAILING_STOP"
        return "HOLD"

    # 50% 익절 진입 조건
    if curr >= avg * (1.0 + TAKE_PROFIT_RATIO):
        return "TAKE_PROFIT_HALF"

    return "HOLD"


def is_force_liquidation_time(now=None):
    """15:10 KST 강제 청산 시각 도달 여부."""
    current = now if now is not None else now_kst()
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    target = _time(FORCE_LIQUIDATION_HOUR, FORCE_LIQUIDATION_MINUTE, 0)
    return current.timetz().replace(tzinfo=None) >= target


def extract_shape_vector_from_ohlcv(ohlcv_list, length=SHAPE_VECTOR_LENGTH):
    """3분봉 OHLCV 리스트에서 형태 비교용 1D 벡터 추출.

    - 종가 시계열을 [0, 1] 스케일로 정규화.
    - 길이 부족 시 앞 0 패딩, 초과 시 최근 length 개만 사용.

    AI 학습 데이터 적재(scalp_trainer.record_trade_result)와 동일 포맷.
    """
    if not ohlcv_list:
        return [0.0] * length
    close_list = [float(it.get("close", 0) or 0) for it in ohlcv_list]
    close_list = close_list[-length:]
    if len(close_list) < length:
        close_list = [0.0] * (length - len(close_list)) + close_list
    arr = np.asarray(close_list, dtype=float)
    if arr.size == 0:
        return [0.0] * length
    mn = float(np.min(arr))
    mx = float(np.max(arr))
    if mx - mn <= 1e-12:
        return [0.0] * length
    normalized = (arr - mn) / (mx - mn)
    return normalized.tolist()
