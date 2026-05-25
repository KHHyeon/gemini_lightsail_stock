# -*- coding: utf-8 -*-
"""AI Investment Decision v1.3 (5축 GARP + 분석보류 + ±2) 단위 테스트.

실행: venv/bin/python3 tests/temp_test_investment_decision.py

본 테스트는 외부 네트워크/KIS API 호출 없이 순수 함수 단위로 동작한다.
- macro_triggers: 임계값/라벨/보정 동작
- screener (5축 채점 헬퍼): 데이터 입력값에 따른 점수 분포
- ai_logic.review_opinion_with_ai: ±2 토큰 인식, 분석보류 스킵
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.utils import macro_triggers as mt
from src.strategy import screener as scr
from src.strategy import ai_logic


class TestOpinionLabelDerivation(unittest.TestCase):
    """derive_opinion_from_score / adjust_opinion_label 단위 테스트."""

    def test_score_none_returns_hold(self):
        self.assertEqual(mt.derive_opinion_from_score(None), mt.OPINION_LABEL_HOLD)

    def test_invalid_score_returns_hold(self):
        self.assertEqual(mt.derive_opinion_from_score("N/A"), mt.OPINION_LABEL_HOLD)
        self.assertEqual(mt.derive_opinion_from_score(-1), mt.OPINION_LABEL_HOLD)

    def test_threshold_boundaries(self):
        cases = {
            85: mt.OPINION_LABEL_STRONG,
            80: mt.OPINION_LABEL_STRONG,
            79: mt.OPINION_LABEL_AGREE,
            65: mt.OPINION_LABEL_AGREE,
            64: mt.OPINION_LABEL_CAUTION,
            50: mt.OPINION_LABEL_CAUTION,
            49: mt.OPINION_LABEL_NEUTRAL,
            35: mt.OPINION_LABEL_NEUTRAL,
            34: mt.OPINION_LABEL_DISAGREE,
            0: mt.OPINION_LABEL_DISAGREE,
        }
        for score, expected in cases.items():
            self.assertEqual(
                mt.derive_opinion_from_score(score), expected,
                msg=f"score={score} expected={expected}",
            )

    def test_adjust_label_hold_is_immutable(self):
        # 분석보류 라벨은 보정 대상이 아니다.
        self.assertEqual(
            mt.adjust_opinion_label(mt.OPINION_LABEL_HOLD, +2),
            mt.OPINION_LABEL_HOLD,
        )
        self.assertEqual(
            mt.adjust_opinion_label(mt.OPINION_LABEL_HOLD, -2),
            mt.OPINION_LABEL_HOLD,
        )

    def test_adjust_label_clamps_to_max_delta(self):
        # ±MAX_OPINION_DELTA 초과는 클램프.
        base = mt.OPINION_LABEL_CAUTION  # idx=2 in OPINION_LABEL_ORDER
        # +5 → +MAX_OPINION_DELTA (2) → idx 4 (STRONG)
        self.assertEqual(
            mt.adjust_opinion_label(base, +5),
            mt.OPINION_LABEL_STRONG,
        )
        # -5 → -MAX_OPINION_DELTA (2) → idx 0 (DISAGREE)
        self.assertEqual(
            mt.adjust_opinion_label(base, -5),
            mt.OPINION_LABEL_DISAGREE,
        )

    def test_adjust_label_normal_delta(self):
        self.assertEqual(
            mt.adjust_opinion_label(mt.OPINION_LABEL_CAUTION, +1),
            mt.OPINION_LABEL_AGREE,
        )
        self.assertEqual(
            mt.adjust_opinion_label(mt.OPINION_LABEL_CAUTION, +2),
            mt.OPINION_LABEL_STRONG,
        )
        self.assertEqual(
            mt.adjust_opinion_label(mt.OPINION_LABEL_AGREE, -1),
            mt.OPINION_LABEL_CAUTION,
        )


class TestScoringAxes(unittest.TestCase):
    """5축 채점 헬퍼 단위 테스트."""

    def test_value_axis_low_per_pbr_full(self):
        pts, _ = scr._score_value(per=6.0, pbr=0.5, is_financial=False)
        self.assertEqual(pts, 20)

    def test_value_axis_high_per_pbr_zero(self):
        pts, _ = scr._score_value(per=40.0, pbr=3.5, is_financial=False)
        self.assertEqual(pts, 0)

    def test_value_axis_financial_skips_per(self):
        # 금융주는 PER 가산점 미적용, PBR 만 평가.
        pts, _ = scr._score_value(per=5.0, pbr=0.5, is_financial=True)
        self.assertEqual(pts, 10)

    def test_quality_axis_roe_tiers(self):
        self.assertEqual(scr._score_quality(25.0, False)[0], 20)
        self.assertEqual(scr._score_quality(16.0, False)[0], 15)
        self.assertEqual(scr._score_quality(12.0, False)[0], 10)
        self.assertEqual(scr._score_quality(9.0, False)[0], 6)
        self.assertEqual(scr._score_quality(6.0, False)[0], 3)
        self.assertEqual(scr._score_quality(1.0, False)[0], 1)
        self.assertEqual(scr._score_quality(-1.0, False)[0], 0)

    def test_quality_axis_financial_bonus(self):
        # 금융주 ROE 8 이상 → +10 보너스.
        base, _ = scr._score_quality(10.0, False)  # 10
        boosted, _ = scr._score_quality(10.0, True)  # 10 + 10
        self.assertEqual(boosted - base, 10)

    def test_growth_axis_full(self):
        pts, _ = scr._score_growth(sales_growth=12.0, op_growth=25.0, turnaround=True)
        self.assertEqual(pts, 20)  # 5+10+5, 그러나 max=20

    def test_growth_axis_negative(self):
        pts, _ = scr._score_growth(sales_growth=-5.0, op_growth=-10.0, turnaround=False)
        self.assertEqual(pts, 0)

    def test_momentum_axis_full(self):
        # 60 캔들. 최신가 > 20일선 > 60일선.
        ohlcv = [{"close": 110}] * 1 + [{"close": 105}] * 19 + [{"close": 100}] * 40
        pts, _ = scr._score_momentum(ohlcv)
        self.assertEqual(pts, 20)

    def test_momentum_axis_below_ma(self):
        ohlcv = [{"close": 90}] * 1 + [{"close": 100}] * 59
        pts, _ = scr._score_momentum(ohlcv)
        self.assertEqual(pts, 0)

    def test_momentum_axis_insufficient_data(self):
        pts, _ = scr._score_momentum([{"close": 100}] * 30)
        self.assertEqual(pts, 0)

    def test_smart_money_axis(self):
        self.assertEqual(scr._score_smart_money(1000, 1000)[0], 20)
        self.assertEqual(scr._score_smart_money(1000, -1000)[0], 10)
        self.assertEqual(scr._score_smart_money(-1000, -1000)[0], 0)


class TestScoreSingleTickerBehavior(unittest.TestCase):
    """score_single_ticker 의 분석보류 분기 및 보류 사유 테스트."""

    def _patch_kis(self, val_dict, frgn=0, orgn=0, ohlcv=None,
                   growth=(0.0, 0.0, False)):
        ohlcv = ohlcv or []
        return [
            patch.object(scr, "get_basic_valuation", return_value=val_dict),
            patch.object(scr, "get_smart_money_accumulation",
                         return_value=(frgn, orgn)),
            patch.object(scr, "get_kis_growth_metrics", return_value=growth),
            patch.object(scr.chart_data, "get_daily_ohlcv", return_value=ohlcv),
        ]

    def test_price_unavailable_returns_hold(self):
        val = {"current_price": 0, "pbr": 0.0, "per": 0.0,
               "roe": 0.0, "tr_amount": 0, "dvd_yld": 0.0}
        patches = self._patch_kis(val)
        for p in patches:
            p.start()
        try:
            res = scr.score_single_ticker(
                "000001", "TestCo", "u", "k", "s", "t",
            )
            self.assertIsNone(res["score"])
            self.assertEqual(res["unscorable_reason"], "price_unavailable")
        finally:
            for p in patches:
                p.stop()

    def test_liquidity_below_threshold_returns_hold(self):
        val = {"current_price": 1000, "pbr": 1.0, "per": 10.0,
               "roe": 10.0, "tr_amount": 50_000_000, "dvd_yld": 0.0}
        patches = self._patch_kis(val)
        for p in patches:
            p.start()
        try:
            res = scr.score_single_ticker(
                "000002", "TestCo", "u", "k", "s", "t",
            )
            self.assertIsNone(res["score"])
            self.assertEqual(res["unscorable_reason"], "liquidity_too_low")
        finally:
            for p in patches:
                p.stop()

    def test_normal_path_returns_int_score(self):
        val = {"current_price": 10000, "pbr": 0.8, "per": 10.0,
               "roe": 15.0, "tr_amount": 5_000_000_000, "dvd_yld": 2.0}
        ohlcv = [{"close": 11000}] * 1 + [{"close": 10500}] * 19 + [{"close": 9500}] * 40
        patches = self._patch_kis(
            val, frgn=1000, orgn=1000, ohlcv=ohlcv,
            growth=(12.0, 25.0, False),
        )
        for p in patches:
            p.start()
        try:
            res = scr.score_single_ticker(
                "000003", "GoodCo", "u", "k", "s", "t",
            )
            self.assertIsNotNone(res["score"])
            self.assertIsInstance(res["score"], int)
            self.assertGreater(res["score"], 80)  # 5축 풀스코어 근접
            self.assertIsNone(res["unscorable_reason"])
            self.assertIsNotNone(res["score_breakdown"])
            self.assertIn("value", res["score_breakdown"])
            self.assertIn("quality", res["score_breakdown"])
            self.assertIn("growth", res["score_breakdown"])
            self.assertIn("momentum", res["score_breakdown"])
            self.assertIn("smart_money", res["score_breakdown"])
        finally:
            for p in patches:
                p.stop()


class TestReviewOpinionWithAI(unittest.TestCase):
    """review_opinion_with_ai 의 ±2 토큰 인식 및 분석보류 스킵 테스트."""

    def test_hold_label_skips_ai_call(self):
        with patch.object(ai_logic, "generate_text") as mock_gen:
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", None, mt.OPINION_LABEL_HOLD,
                {}, "", "",
            )
            self.assertEqual(res["delta"], 0)
            mock_gen.assert_not_called()

    def test_score_none_skips_ai_call(self):
        with patch.object(ai_logic, "generate_text") as mock_gen:
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", None, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
            )
            self.assertEqual(res["delta"], 0)
            mock_gen.assert_not_called()

    def test_plus2_token_recognized(self):
        with patch.object(ai_logic, "generate_text",
                          return_value="[+2]\n어닝 서프라이즈로 패러다임 전환 강도 상승"):
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", 60, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
            )
            self.assertEqual(res["delta"], 2)

    def test_minus2_token_recognized(self):
        with patch.object(ai_logic, "generate_text",
                          return_value="[-2]\n임상 실패와 산업 위축 동시 발생"):
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", 60, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
            )
            self.assertEqual(res["delta"], -2)

    def test_plus1_token_priority_over_2(self):
        # head 라인이 '[+1]' 인 경우 +1 만 매칭 (정확 매칭).
        with patch.object(ai_logic, "generate_text",
                          return_value="[+1]\n온건한 호재"):
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", 60, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
            )
            self.assertEqual(res["delta"], 1)

    def test_max_abs_delta_one_blocks_plus2(self):
        # 호출자가 ±1 만 허용한 경우 ±2 토큰은 무시되어 ±1 매칭이 안 되면 폴백.
        with patch.object(ai_logic, "generate_text",
                          return_value="[+2]\n강한 호재"):
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", 60, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
                max_abs_delta=1,
            )
            # head 에 '+2' 만 있으므로 ±1 매칭 실패 → 폴백 0.
            self.assertEqual(res["delta"], 0)

    def test_ambiguous_response_falls_back(self):
        with patch.object(ai_logic, "generate_text",
                          return_value="판단 보류\n추가 정보 필요"):
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", 60, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
            )
            self.assertEqual(res["delta"], 0)
            self.assertEqual(
                res["reason"], ai_logic.FALLBACK_REASON_AMBIGUOUS,
            )

    def test_keep_token_returns_zero(self):
        with patch.object(ai_logic, "generate_text",
                          return_value="[유지]\n정성적 가중치 결론 모호"):
            res = ai_logic.review_opinion_with_ai(
                "000001", "TestCo", 60, mt.OPINION_LABEL_CAUTION,
                {}, "", "",
            )
            self.assertEqual(res["delta"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
