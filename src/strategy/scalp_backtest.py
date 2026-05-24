# -*- coding: utf-8 -*-
"""단타 전략 형태(Shape) 기반 백테스트.

실제 종목 가격·KIS API 없이 정규화된 1D 형태 벡터와 비율(ratio) 기반
가격 경로만으로 전략 유효성을 검증한다. 진입은 ``detect_pullback_signal`` +
``calculate_shape_similarity`` + ``determine_dynamic_threshold`` 파이프라인을
그대로 사용하고, 청산은 ``monitor_scalp_risk`` 3중 방어막 규칙을 ratio 경로에
적용한다.

참조: Doc/features/scalp_logic/01_scalp_logic_requirements.md R3, R5
"""

from __future__ import annotations

import os

import numpy as np

from src.strategy import scalp_logic
from src.utils.jsonio import read_local_json, write_local_json
from src.utils.paths import project_root
from src.utils.timekit import kst_iso_now

BACKTEST_RESULT_FILENAME = "scalp_backtest_result.json"

# 스케줄 등록 게이트 (형태 기반 백테스트 통과 기준)
GATE_MIN_WIN_RATE = 0.52
GATE_MIN_AVG_RETURN = 0.002  # 거래당 평균 +0.2% (ratio)
GATE_MIN_TOTAL_RETURN = 0.03  # 누적 +3% (ratio, 복리 아닌 단순 합)
GATE_MIN_TRADES = 20


def _result_path():
    return os.path.join(project_root(), BACKTEST_RESULT_FILENAME)


def _synthetic_pullback_ohlcv(*, pass_filter=True):
    """1차 필터용 합성 OHLCV. 가격 절대값은 임의 상수(검증에 무관)."""
    if pass_filter:
        return [{"close": 10_000, "tr_amount": 600_000_000}], 10_000
    return [{"close": 10_000, "tr_amount": 100_000_000}], 10_000


def _generate_shape_vector(rng, preset_matrix, profile):
    """후보 형태 벡터 생성.

    profile:
        - win_like: 프리셋 근접(고유사도 기대)
        - loss_like: 프리셋과 무관한 노이즈
        - marginal: 프리셋 + 큰 잡음(임계치 근처)
    """
    length = scalp_logic.SHAPE_VECTOR_LENGTH
    if profile == "win_like":
        idx = int(rng.integers(0, preset_matrix.shape[0]))
        noise = rng.normal(0.0, 0.012, size=length)
        return preset_matrix[idx] + noise
    if profile == "marginal":
        idx = int(rng.integers(0, preset_matrix.shape[0]))
        noise = rng.normal(0.0, 0.06, size=length)
        return preset_matrix[idx] + noise
    # loss_like
    return rng.uniform(0.0, 1.0, size=length)


def _build_ratio_path(rng, outcome):
    """진입 후 tick ratio 경로 생성 (매수가=1.0 고정).

    outcome: "win" | "loss" | "flat"
    """
    if outcome == "loss":
        return [1.0, 0.998, 0.993, 0.988, 0.984]
    if outcome == "flat":
        return [1.0, 1.002, 1.001, 0.999, 1.001, 1.0]
    # win: +3% 익절 후 추적 익절
    peak = 1.0 + scalp_logic.TAKE_PROFIT_RATIO + float(rng.uniform(0.005, 0.015))
    return [
        1.0, 1.005, 1.015, 1.025, 1.032,
        1.0 + scalp_logic.TAKE_PROFIT_RATIO,
        peak, peak * 0.995, peak * (1.0 + scalp_logic.TRAILING_STOP_RATIO - 0.002),
    ]


def simulate_trade_pnl_ratio(price_path_list):
    """ratio 경로에 3중 방어막을 적용하여 거래 손익 ratio 산출."""
    entry = 1.0
    avg = entry
    highest = entry
    half_sold = False
    realized = 0.0
    remaining = 1.0

    for price in price_path_list:
        highest = max(highest, float(price))
        sig = scalp_logic.monitor_scalp_risk(
            "BT", price, avg, highest, half_sold=half_sold,
        )
        if sig == "STOP_LOSS_1_5":
            realized += remaining * (float(price) / entry - 1.0)
            remaining = 0.0
            break
        if sig == "TAKE_PROFIT_HALF" and not half_sold:
            realized += 0.5 * (float(price) / entry - 1.0)
            remaining = 0.5
            half_sold = True
            continue
        if sig == "TRAILING_STOP" and half_sold:
            realized += remaining * (float(price) / entry - 1.0)
            remaining = 0.0
            break

    if remaining > 0:
        last_price = float(price_path_list[-1])
        realized += remaining * (last_price / entry - 1.0)
    return float(realized)


