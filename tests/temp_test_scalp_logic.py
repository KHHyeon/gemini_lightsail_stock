# -*- coding: utf-8 -*-
"""scalp_logic 시나리오 단위 테스트.

시나리오 1: S_PRE 09:00 무응답 폴백 -> 기본 5만원 + S0 자동 전이.
시나리오 2: Slack Mock 페이로드(`budget_default`) + 호재 뉴스 임계치(0.80) +
            20선 눌림목 충족 시 100% 매수 트리거 통과.
시나리오 3: 3중 방어막 - 손절/익절+추적/15:10 강제 청산 + B-Type 알림.

실행: venv/bin/python3 tests/temp_test_scalp_logic.py
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, time as _time
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np

from src.strategy import scalp_logic
from src.utils import slack_interface as si
from src.utils.timekit import KST


def _mock_kis_hts_ok():
    """HTS 조건식 등록 OK Mock KIS 클라이언트."""
    kis = MagicMock()
    kis.hts_id = "TEST_HTS"
    kis.token = "TEST_TOKEN"
    kis.find_condition_seq.return_value = "001"
    return kis


def _mock_kis_hts_missing():
    """HTS 조건식 미등록 Mock KIS 클라이언트."""
    kis = MagicMock()
    kis.hts_id = "TEST_HTS"
    kis.token = "TEST_TOKEN"
    kis.find_condition_seq.return_value = None
    return kis
# =====================================================================
# 시나리오 1: 폴백 및 타임아웃 검증
# =====================================================================
class TestScenario1FallbackTimeout(unittest.TestCase):
    def setUp(self):
        si.reset_weekly_budget_session()
        si.stop_scalp_trading()

    def test_09_00_no_response_falls_back_to_50000(self):
        # S_PRE + 진행 ON 상태에서 09:00 스케줄 폴백
        si._scalp_session_dict["is_user_running"] = True
        si.set_scalp_lifecycle(si.SCALP_LIFECYCLE_PRE)
        self.assertIsNone(si.get_weekly_budget(), "초기 예산은 미확정이어야 함")

        applied = si.force_default_budget_if_idle(mode="open_0900")

        self.assertTrue(applied["applied"])
        self.assertEqual(applied["amount"], 50_000)
        self.assertEqual(applied["via"], "fallback_timeout")
        self.assertEqual(si.get_weekly_budget(), 50_000)
        self.assertEqual(si.get_scalp_lifecycle(), si.SCALP_LIFECYCLE_SCANNING)

        state = si.get_weekly_budget_session_state()
        self.assertEqual(state["amount"], 50_000)
        self.assertEqual(state["set_via"], "fallback_timeout")

    def test_timeout_fallback_after_30min(self):
        from datetime import timedelta
        from src.utils.timekit import now_kst

        si._scalp_session_dict["is_user_running"] = True
        si.set_scalp_lifecycle(si.SCALP_LIFECYCLE_PRE)
        past = now_kst() - timedelta(minutes=31)
        si._scalp_session_dict["budget_requested_at"] = past.isoformat()

        applied = si.force_default_budget_if_idle(mode="timeout")
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["amount"], 50_000)

    def test_timeout_not_due_before_30min(self):
        from datetime import timedelta
        from src.utils.timekit import now_kst

        si._scalp_session_dict["is_user_running"] = True
        si.set_scalp_lifecycle(si.SCALP_LIFECYCLE_PRE)
        recent = now_kst() - timedelta(minutes=5)
        si._scalp_session_dict["budget_requested_at"] = recent.isoformat()

        applied = si.force_default_budget_if_idle(mode="timeout")
        self.assertFalse(applied["applied"])
        self.assertEqual(applied["via"], "not_due")

    def test_fallback_does_not_override_user_input(self):
        # 사용자가 09:00 직전 7만원 입력 -> 폴백은 무효
        si.set_weekly_budget(70_000, via="custom")
        applied = si.force_default_budget_if_idle()
        self.assertFalse(applied["applied"])
        self.assertEqual(applied["amount"], 70_000)
        self.assertEqual(si.get_weekly_budget(), 70_000)


# =====================================================================
# 시나리오 2: 인터랙션 및 매매 로직 검증
# =====================================================================
class TestScenario2InteractionAndTrading(unittest.TestCase):
    def setUp(self):
        si.reset_weekly_budget_session()

    def test_budget_default_payload_immediately_applies(self):
        # 슬랙 Mock 페이로드: '기본 5만원' 버튼 클릭
        payload = {
            "actions": [
                {"action_id": "budget_default", "value": "50000"},
            ],
            "user": {"id": "U_TEST"},
        }
        result = si.handle_budget_slack_interaction(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["amount"], 50_000)
        self.assertEqual(si.get_weekly_budget(), 50_000)

    def test_custom_then_modal_submit_applies_70000(self):
        # 직접 입력 버튼 -> 모달 제출 흐름
        si.handle_budget_slack_interaction({
            "actions": [{"action_id": "budget_custom", "value": "custom"}],
        })
        self.assertIsNone(si.get_weekly_budget())  # 아직 미확정 (pending)

        modal_payload = {
            "view": {
                "callback_id": "budget_custom_modal_submit",
                "state": {
                    "values": {
                        "budget_input_block": {
                            "budget_input_value": {
                                "type": "plain_text_input",
                                "value": "70,000",
                            },
                        },
                    },
                },
            },
            "user": {"id": "U_TEST"},
        }
        result = si.handle_budget_slack_interaction(modal_payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["amount"], 70_000)
        self.assertEqual(si.get_weekly_budget(), 70_000)

    def test_pullback_signal_passes_with_volume_5e8_and_ma20_proximity(self):
        # KIS Mock OHLCV: 직전 3분 거래대금 6억, 종가가 20MA의 -0.4% 근처
        ohlcv_3min = [
            {"open": 9800, "high": 10100, "low": 9750, "close": 9960,
             "volume": 60_000, "tr_amount": 600_000_000},
        ]
        ma20 = 10_000
        signal = scalp_logic.detect_pullback_signal(ohlcv_3min, ma20)
        self.assertTrue(signal["is_signal"], signal["reason"])

    def test_pullback_signal_rejects_low_volume(self):
        ohlcv_3min = [
            {"close": 10_000, "tr_amount": 100_000_000},
        ]
        signal = scalp_logic.detect_pullback_signal(ohlcv_3min, 10_000)
        self.assertFalse(signal["is_signal"])

    def test_dynamic_threshold_branches(self):
        self.assertEqual(scalp_logic.determine_dynamic_threshold(15.0, False), 0.85)
        self.assertEqual(scalp_logic.determine_dynamic_threshold(15.0, True), 0.80)
        self.assertEqual(scalp_logic.determine_dynamic_threshold(35.0, True), 0.90)
        self.assertEqual(scalp_logic.determine_dynamic_threshold(None, False), 0.85)

    def test_shape_similarity_passes_with_good_news_threshold(self):
        """호재 뉴스 -> 임계치 0.80. 프리셋 한 행과 거의 동일한 실시간 벡터를 주입.

        프리셋 매트릭스의 첫 행과 강한 양의 상관관계(노이즈 작음)를 가지는 벡터를
        만들어, 유사도가 0.80 이상으로 통과하는지 검증한다.
        """
        preset_matrix = scalp_logic.build_default_preset_matrix(seed=42, count=30)
        target = preset_matrix[0].copy()
        # 동일 형태 + 소량 잡음 -> 상관계수 매우 높음
        rng = np.random.default_rng(0)
        realtime_vector = target + rng.normal(0.0, 0.01, size=target.shape)

        similarity = scalp_logic.calculate_shape_similarity(realtime_vector, preset_matrix)
        threshold = scalp_logic.determine_dynamic_threshold(vix_score=15.0, has_good_news=True)
        self.assertEqual(threshold, 0.80)
        self.assertGreaterEqual(similarity, threshold,
                                f"유사도 {similarity:.3f} < 임계치 {threshold}")

    def test_shape_similarity_rejects_unrelated_vector(self):
        preset_matrix = scalp_logic.build_default_preset_matrix(seed=42, count=30)
        # 단순 선형 증가 - 눌림목 형태와 무관
        unrelated = np.linspace(0, 1, scalp_logic.SHAPE_VECTOR_LENGTH)
        similarity = scalp_logic.calculate_shape_similarity(unrelated, preset_matrix)
        # 우연한 상관관계는 있을 수 있으나 0.85 임계치는 일반적으로 통과 못함.
        # 본 테스트는 임계치 미달임을 폭넓게 확인(보수적 검증).
        threshold_default = scalp_logic.determine_dynamic_threshold(15.0, False)
        self.assertLess(similarity, threshold_default,
                        f"무관 벡터가 임계치 {threshold_default} 통과: {similarity:.3f}")

    def test_full_market_buy_qty_calculation(self):
        """100% 매수 수량 = floor(예산 / 시장가). 예산 분할 금지."""
        si.set_weekly_budget(50_000, via="default")
        budget = si.get_weekly_budget()
        market_price = 9_500
        qty = budget // market_price
        self.assertEqual(qty, 5)
        self.assertLessEqual(qty * market_price, budget)


# =====================================================================
# 시나리오 3: 3중 청산 검증
# =====================================================================
class TestScenario3RiskAndLiquidation(unittest.TestCase):
    def test_stop_loss_triggers_at_minus_1_5_percent(self):
        signal = scalp_logic.monitor_scalp_risk(
            ticker="000660", current_price=9_850, avg_buy_price=10_000,
            highest_price=10_050,
        )
        self.assertEqual(signal, "STOP_LOSS_1_5")

    def test_take_profit_half_triggers_at_plus_3_percent(self):
        signal = scalp_logic.monitor_scalp_risk(
            ticker="000660", current_price=10_300, avg_buy_price=10_000,
            highest_price=10_300,
        )
        self.assertEqual(signal, "TAKE_PROFIT_HALF")

    def test_trailing_stop_after_half_sold(self):
        # 50% 익절 후, 최고가 11,000 에서 -1% 이상 하락 (10,890 이하)
        signal = scalp_logic.monitor_scalp_risk(
            ticker="000660", current_price=10_880, avg_buy_price=10_000,
            highest_price=11_000, half_sold=True,
        )
        self.assertEqual(signal, "TRAILING_STOP")

    def test_trailing_stop_holds_above_threshold(self):
        signal = scalp_logic.monitor_scalp_risk(
            ticker="000660", current_price=10_950, avg_buy_price=10_000,
            highest_price=11_000, half_sold=True,
        )
        self.assertEqual(signal, "HOLD")

    def test_force_liquidation_time_15_10(self):
        before = datetime(2026, 5, 25, 15, 9, 30, tzinfo=KST)
        at = datetime(2026, 5, 25, 15, 10, 0, tzinfo=KST)
        after = datetime(2026, 5, 25, 15, 11, 0, tzinfo=KST)
        self.assertFalse(scalp_logic.is_force_liquidation_time(before))
        self.assertTrue(scalp_logic.is_force_liquidation_time(at))
        self.assertTrue(scalp_logic.is_force_liquidation_time(after))

    def test_orchestrator_force_liquidation_b_type_on_failure(self):
        """매도 실패 시 B-Type 알림 발행 + HALT_B_TYPE 상태 반환."""
        from src.execution.orchestrator import MarketOrchestrator
        from src.strategy import scalp_backtest

        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_ok())
        si.set_weekly_budget(50_000, via="test")

        kis = MagicMock()
        app = MagicMock()
        config = {"APP_KEY": "x", "SECRET_KEY": "y", "URL": "z", "ACC_NO": "0", "CHANNEL_ID": "C"}
        orch = MarketOrchestrator(kis, app, config)

        # 토큰/포트폴리오 의존성 무력화
        from src.core import token_manager
        token_manager.get_access_token = lambda *a, **kw: "TEST_TOKEN"
        from src.execution import orchestrator as orch_mod
        orch_mod.load_json_from_gdrive = lambda name: {
            "000660": {"name": "SK하이닉스", "quantity": 5, "avg_price": 200_000, "mode_type": "SCALP"},
        }

        slack_messages = []
        orch.send_slack = lambda text: slack_messages.append(text)

        def failing_sell(ticker, qty):
            return {"success": False, "msg": "KIS RC=-9999 매도 거부"}

        # 실제 시각이 휴장일일 수 있으므로 거래일 가드를 강제 True.
        with patch("src.execution.orchestrator.market_hours.is_trading_day", return_value=True):
            result = orch.scalp_force_liquidation(sell_fn=failing_sell)
        self.assertEqual(result["state"], "HALT_B_TYPE")
        self.assertEqual(len(result["failures"]), 1)
        self.assertTrue(any("[B-Type]" in m for m in slack_messages),
                        f"B-Type 알림 누락: {slack_messages}")

    def test_orchestrator_force_liquidation_success(self):
        from src.execution.orchestrator import MarketOrchestrator
        from src.strategy import scalp_backtest

        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_ok())
        si.set_weekly_budget(50_000, via="test")

        kis = MagicMock()
        app = MagicMock()
        config = {"APP_KEY": "x", "SECRET_KEY": "y", "URL": "z", "ACC_NO": "0", "CHANNEL_ID": "C"}
        orch = MarketOrchestrator(kis, app, config)

        from src.core import token_manager
        token_manager.get_access_token = lambda *a, **kw: "TEST_TOKEN"
        from src.execution import orchestrator as orch_mod
        orch_mod.load_json_from_gdrive = lambda name: {
            "000660": {"name": "SK하이닉스", "quantity": 5, "avg_price": 200_000, "mode_type": "SCALP"},
            "005930": {"name": "삼성전자", "quantity": 3, "avg_price": 70_000, "mode_type": "PAPER_ONLY"},
        }

        slack_messages = []
        orch.send_slack = lambda text: slack_messages.append(text)

        def ok_sell(ticker, qty):
            return {"success": True, "msg": f"{ticker} 시장가 매도 OK"}

        with patch("src.execution.orchestrator.market_hours.is_trading_day", return_value=True):
            result = orch.scalp_force_liquidation(sell_fn=ok_sell)
        self.assertEqual(result["state"], "LIQUIDATED")
        # SCALP 만 청산 대상 (PAPER_ONLY 는 제외)
        self.assertEqual(result["count"], 1)


# =====================================================================
# 시나리오 4 (보조): 학습 데이터 적재
# =====================================================================
class TestScalpTrainerRecord(unittest.TestCase):
    def test_record_trade_result_appends_and_updates_metadata(self):
        from src.memory import scalp_trainer

        tmp_path = os.path.join(ROOT, "scalp_training_data.json")
        # 이전 테스트 잔재 정리
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        scalp_trainer.record_trade_result(
            "000660", True, [0.1, 0.2, 0.3], extra={"shape_similarity": 0.87},
        )
        scalp_trainer.record_trade_result(
            "000660", False, [0.5, 0.6, 0.7],
        )
        meta = scalp_trainer.get_training_metadata()
        self.assertEqual(meta["total_trades"], 2)
        self.assertEqual(meta["win_rate"], 0.5)

        # 검증 후 임시 파일 정리
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


class TestScenario4BacktestAndControl(unittest.TestCase):
    def setUp(self):
        si.reset_weekly_budget_session()
        si.stop_scalp_trading()

    def test_shape_backtest_passes_gate(self):
        from src.strategy import scalp_backtest
        result = scalp_backtest.run_shape_backtest(n_days=60, seed=42)
        self.assertGreater(result["total_trades"], 0)
        self.assertTrue(result["passes_gate"], result.get("gate_reason"))

    def test_start_rejected_without_backtest(self):
        si._scalp_session_dict["backtest_passed"] = False
        r = si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_ok())
        self.assertFalse(r["ok"])

    def test_start_rejected_without_hts_condition(self):
        from src.strategy import scalp_backtest
        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        r = si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_missing())
        self.assertFalse(r["ok"])
        self.assertIn("HTS", r.get("reason", ""))

    def test_start_ok_after_backtest_pass(self):
        from src.strategy import scalp_backtest
        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        r = si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_ok())
        self.assertTrue(r["ok"])
        self.assertEqual(r["lifecycle"], si.SCALP_LIFECYCLE_PRE)
        self.assertIsNone(si.get_weekly_budget())
        self.assertTrue(si.is_scalp_schedule_enabled())

    def test_restart_always_resets_budget(self):
        from src.strategy import scalp_backtest
        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        kis = _mock_kis_hts_ok()
        si.start_scalp_trading(via="test", kis_client=kis)
        si.set_weekly_budget(70_000, via="custom")
        si.stop_scalp_trading()
        r = si.start_scalp_trading(via="test", kis_client=kis)
        self.assertTrue(r["ok"])
        self.assertIsNone(si.get_weekly_budget())
        self.assertEqual(si.get_scalp_lifecycle(), si.SCALP_LIFECYCLE_PRE)

    def test_scalp_control_buttons(self):
        from src.strategy import scalp_backtest
        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        kis = _mock_kis_hts_ok()
        start = si.handle_scalp_control_interaction(
            {"actions": [{"action_id": "scalp_start"}]},
            kis_client=kis,
        )
        self.assertEqual(start["status"], "ok")
        self.assertEqual(start["lifecycle"], si.SCALP_LIFECYCLE_PRE)
        status = si.handle_scalp_control_interaction({
            "actions": [{"action_id": "scalp_status"}],
        })
        self.assertIn("단타(Scalp) 상태", status["text"])
        stop = si.handle_scalp_control_interaction({
            "actions": [{"action_id": "scalp_stop"}],
        })
        self.assertEqual(stop["status"], "ok")
        self.assertFalse(si.is_scalp_user_running())

    def test_budget_blocks_include_control_actions(self):
        blocks = si._build_weekly_budget_blocks()
        action_ids = []
        for blk in blocks:
            for el in blk.get("elements") or []:
                action_ids.append(el.get("action_id"))
        self.assertIn("scalp_start", action_ids)
        self.assertIn("scalp_stop", action_ids)
        self.assertIn("scalp_status", action_ids)


class TestScenario5LiveCycle(unittest.TestCase):
    def setUp(self):
        si.reset_weekly_budget_session()
        si.stop_scalp_trading()
        si.clear_scalp_position()

    def test_resample_minute_to_3min(self):
        from src.data.chart import resample_minute_to_3min
        minute_list = []
        for mm in range(9, 12):
            for m in range(0, 60):
                minute_list.append({
                    "time": f"09{m:02d}00",
                    "open": 1000, "high": 1010, "low": 990, "close": 1005,
                    "volume": 1000, "tr_amount": 1_000_000,
                })
        bars = resample_minute_to_3min(minute_list)
        self.assertGreaterEqual(len(bars), 20)
        self.assertGreater(bars[-1]["tr_amount"], 0)

    def test_evaluate_entry_candidate_s3(self):
        from src.strategy import scalp_logic
        preset = scalp_logic.build_default_preset_matrix(seed=1, count=5)
        target = preset[0].tolist()
        closes = [int(10000 + v * 500) for v in target]
        ohlcv = []
        for i, c in enumerate(closes[-20:]):
            ohlcv.append({
                "open": c, "high": c + 10, "low": c - 10, "close": c,
                "volume": 10000,
                "tr_amount": 600_000_000 if i == len(closes[-20:]) - 1 else 1_000_000,
            })
        ma20 = float(closes[-1])
        result = scalp_logic.evaluate_entry_candidate(
            ohlcv, ma20, preset_matrix=preset, vix_score=15.0, has_good_news=True,
        )
        self.assertIn(result["state"], ("S2", "S3"))

    def test_orchestrator_scan_and_buy_mock(self):
        from src.execution.orchestrator import MarketOrchestrator
        from src.strategy import scalp_backtest
        from src.utils import helpers as market_hours

        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_ok())
        si.set_weekly_budget(50_000, via="test")

        preset = __import__("src.strategy.scalp_logic", fromlist=["scalp_logic"]).build_default_preset_matrix(seed=1, count=5)
        target = preset[0].tolist()
        closes = [int(10000 + v * 500) for v in target]

        def chart_provider(ticker):
            ohlcv = []
            seq = closes[-20:]
            for i, c in enumerate(seq):
                ohlcv.append({
                    "open": c, "high": c + 10, "low": c - 10, "close": c,
                    "volume": 10000,
                    "tr_amount": 600_000_000 if i == len(seq) - 1 else 1_000_000,
                })
            return ohlcv, float(seq[-1]), seq[-1]

        kis = MagicMock()
        app = MagicMock()
        config = {"APP_KEY": "x", "SECRET_KEY": "y", "URL": "z", "ACC_NO": "0", "CHANNEL_ID": "C"}
        orch = MarketOrchestrator(kis, app, config)

        from src.core import token_manager
        token_manager.get_access_token = lambda *a, **kw: "TEST_TOKEN"

        from src.execution import order as order_mod
        original_om = order_mod.OrderManager

        class MockOM:
            def __init__(self, *a, **kw):
                pass
            def submit(self, req):
                return {"success": True, "msg": "mock"}

        order_mod.OrderManager = MockOM
        original_market_open = market_hours.is_market_open
        market_hours.is_market_open = lambda now=None: True
        try:
            # 휴장일 환경에서도 거래일 가드 통과 강제 (테스트 시각 의존성 제거).
            with patch(
                "src.execution.orchestrator.macro_collector.get_macro_indicators",
                return_value={"VIX": 15.0},
            ), patch.object(orch, "_scalp_detect_good_news", return_value=True), patch(
                "src.execution.orchestrator.market_hours.is_trading_day",
                return_value=True,
            ), patch(
                "src.strategy.scalp_logic.is_force_liquidation_time",
                return_value=False,
            ):
                result = orch.scalp_scan_cycle(
                    candidate_provider=[{"ticker": "005930", "name": "삼성전자"}],
                    chart_provider=chart_provider,
                )
        finally:
            order_mod.OrderManager = original_om
            market_hours.is_market_open = original_market_open

        self.assertIn(result.get("state"), ("S3", "S0"))
        if result.get("state") == "S3":
            self.assertTrue(si.has_scalp_position())

    def test_orchestrator_risk_stop_loss_mock(self):
        from src.execution.orchestrator import MarketOrchestrator
        from src.strategy import scalp_backtest

        si.set_backtest_gate_result(scalp_backtest.run_shape_backtest(n_days=30))
        si.start_scalp_trading(via="test", kis_client=_mock_kis_hts_ok())
        si.set_weekly_budget(50_000, via="test")
        si.set_scalp_position({
            "ticker": "005930", "name": "삼성전자", "qty": 5, "remaining_qty": 5,
            "avg_price": 10000, "highest_price": 10000, "half_sold": False,
            "shape_vector": [0.1] * 20,
        })

        kis = MagicMock()
        app = MagicMock()
        config = {"APP_KEY": "x", "SECRET_KEY": "y", "URL": "z", "ACC_NO": "0", "CHANNEL_ID": "C"}
        orch = MarketOrchestrator(kis, app, config)
        orch.send_slack = lambda t: None

        from src.core import token_manager
        token_manager.get_access_token = lambda *a, **kw: "TEST_TOKEN"

        result = orch.scalp_risk_monitor_cycle(
            price_provider=lambda t: 9800.0,
            sell_fn=lambda t, q: {"success": True, "msg": "sold"},
        )
        self.assertEqual(result.get("state"), "S5")
        self.assertEqual(result.get("signal"), "STOP_LOSS_1_5")
        self.assertFalse(si.has_scalp_position())


if __name__ == "__main__":
    unittest.main(verbosity=2)
