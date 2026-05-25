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
        # 2026-03-02 월요일(거래일), 2026-03-01 일요일+공휴일
        mon = datetime(2026, 3, 2, 9, 0, tzinfo=KST)
        self.assertTrue(mc.is_first_trading_day_of_week(mon))

    def test_auto_discovery_guard_holiday(self):
        from src.execution.orchestrator import MarketOrchestrator
        from unittest.mock import MagicMock

        orch = MarketOrchestrator(MagicMock(), MagicMock(), {})
        with patch("src.execution.orchestrator.market_hours.is_trading_day", return_value=False):
            with patch.object(orch, "send_slack") as slack_mock:
                orch.auto_stock_discovery(KST)
        slack_mock.assert_not_called()


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