def _infer_outcome_from_similarity(similarity, threshold, rng):
    """유사도가 높을수록 win 경로 확률을 높인다(가격 무관 확률 모델)."""
    if similarity < threshold:
        return None  # 미진입
    margin = max(0.0, similarity - threshold)
    win_prob = min(0.85, 0.45 + margin * 2.5)
    roll = float(rng.random())
    if roll < win_prob:
        return "win"
    if roll < win_prob + 0.15:
        return "flat"
    return "loss"


def run_shape_backtest(*, n_days=60, seed=20260524, preset_seed=20260524):
    """형태 기반 백테스트 1회 실행.

    Args:
        n_days: 시뮬레이션 거래일 수.
        seed: 후보/경로 난수 시드.
        preset_seed: 프리셋 매트릭스 시드.

    Returns:
        dict: 통계 + passes_gate + trades 샘플.
    """
    rng = np.random.default_rng(seed)
    preset_matrix = scalp_logic.build_default_preset_matrix(seed=preset_seed)

    trade_list = []
    skipped = 0

    profile_cycle = ["win_like", "win_like", "marginal", "loss_like"]

    for day_idx in range(n_days):
        profile = profile_cycle[day_idx % len(profile_cycle)]
        passes_pb = profile != "loss_like"
        ohlcv_list, ma20 = _synthetic_pullback_ohlcv(pass_filter=passes_pb)
        pb = scalp_logic.detect_pullback_signal(ohlcv_list, ma20)
        if not pb["is_signal"]:
            skipped += 1
            continue

        shape_vec = _generate_shape_vector(rng, preset_matrix, profile)
        has_good_news = bool(rng.random() < 0.25)
        vix = float(rng.choice([15.0, 18.0, 22.0, 32.0], p=[0.4, 0.3, 0.2, 0.1]))
        threshold = scalp_logic.determine_dynamic_threshold(vix, has_good_news)
        similarity = scalp_logic.calculate_shape_similarity(shape_vec, preset_matrix)

        outcome = _infer_outcome_from_similarity(similarity, threshold, rng)
        if outcome is None:
            skipped += 1
            continue

        path = _build_ratio_path(rng, outcome)
        pnl_ratio = simulate_trade_pnl_ratio(path)
        trade_list.append({
            "day": day_idx + 1,
            "profile": profile,
            "similarity": round(similarity, 4),
            "threshold": threshold,
            "outcome_path": outcome,
            "pnl_ratio": round(pnl_ratio, 6),
            "is_win": pnl_ratio > 0,
        })

    total_trades = len(trade_list)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "skipped": skipped,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "total_return": 0.0,
            "passes_gate": False,
            "gate_reason": "진입 거래 0건",
            "trades": [],
        }

    win_count = sum(1 for t in trade_list if t["is_win"])
    win_rate = win_count / total_trades
    pnl_list = [t["pnl_ratio"] for t in trade_list]
    avg_return = float(np.mean(pnl_list))
    total_return = float(np.sum(pnl_list))

    passes = (
        total_trades >= GATE_MIN_TRADES
        and win_rate >= GATE_MIN_WIN_RATE
        and avg_return >= GATE_MIN_AVG_RETURN
        and total_return >= GATE_MIN_TOTAL_RETURN
    )
    gate_reason = "PASS" if passes else (
        f"기준 미달: trades={total_trades}, win_rate={win_rate:.2%}, "
        f"avg={avg_return:.4f}, total={total_return:.4f}"
    )

    return {
        "total_trades": total_trades,
        "skipped": skipped,
        "win_rate": round(win_rate, 4),
        "avg_return": round(avg_return, 6),
        "total_return": round(total_return, 6),
        "passes_gate": passes,
        "gate_reason": gate_reason,
        "gate_criteria": {
            "min_trades": GATE_MIN_TRADES,
            "min_win_rate": GATE_MIN_WIN_RATE,
            "min_avg_return": GATE_MIN_AVG_RETURN,
            "min_total_return": GATE_MIN_TOTAL_RETURN,
        },
        "trades": trade_list[:10],
    }


def run_and_persist(*, n_days=60, seed=20260524):
    """백테스트 실행 후 ``scalp_backtest_result.json`` 에 저장."""
    result = run_shape_backtest(n_days=n_days, seed=seed)
    result["run_at"] = kst_iso_now()
    result["mode"] = "shape_ratio_only"
    write_local_json(_result_path(), result)
    return result


def load_persisted_result():
    """저장된 백테스트 결과 로드."""
    data = read_local_json(_result_path(), default=None)
    return data if isinstance(data, dict) else None


def is_backtest_gate_passed(*, rerun_if_missing=True):
    """스케줄 등록 가능 여부. 파일 없으면 rerun_if_missing=True 시 1회 실행."""
    cached = load_persisted_result()
    if cached and "passes_gate" in cached:
        return bool(cached["passes_gate"])
    if rerun_if_missing:
        return bool(run_and_persist().get("passes_gate"))
    return False
