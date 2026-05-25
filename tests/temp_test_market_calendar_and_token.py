# -*- coding: utf-8 -*-
"""거래일·토큰 정책·단타 세션 영속화 단위 테스트.

실행: venv/bin/python3 tests/temp_test_market_calendar_and_token.py
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.utils.timekit import KST
from src.utils import market_calendar as mc
from src.core import token_manager as tm
from src.memory import scalp_session_store as store
from src.utils import slack_interface as si


class TestMarketCalendar(unittest.TestCase):
    def setUp(self):
        mc.load_holiday_date_set(reload=True)

    def test_weekend_not_trading_day(self):
        sat = datetime(2026, 5, 23, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(sat))

    def test_holiday_not_trading_day(self):
        holiday = datetime(2026, 1, 1, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(holiday))

    def test_weekday_non_holiday_is_trading_day(self):
        day = datetime(2026, 5, 22, 10, 0, tzinfo=KST)  # 금요일
        self.assertTrue(mc.is_trading_day(day))

    def test_market_hours_before_open(self):
        pre = datetime(2026, 5, 22, 8, 50, tzinfo=KST)
        self.assertFalse(mc.is_market_hours(pre))

    def test_market_hours_during_session(self):
        mid = datetime(2026, 5, 22, 10, 0, tzinfo=KST)
        self.assertTrue(mc.is_market_hours(mid))

    def test_first_trading_day_when_monday_holiday(self):
        # 2026-03-02 (월)은 삼일절 대체공휴일 → 거래일 아님.
        # 2026-03-03 (화)이 그 주의 첫 거래일.
        mon = datetime(2026, 3, 2, 9, 0, tzinfo=KST)
        tue = datetime(2026, 3, 3, 9, 0, tzinfo=KST)
        self.assertFalse(mc.is_first_trading_day_of_week(mon))
        self.assertTrue(mc.is_first_trading_day_of_week(tue))

    def test_substitute_holiday_2026_05_25_buddha(self):
        """2026-05-25 부처님오신날 대체공휴일 (5/24 일요일) — 거래일 아님."""
        day = datetime(2026, 5, 25, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))
        self.assertFalse(mc.is_market_hours(day))

    def test_substitute_holiday_2026_08_17_liberation(self):
        """2026-08-17 광복절 대체공휴일 (8/15 토요일) — 거래일 아님."""
        day = datetime(2026, 8, 17, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))

    def test_election_day_2026_06_03(self):
        """2026-06-03 제8회 전국동시지방선거 — 거래일 아님."""
        day = datetime(2026, 6, 3, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))

    def test_constitution_day_2026_07_17(self):
        """2026-07-17 제헌절 부활 — 거래일 아님."""
        day = datetime(2026, 7, 17, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))

    def test_chuseok_2026_correct_dates(self):
        """2026 추석은 9/24~25 (목/금). 10/6~10/8 은 정상 거래일."""
        self.assertFalse(mc.is_trading_day(datetime(2026, 9, 24, 10, 0, tzinfo=KST)))
        self.assertFalse(mc.is_trading_day(datetime(2026, 9, 25, 10, 0, tzinfo=KST)))
        self.assertTrue(mc.is_trading_day(datetime(2026, 10, 6, 10, 0, tzinfo=KST)))
        self.assertTrue(mc.is_trading_day(datetime(2026, 10, 7, 10, 0, tzinfo=KST)))
        self.assertTrue(mc.is_trading_day(datetime(2026, 10, 8, 10, 0, tzinfo=KST)))

    def test_holiday_label_lookup(self):
        """get_holiday_label 이 사유 라벨을 정확히 반환."""
        label = mc.get_holiday_label(datetime(2026, 5, 25, 10, 0, tzinfo=KST))
        self.assertIsNotNone(label)
        self.assertIn("부처님오신날", label)
        # 거래일은 None
        self.assertIsNone(mc.get_holiday_label(datetime(2026, 5, 22, 10, 0, tzinfo=KST)))
        # 토/일은 "주말"
        self.assertEqual(
            mc.get_holiday_label(datetime(2026, 5, 23, 10, 0, tzinfo=KST)),
            "주말",
        )

    def test_holiday_load_status(self):
        """get_holiday_load_status 가 정상 dict 를 반환."""
        status = mc.get_holiday_load_status()
        self.assertTrue(status["loaded"])
        self.assertTrue(status["file_exists"])
        self.assertGreater(status["count"], 0)
        self.assertEqual(status["schema_version"], 2)

    def test_auto_discovery_guard_holiday(self):
        from src.execution.orchestrator import MarketOrchestrator
        from unittest.mock import MagicMock

        orch = MarketOrchestrator(MagicMock(), MagicMock(), {})
        with patch("src.execution.orchestrator.market_hours.is_trading_day", return_value=False):
            with patch.object(orch, "send_slack") as slack_mock:
                orch.auto_stock_discovery(KST)
        slack_mock.assert_not_called()


class TestChronicleTradingDayGuard(unittest.TestCase):
    """write_chronicle_for_today 가 거래일이 아닐 때 거부하는지 검증."""

    def setUp(self):
        mc.load_holiday_date_set(reload=True)

    def test_skip_on_weekend(self):
        """주말이면 write_chronicle_for_today 가 거부 메시지 반환."""
        from src.memory import chronicle_writer
        from unittest.mock import MagicMock

        sat = datetime(2026, 5, 23, 16, 0, tzinfo=KST)
        with patch("src.memory.chronicle_writer.now_kst", return_value=sat):
            ok, msg = chronicle_writer.write_chronicle_for_today(
                {"VIX": 30.0, "KOSPI_CHG": -2.0, "KOSDAQ_CHG": -2.0},
                us_news=[], kr_news=[], notify_fn=MagicMock(),
            )
        self.assertFalse(ok)
        self.assertIn("거래일", msg)

    def test_skip_on_holiday(self):
        """평일 대체공휴일(2026-05-25 부처님오신날 대체)이면 거부."""
        from src.memory import chronicle_writer
        from unittest.mock import MagicMock

        holiday = datetime(2026, 5, 25, 16, 0, tzinfo=KST)
        with patch("src.memory.chronicle_writer.now_kst", return_value=holiday):
            ok, msg = chronicle_writer.write_chronicle_for_today(
                {"VIX": 30.0, "KOSPI_CHG": -2.0, "KOSDAQ_CHG": -2.0},
                us_news=[], kr_news=[], notify_fn=MagicMock(),
            )
        self.assertFalse(ok)
        self.assertIn("거래일", msg)

    def test_trading_day_passes_guard(self):
        """거래일이면 거래일 가드는 통과하고 다음 단계(트리거 조건)에서 평가."""
        from src.memory import chronicle_writer
        from unittest.mock import MagicMock

        trading = datetime(2026, 5, 22, 16, 0, tzinfo=KST)  # 금
        # 트리거 조건 미충족 시 "크로니클 트리거 조건 미충족" 메시지가 나오면
        # 거래일 가드는 통과한 것이다.
        with patch("src.memory.chronicle_writer.now_kst", return_value=trading):
            ok, msg = chronicle_writer.write_chronicle_for_today(
                {"VIX": 10.0, "KOSPI_CHG": 0.1, "KOSDAQ_CHG": 0.1},
                us_news=[], kr_news=[], notify_fn=MagicMock(),
            )
        self.assertFalse(ok)
        self.assertNotIn("거래일", msg)
        self.assertIn("트리거", msg)


class TestManualRegisteredStopLossPolicy(unittest.TestCase):
    """수동등록 종목은 추적익절만 자동매도 — daily_fundamental_stop_loss 정책 검증."""

    def _run_daily_with_portfolio(self, portfolio, current_price):
        """daily_fundamental_stop_loss 를 mock 환경에서 1회 실행하고 trigger_reason 캡쳐."""
        from src.execution import orchestrator as orch_mod
        from src.execution.orchestrator import MarketOrchestrator
        from unittest.mock import MagicMock

        kis = MagicMock()
        kis.get_valuation_data.return_value = {"current_price": current_price}
        orch = MarketOrchestrator(kis, MagicMock(), {
            "APP_KEY": "x", "SECRET_KEY": "y", "URL": "z", "ACC_NO": "0",
        })

        captured = {"submitted": []}

        class MockOM:
            def __init__(self, *a, **kw):
                pass

            def submit(self, req):
                captured["submitted"].append(req)
                return {"success": True, "msg": f"{req.ticker} 매도 OK"}

        with patch.object(orch_mod, "market_hours") as mh, \
             patch.object(orch_mod, "load_json_from_gdrive") as load_mock, \
             patch.object(orch_mod, "save_json_to_gdrive"), \
             patch.object(orch_mod, "token_manager") as tm_mock, \
             patch.object(orch_mod, "OrderManager", MockOM), \
             patch.object(orch_mod, "macro_collector") as macro_mock, \
             patch.object(orch_mod, "ai_strategy") as ai_mock, \
             patch.object(orch_mod, "chart_data") as chart_mock, \
             patch.object(orch, "send_slack"):

            mh.is_market_open.return_value = True
            load_mock.side_effect = lambda name: (
                dict(portfolio) if name == "paper_portfolio.json" else {}
            )
            tm_mock.get_access_token.return_value = "T"
            macro_mock.get_macro_indicators.return_value = {}
            chart_mock.get_daily_ohlcv.return_value = []
            # 펀더멘털 훼손 진단을 항상 [펀더멘털훼손] 으로 강제 → 자동 종목엔 매도,
            # 수동 종목엔 호출 자체 차단 여부 검증.
            ai_mock.check_fundamental_damage.return_value = "[펀더멘털훼손] 매출 절벽"

            orch.daily_fundamental_stop_loss()
            return captured["submitted"], ai_mock.check_fundamental_damage

    def test_manual_skip_principal_stop_loss(self):
        """수동등록 종목은 원금 -10% 이탈에도 자동 매도 안 한다."""
        portfolio = {
            "000001": {
                "name": "수동주식", "quantity": 10,
                "avg_price": 10000, "mode_type": "PAPER_ONLY",
                "reason": "수동등록 | AI 팩트체크 완료",
            },
        }
        # 현재가가 평균가의 -15% 라도 (원금손절 트리거) 수동등록이면 SKIP.
        submitted, dmg_mock = self._run_daily_with_portfolio(portfolio, current_price=8500)
        self.assertEqual(submitted, [], "수동등록 종목은 원금손절로 자동 매도되면 안 됨")
        dmg_mock.assert_not_called()

    def test_manual_skip_fundamental_damage(self):
        """수동등록 종목은 AI 펀더멘털 훼손 판정에도 자동 매도 안 한다."""
        portfolio = {
            "000002": {
                "name": "수동주식2", "quantity": 5,
                "avg_price": 10000, "mode_type": "PAPER_ONLY",
                "reason": "수동등록 | TRACK_M",
            },
        }
        # 현재가는 평균가 부근(-5%) — 추적익절도 원금손절도 트리거 안 됨.
        submitted, dmg_mock = self._run_daily_with_portfolio(portfolio, current_price=9500)
        self.assertEqual(submitted, [], "수동등록은 펀더멘털 훼손 매도 트리거되면 안 됨")
        # AI 호출 자체가 일어나면 안 됨 (토큰 절약 + 정책 일관성).
        dmg_mock.assert_not_called()

    def test_manual_allows_trailing_stop(self):
        """수동등록 종목도 최고점 대비 -10% 추적익절은 동작한다."""
        portfolio = {
            "000003": {
                "name": "수동주식3", "quantity": 3,
                "avg_price": 10000, "mode_type": "PAPER_ONLY",
                "high_water_mark": 15000,  # 50% 상승 후
                "reason": "수동등록 | TRACK_A",
            },
        }
        # 최고점 15000 의 -10% = 13500. 그 아래로 떨어지면 추적익절.
        submitted, _ = self._run_daily_with_portfolio(portfolio, current_price=13000)
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0].reason,
                         "최고점 대비 하락선(-10%) 이탈 (추적 익절/손절)")

    def test_auto_stock_applies_full_defense(self):
        """자동발굴/AI매수 종목은 원금손절/펀더멘털훼손까지 3중 방어막 적용."""
        portfolio = {
            "000004": {
                "name": "자동주식", "quantity": 10,
                "avg_price": 10000, "mode_type": "NORMAL",
                "reason": "AI 자동발굴 (기대주_발굴)",
            },
        }
        submitted, _ = self._run_daily_with_portfolio(portfolio, current_price=8500)
        self.assertEqual(len(submitted), 1)
        self.assertIn("원금 방어선", submitted[0].reason)


class TestTokenPolicy(unittest.TestCase):
    def setUp(self):
        self.token_path = tm._token_path()
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def tearDown(self):
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def test_scheduled_skip_on_holiday(self):
        with patch("src.utils.market_calendar.is_trading_day", return_value=False):
            result = tm.issue_scheduled_token("k", "s")
        self.assertFalse(result["issued"])
        self.assertEqual(result["reason"], "not_trading_day")

    def test_on_demand_issues_when_cache_missing(self):
        with patch.object(tm, "_request_new_token", return_value="NEW_TOKEN") as req:
            token = tm.get_access_token("k", "s", context="on_demand")
        self.assertEqual(token, "NEW_TOKEN")
        req.assert_called_once()

    def test_scheduled_respects_min_interval(self):
        recent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        from src.utils.jsonio import write_local_json
        write_local_json(tm._token_path(), {
            "access_token": "OLD",
            "issued_at": recent,
        }, indent=2)
        with patch("src.utils.market_calendar.is_trading_day", return_value=True):
            with patch.object(tm, "_request_new_token") as req:
                result = tm.issue_scheduled_token("k", "s")
        self.assertFalse(result["issued"])
        self.assertEqual(result["reason"], "min_interval")
        req.assert_not_called()


class TestScalpSessionStore(unittest.TestCase):
    def setUp(self):
        self.drive_patcher = patch("src.utils.logger._use_drive_storage", return_value=False)
        self.drive_patcher.start()
        si.reset_weekly_budget_session()
        si.stop_scalp_trading()
        si.clear_scalp_position()
        self.session_file = os.path.join(ROOT, store.SCALP_SESSION_FILENAME)
        if os.path.exists(self.session_file):
            os.remove(self.session_file)

    def tearDown(self):
        self.drive_patcher.stop()
        if os.path.exists(self.session_file):
            os.remove(self.session_file)

    def test_persist_and_restore(self):
        si._scalp_session_dict["is_user_running"] = True
        si.set_weekly_budget(50_000, via="test")
        self.assertTrue(store.persist_scalp_session_from_module())
        loaded = store.load_scalp_session()
        self.assertIsInstance(loaded, dict)
        self.assertTrue(loaded.get("is_user_running"))
        self.assertEqual(loaded.get("amount"), 50_000)
        # 로컬 fallback 경로에도 기록 (Drive 비활성 테스트)
        self.assertTrue(os.path.exists(self.session_file))
        # 메모리만 초기화 (저장본은 유지)
        si._scalp_session_dict["is_user_running"] = False
        si._scalp_session_dict["amount"] = None
        result = store.restore_scalp_session_to_module()
        self.assertTrue(result["restored"])
        self.assertTrue(si.is_scalp_user_running())
        self.assertEqual(si.get_weekly_budget(), 50_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
