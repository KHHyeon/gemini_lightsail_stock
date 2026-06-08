# -*- coding: utf-8 -*-
"""Scalp Phase Upgrade 테스트.

검증 범위:
1) Top-K / soft-margin 환경변수 파싱
2) 변동성 타깃 수량 산출
3) 메타라벨링 데이터셋 기록/라벨 확정
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.memory import scalp_meta_dataset
from src.strategy import scalp_logic


class TestScalpPhaseUpgrade(unittest.TestCase):
    def test_env_topk_and_soft_margin(self):
        with patch.dict(os.environ, {"SCALP_TOP_K": "5", "SCALP_SIMILARITY_SOFT_MARGIN": "0.03"}):
            self.assertEqual(scalp_logic.scalp_top_k(), 5)
            self.assertAlmostEqual(scalp_logic.scalp_similarity_soft_margin(), 0.03, places=6)

        with patch.dict(os.environ, {"SCALP_TOP_K": "bad", "SCALP_SIMILARITY_SOFT_MARGIN": "bad"}):
            self.assertEqual(scalp_logic.scalp_top_k(), 3)
            self.assertAlmostEqual(scalp_logic.scalp_similarity_soft_margin(), 0.02, places=6)

    def test_vol_targeted_qty(self):
        # 변동성 낮음 -> scale 상한(1.0) 근접
        qty_low, scale_low = scalp_logic.calc_vol_targeted_buy_qty(
            100_000, 10_000, realized_vol_ratio=0.005
        )
        self.assertEqual(qty_low, 10)
        self.assertAlmostEqual(scale_low, 1.0, places=6)

        # 변동성 높음 -> scale 축소
        qty_high, scale_high = scalp_logic.calc_vol_targeted_buy_qty(
            100_000, 10_000, realized_vol_ratio=0.04
        )
        self.assertLess(qty_high, 10)
        self.assertGreaterEqual(scale_high, 0.35)
        self.assertLessEqual(scale_high, 1.0)

    def test_meta_dataset_record_and_finalize(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_file = os.path.join(td, "scalp_meta_signals.json")
            with patch("src.memory.scalp_meta_dataset._dataset_path", return_value=tmp_file):
                signal_id = scalp_meta_dataset.record_entry_signal(
                    "005930",
                    {
                        "similarity": 0.82,
                        "threshold": 0.80,
                        "margin": 0.02,
                        "vix_score": 17.0,
                        "vol_scale": 0.7,
                    },
                )
                self.assertTrue(signal_id)
                ok = scalp_meta_dataset.finalize_signal_label(
                    signal_id,
                    is_win=True,
                    pnl_ratio=0.0123,
                    exit_reason="TRAILING_STOP",
                )
                self.assertTrue(ok)

                with open(tmp_file, "r", encoding="utf-8") as fp:
                    root = json.load(fp)
                meta = root.get("metadata") or {}
                signals = root.get("signals") or []
                self.assertEqual(meta.get("total_signals"), 1)
                self.assertEqual(meta.get("pending_signals"), 0)
                self.assertEqual(meta.get("labeled_signals"), 1)
                self.assertAlmostEqual(meta.get("win_rate"), 1.0, places=6)
                self.assertEqual(signals[0].get("label"), "WIN")
                self.assertEqual((signals[0].get("outcome") or {}).get("exit_reason"), "TRAILING_STOP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
